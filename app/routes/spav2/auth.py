from flask import Blueprint, request, jsonify, session, current_app, url_for
from datetime import datetime, timedelta
import re
import secrets
from app import db
from app.models import User, EmailVerification, UserSession
from app.utils.helpers import get_current_user
from app.utils.security import rate_limit, validate_password, sanitize_string, account_lockout, note_account_failure, clear_account_failures

spav2_auth_bp = Blueprint('spav2_auth', __name__, url_prefix='/api/auth')

@spav2_auth_bp.route('/register', methods=['POST'])
@rate_limit('register', max_requests=5, window=300)
def register():
    try:
        data = request.get_json() or {}
        username = sanitize_string(data.get('username', ''), max_length=32)
        email = sanitize_string(data.get('email', ''), max_length=128)
        password = data.get('password', '')

        errors = {}
        if len(username) < 3 or not re.match(r'^[a-zA-Z0-9_]+$', username):
            errors['username'] = 'Username must be 3-32 characters (letters, numbers, underscores)'
        if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
            errors['email'] = 'Invalid email format'
        pwd_errors = validate_password(password)
        if pwd_errors:
            errors['password'] = ' '.join(pwd_errors)
        if User.query.filter_by(username=username).first():
            errors['username'] = 'Username already taken'
        if User.query.filter_by(email=email).first():
            errors['email'] = 'Email already registered'
        if errors:
            return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'Validation failed', 'fields': errors}}), 400

        user = User(username=username, email=email, display_name=username, is_online=False, last_seen=datetime.utcnow())
        user.set_password(password)
        user.email_verified = False
        db.session.add(user)
        db.session.flush()

        verify_token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(hours=24)
        db.session.add(EmailVerification(user_id=user.id, token=verify_token, expires_at=expires_at))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': str(e)}}), 500

    from flask import request as req
    verify_url = f"{req.host_url}api.v2/api/auth/verify?token={verify_token}"
    current_app.logger.info(f'Verification token for {username}: {verify_token}')
    print(f'[EMAIL] Verification link: {verify_url}')

    return jsonify({'success': True, 'data': {
        'user': {
            'user_id': user.id,
            'username': user.username,
            'email': user.email,
            'display_name': user.display_name,
            'avatar_url': user.avatar_url,
            'bio': getattr(user, 'bio', None),
            'is_premium': user.premium.is_premium if user.premium else False,
            'is_admin': getattr(user, 'is_admin', False),
            'is_online': False,
            'last_seen': None,
            'created_at': user.created_at.isoformat() if user.created_at else datetime.utcnow().isoformat(),
            'status_emoji': getattr(user, 'status_emoji', '')
        },
        'verification_token': verify_token,
        'message': 'Account created. Please verify your email.'
    }}), 201


@spav2_auth_bp.route('login', methods=['POST'])
@rate_limit('login', max_requests=10, window=60)
@account_lockout(lambda req: (req.get_json(silent=True) or {}).get('username', ''))
def login():
    try:
        data = request.get_json() or {}
        username = sanitize_string(data.get('username', ''), max_length=32)
        password = data.get('password', '')

        if not username or not password:
            return jsonify({'success': False, 'error': {'code': 'INVALID_CREDENTIALS', 'message': 'Invalid username or password'}}), 401

        user = User.query.filter_by(username=username).filter(User.is_deleted == False).first()
        if not user or not user.check_password(password):
            note_account_failure(username)
            return jsonify({'success': False, 'error': {'code': 'INVALID_CREDENTIALS', 'message': 'Invalid username or password'}}), 401

        if not user.email_verified:
            return jsonify({'success': False, 'error': {'code': 'EMAIL_NOT_VERIFIED', 'message': 'Please verify your email first'}}), 403

        session_token = secrets.token_urlsafe(32)
        session['user_id'] = user.id
        session['username'] = user.username
        user.is_online = True
        user.last_seen = datetime.utcnow()
        db.session.add(UserSession(user_id=user.id, session_token=session_token, device='K Web', created_at=datetime.utcnow(), last_activity=datetime.utcnow(), is_active=True))
        db.session.commit()
        clear_account_failures(username)
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': str(e)}}), 500

    return jsonify({'success': True, 'data': {
        'user': {
            'user_id': user.id,
            'username': user.username,
            'email': user.email,
            'display_name': user.display_name or user.username,
            'avatar_url': user.avatar_url,
            'bio': getattr(user, 'bio', None),
            'is_premium': user.premium.is_premium if user.premium else False,
            'is_admin': getattr(user, 'is_admin', False),
            'is_online': True,
            'last_seen': datetime.utcnow().isoformat(),
            'created_at': user.created_at.isoformat() if user.created_at else datetime.utcnow().isoformat(),
            'status_emoji': user.status_emoji or ('\u2b50' if (user.premium and user.premium.is_premium) else '')
        },
        'session_token': session_token
    }})


@spav2_auth_bp.route('logout', methods=['POST'])
@rate_limit('logout', max_requests=10, window=60)
def logout():
    user_id = session.get('user_id')
    if user_id:
        user = User.query.filter(User.id == user_id, User.is_deleted == False).first()
        if user:
            user.is_online = False
            user.last_seen = datetime.utcnow()
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
    session.clear()
    return jsonify({'success': True, 'data': {'message': 'Logged out successfully'}})


@spav2_auth_bp.route('verify', methods=['GET', 'POST'])
@rate_limit('verify', max_requests=20, window=60)
def verify_email():
    token = ''
    if request.method == 'GET':
        token = request.args.get('token', '').strip()
    else:
        data = request.get_json() or {}
        token = data.get('token', '').strip()
    if not token:
        return jsonify({'success': False, 'error': {'code': 'INVALID_TOKEN', 'message': 'Verification token is required'}}), 400

    verification = EmailVerification.query.filter_by(token=token, verified=False).first()
    if not verification:
        return jsonify({'success': False, 'error': {'code': 'INVALID_TOKEN', 'message': 'Invalid or expired verification token'}}), 400

    if verification.expires_at < datetime.utcnow():
        return jsonify({'success': False, 'error': {'code': 'EXPIRED_TOKEN', 'message': 'Verification token has expired'}}), 400

    user = User.query.filter(User.id == verification.user_id, User.is_deleted == False).first()
    if not user:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'User not found'}}), 404

    user.email_verified = True
    user.is_online = True
    user.last_seen = datetime.utcnow()
    verification.verified = True
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Database error'}}), 500

    return jsonify({'success': True, 'data': {'message': 'Email verified successfully'}})


@spav2_auth_bp.route('/check_username', methods=['GET'])
def check_username():
    username = request.args.get('username', '').strip()
    if not username:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'Username is required'}}), 400
    user_id = session.get('user_id')
    existing = User.query.filter_by(username=username).filter(User.is_deleted == False).first()
    available = existing is None or (user_id and existing.id == user_id)
    return jsonify({'success': True, 'data': {'username': username, 'available': available}})
