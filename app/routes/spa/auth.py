# app/routes/auth.py
from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify, current_app, flash
from flask_mail import Mail
from flask_mail import Message as MailMessage
import requests
from app import db, oauth
from app.models import User, Message, Chat, ChatMember, ChatSubscriber, BlockedUser, UserSession, Report, EmailVerification, PreloadedAvatar
from app.utils.helpers import hash_password, get_current_user, get_current_user_id
import re
from datetime import datetime, timedelta
import secrets
from flask import make_response

spa_auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

mail = Mail()

# ========== LOGIN — redirect to K SPA ==========
@spa_auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return redirect('/k#login')

    username = (request.form.get('username') or '').strip()
    password = request.form.get('password', '')
    if not username or not password:
        return "Username and password required", 400

    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        return "Invalid username or password", 401
    if not getattr(user, 'email_verified', True):
        return "Please verify your email first", 400

    session['user_id'] = user.id
    session['username'] = user.username
    user.is_online = True
    user.last_seen = datetime.utcnow()
    db.session.commit()
    return redirect('/chat_list')


# ========== REGISTER — redirect to K SPA ==========
@spa_auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return redirect('/k#register')

    username = (request.form.get('username') or '').strip()
    email = (request.form.get('email') or '').strip()
    password = request.form.get('password', '')
    confirm = request.form.get('confirm_password', '')

    if not username or not email or not password:
        return "Username, email and password are required", 400
    if len(username) < 3:
        return "Username must be at least 3 characters", 400
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        return "Username can only contain letters, numbers, and underscores", 400
    if len(password) < 6:
        return "Password must be at least 6 characters", 400
    if password != confirm:
        return "Passwords do not match", 400
    if User.query.filter_by(username=username).first():
        return "Username already taken", 400
    if User.query.filter_by(email=email).first():
        return "Email already registered", 400

    user = User(username=username, email=email, display_name=username)
    user.set_password(password)
    user.email_verified = False
    db.session.add(user)
    db.session.flush()

    verify_token = secrets.token_urlsafe(32)
    expires = datetime.utcnow() + timedelta(hours=24)
    ver = EmailVerification(user_id=user.id, token=verify_token, expires_at=expires)
    db.session.add(ver)
    db.session.commit()

    return redirect('/auth/check_email')


@spa_auth_bp.route('/check-email')
def check_email():
    user_id = session.get('pending_user_id')
    return render_template('auth/check_email.html', user_id=user_id)

@spa_auth_bp.route('/api/resend_verification', methods=['POST'])
def resend_verification():
    """Resend verification email to the pending user."""
    user_id = session.get('pending_user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'No pending registration'}), 400
    user = User.query.get(user_id)
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    if user.email_verified:
        return jsonify({'success': False, 'error': 'Email already verified'}), 400
    try:
        code = str(random.randint(100000, 999999))
        expires = datetime.utcnow() + timedelta(hours=24)
        verification = EmailVerification(user_id=user.id, token=code, expires_at=expires)
        db.session.add(verification)
        db.session.commit()
        msg = MailMessage(subject='Verify your email – Kiselgram',
                      sender=current_app.config['MAIL_DEFAULT_SENDER'],
                      recipients=[user.email])
        msg.body = f'Welcome to Kiselgram!\n\nYour verification code: {code}\n\nThis code expires in 24 hours.\n\nIf you didn\'t request this, ignore this email.'
        mail.send(msg)
        return jsonify({'success': True})
    except Exception as e:
        current_app.logger.error(f"Resend verification failed: {e}")
        return jsonify({'success': False, 'error': 'Failed to send email'}), 500


@spa_auth_bp.route('/verify/<token>')
def verify_email(token):
    verification = EmailVerification.query.filter_by(token=token, verified=False).first()
    if not verification or verification.expires_at < datetime.utcnow():
        flash('Invalid or expired verification link.', 'error')
        return redirect('/k#login')

    verification.verified = True
    user = User.query.get(verification.user_id)
    user.email_verified = True
    db.session.commit()

    flash('Email verified! You can now log in.', 'success')
    return redirect('/k#login')


@spa_auth_bp.route('/complete-registration', methods=['GET', 'POST'])
def complete_registration():
    if request.method == 'GET':
        if not session.get('user_id'):
            return redirect('/auth/login')
        return redirect('/k#register')

    user_id = session.get('user_id')
    if not user_id:
        return redirect('/auth/login')

    user = User.query.get(user_id)
    if not user:
        return redirect('/auth/login')

    username = (request.form.get('username') or '').strip()
    display_name = (request.form.get('display_name') or '').strip()
    avatar = (request.form.get('avatar') or '').strip()

    if len(username) < 3:
        return "Username must be at least 3 characters", 400

    user.username = username
    if display_name:
        user.display_name = display_name
    if avatar:
        user.avatar_url = f"/uploads/avatars/{avatar}"
    db.session.commit()
    return redirect('/chat_list')


# ========== GOOGLE OAUTH ==========
@spa_auth_bp.route('/google')
def google_login():
    redirect_uri = url_for('auth.google_authorize', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@spa_auth_bp.route('/google/callback')
def google_authorize():
    try:
        token = oauth.google.authorize_access_token()
    except Exception as e:
        current_app.logger.error(f"OAuth token error: {e}")
        flash("Authorization with Google failed.", "error")
        return redirect(url_for('auth.login'))

    user_info = token.get('userinfo')
    if not user_info:
        resp = requests.get(
            'https://www.googleapis.com/oauth2/v3/userinfo',
            headers={'Authorization': f'Bearer {token["access_token"]}'}
        )
        user_info = resp.json()

    if not user_info:
        flash("Failed to fetch user information from Google.", "error")
        return redirect(url_for('auth.login'))

    google_id = user_info.get('sub')
    email = user_info.get('email')
    name = user_info.get('name')
    picture = user_info.get('picture')

    # Find or create user
    user = User.query.filter_by(google_id=google_id).first()
    if not user:
        # Try to find by email
        if email:
            user = User.query.filter_by(email=email).first()

        if not user:
            # Generate a unique username from email
            base_username = email.split('@')[0] if email else 'user'
            username = base_username
            counter = 1
            while User.query.filter_by(username=username).first():
                username = f"{base_username}{counter}"
                counter += 1

            user = User(
                username=username,
                display_name=name,
                google_id=google_id,
                avatar_url=picture,
                email=email,
                email_verified=True  # Google accounts are pre-verified
            )
            db.session.add(user)
        else:
            # Link existing account to Google
            user.google_id = google_id
            if not user.avatar_url:
                user.avatar_url = picture
            if not user.display_name:
                user.display_name = name
            if not user.email_verified and email == user.email:
                user.email_verified = True
    else:
        # Update info on each login
        user.display_name = name
        user.avatar_url = picture
        if not user.email_verified:
            user.email_verified = True

    db.session.commit()

    session['username'] = user.username
    session['user_id'] = user.id
    session['display_name'] = user.display_name or user.username
    user.is_online = True
    user.last_seen = datetime.utcnow()
    db.session.commit()

    flash(f"Welcome, {user.display_name or user.username}!", "success")

    # If username is the auto-generated one, ask to complete registration
    if user.username.startswith('user_') or not user.display_name:
        return redirect(url_for('auth.complete_registration'))
    return redirect('/app')


# ========== LOGOUT ==========
@spa_auth_bp.route('/logout')
def logout():
    user_id = session.get('user_id')
    if user_id:
        user = User.query.get(user_id)
        if user:
            user.is_online = False
            user.last_seen = datetime.utcnow()
            db.session.commit()
    session.clear()
    return redirect('/k')


# ========== API ROUTES (unchanged) ==========
@spa_auth_bp.route('/api/login', methods=['GET', 'POST'])
def api_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if not username or not password:
            return jsonify({'error': 'Username and password required'}), 400

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['username'] = username
            session['user_id'] = user.id
            user.is_online = True
            user.last_seen = datetime.utcnow()
            db.session.commit()
            return jsonify({'success': True, 'redirect': '/app'})
        else:
            return jsonify({'error': 'Invalid username or password'}), 401
    return jsonify({'error': 'Method not allowed'}), 405


@spa_auth_bp.route('/api/check_username', methods=['POST'])
def api_check_username():
    if not get_current_user():
        return jsonify({'error': 'Not authenticated'}), 401
    data = request.get_json()
    username = data.get('username', '').strip()
    if len(username) < 3:
        return jsonify({'available': False, 'message': 'Min 3 characters'})
    existing = User.query.filter_by(username=username).first()
    current_user_id = get_current_user_id()
    if existing and existing.id != current_user_id:
        return jsonify({'available': False, 'message': 'Username taken'})
    return jsonify({'available': True, 'message': 'Available'})

@spa_auth_bp.route('/api/get_user_id')
def get_user_id():
    user_id = session.get('user_id')
    if not user_id:
        # Return 401 – Nginx will treat this as auth failure
        return '', 401

    # Return empty body with user ID in a custom header
    response = make_response('', 204)
    response.headers['X-User-Id'] = str(user_id)
    return response