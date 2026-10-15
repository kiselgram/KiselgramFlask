from flask import Blueprint, request, jsonify, session, current_app
from datetime import datetime, timezone, timedelta
import secrets
import random
from sqlalchemy.exc import IntegrityError
from app import db
from app.models import User, Message, Chat, LoginOtp, UserSession, EmailVerification, PreloadedAvatar, Referral
from app.utils.helpers import get_current_user
from app.utils.security import rate_limit, sanitize_string, account_lockout, note_account_failure, clear_account_failures
import re

spav2_login_v3_bp = Blueprint('spav2_login_v3', __name__, url_prefix='/api/auth')

KISELGRAM_USER_ID = None


def _new_otp_code():
    """5-digit numeric OTP code (matches the K.otpWidget pill count)."""
    return str(random.randint(10000, 99999))


def _mail_configured():
    """True when SMTP credentials are actually set (not defaults/empty)."""
    srv = current_app.config.get('MAIL_SERVER', '') or ''
    usr = current_app.config.get('MAIL_USERNAME', '') or ''
    return bool(srv) and srv != 'localhost' and bool(usr)


def _send_mail_fast(msg, timeout=8):
    """Send mail with a hard socket cap so one bad SMTP never hangs workers."""
    import socket
    from flask_mail import Mail
    prev = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        Mail(current_app).send(msg)
    finally:
        socket.setdefaulttimeout(prev)


def _ensure_kiselgram_user():
    global KISELGRAM_USER_ID
    if KISELGRAM_USER_ID:
        return KISELGRAM_USER_ID
    user = User.query.filter_by(username='kiselgram', is_deleted=False).first()
    if not user:
        user = User(
            username='kiselgram',
            email='system@kiselgram.local',
            display_name='Kiselgram',
            is_bot=True,
            email_verified=True,
        )
        db.session.add(user)
        db.session.flush()
    if not user.avatar_url:
        user.avatar_url = '/static/favicon.svg'
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    KISELGRAM_USER_ID = user.id
    return user.id


def _send_otp_via_chat(user_id, code):
    kg_id = _ensure_kiselgram_user()
    chat = Chat.query.filter(
        ((Chat.user1_id == kg_id) & (Chat.user2_id == user_id)) |
        ((Chat.user1_id == user_id) & (Chat.user2_id == kg_id))
    ).first()
    if not chat:
        chat = Chat(user1_id=min(kg_id, user_id), user2_id=max(kg_id, user_id), chat_type='personal')
        db.session.add(chat)
        db.session.flush()
    msg = Message(
        sender_id=kg_id,
        receiver_id=user_id,
        chat_id=chat.id,
        content=f"Your login code: <b>{code}</b>\nIt expires in 5 minutes.",
        timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.session.add(msg)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def _make_session(user):
    session_token = secrets.token_urlsafe(32)
    session['user_id'] = user.id
    session['username'] = user.username
    user.is_online = True
    user.last_seen = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.add(UserSession(
        user_id=user.id,
        session_token=session_token,
        device='K Web',
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        last_activity=datetime.now(timezone.utc).replace(tzinfo=None),
        is_active=True,
    ))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return None
    return session_token


def _serialize_user(user):
    is_premium = (user.premium and user.premium.is_premium) or False
    return {
        'user_id': user.id,
        'username': user.username,
        'email': user.email,
        'display_name': user.display_name or user.username,
        'avatar_url': user.avatar_url,
        'bio': getattr(user, 'bio', None),
        'is_premium': is_premium,
        'is_admin': getattr(user, 'is_admin', False),
        'is_online': True,
        'last_seen': datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        'created_at': user.created_at.isoformat() if user.created_at else datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        'status_emoji': user.status_emoji or ('\u2b50' if is_premium else ''),
    }


# ── Step 1: Check email ────────────────────────────────────────

@spav2_login_v3_bp.route('/check-email', methods=['POST'])
def check_email():
    data = request.get_json() or {}
    email = sanitize_string(data.get('email', '').strip().lower(), max_length=128)
    if not email or '@' not in email:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'Valid email required'}}), 400

    user = User.query.filter_by(email=email, is_deleted=False).first()
    exists = user is not None
    return jsonify({'success': True, 'data': {'exists': exists, 'email': email}})


# ── Step 2a: Send OTP (existing user) ──────────────────────────

@spav2_login_v3_bp.route('/send-otp', methods=['POST'])
@rate_limit('send_otp', max_requests=5, window=300)
def send_otp():
    data = request.get_json() or {}
    email = sanitize_string(data.get('email', '').strip().lower(), max_length=128)
    user = User.query.filter_by(email=email, is_deleted=False).first()
    if not user:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'User not found'}}), 404

    code = _new_otp_code()
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5)
    db.session.add(LoginOtp(user_id=user.id, code=code, expires_at=expires_at))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Failed to save OTP'}}), 500

    try:
        _send_otp_via_chat(user.id, code)
        current_app.logger.info(f"OTP for {email}: {code}")
    except Exception as e:
        current_app.logger.error(f"Failed to send OTP via chat: {e}")
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Failed to send code'}}), 500

    return jsonify({'success': True, 'data': {'message': 'Code sent via Kiselgram chat'}})


# ── Step 2a alt: Resend OTP via email (fallback) ───────────────

@spav2_login_v3_bp.route('/send-otp-email', methods=['POST'])
@rate_limit('send_otp_email', max_requests=5, window=300)
def send_otp_email():
    data = request.get_json() or {}
    email = sanitize_string(data.get('email', '').strip().lower(), max_length=128)
    user = User.query.filter_by(email=email, is_deleted=False).first()
    if not user:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'User not found'}}), 404

    code = _new_otp_code()
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5)
    db.session.add(LoginOtp(user_id=user.id, code=code, expires_at=expires_at))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Failed to save OTP'}}), 500

    try:
        from flask_mail import Message as MailMessage
        msg = MailMessage(
            subject='Your Kiselgram login code',
            sender=current_app.config.get('MAIL_DEFAULT_SENDER'),
            recipients=[email],
        )
        msg.body = f"Your login code: {code}\nIt expires in 5 minutes.\n\nIf you didn't request this, ignore this email."
        if _mail_configured():
            _send_mail_fast(msg)
        else:
            raise RuntimeError('SMTP not configured')
        current_app.logger.info(f"OTP for {email}: {code}")
    except Exception as e:
        current_app.logger.error(f"Failed to send OTP via email: {e}")
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Failed to send email'}}), 500

    return jsonify({'success': True, 'data': {'message': 'Code sent to your email'}})


# ── Step 2b: Verify OTP ────────────────────────────────────────

@spav2_login_v3_bp.route('/verify-otp', methods=['POST'])
@rate_limit('verify_otp', max_requests=10, window=60)
@account_lockout(lambda req: ((req.get_json(silent=True) or {}).get('email', '') or '').strip().lower())
def verify_otp():
    data = request.get_json() or {}
    email = sanitize_string(data.get('email', '').strip().lower(), max_length=128)
    code = data.get('code', '').strip()

    user = User.query.filter_by(email=email, is_deleted=False).first()
    if not user:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'User not found'}}), 404

    otp = LoginOtp.query.filter_by(user_id=user.id, code=code, used=False).order_by(LoginOtp.id.desc()).first()
    if not otp:
        note_account_failure(email)
        return jsonify({'success': False, 'error': {'code': 'INVALID_CODE', 'message': 'Invalid code'}}), 400
    if otp.expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
        note_account_failure(email)
        return jsonify({'success': False, 'error': {'code': 'EXPIRED_CODE', 'message': 'Code expired'}}), 400

    otp.used = True
    try:
        db.session.commit()
        clear_account_failures(email)
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Failed to verify code'}}), 500

    return jsonify({'success': True, 'data': {'message': 'Code verified', 'email': email}})


# ── Step 3a: Login with password (after OTP) ───────────────────

@spav2_login_v3_bp.route('/login-password', methods=['POST'])
@rate_limit('login_password', max_requests=5, window=60)
@account_lockout(lambda req: ((req.get_json(silent=True) or {}).get('email', '') or '').strip().lower())
def login_password():
    data = request.get_json() or {}
    email = sanitize_string(data.get('email', '').strip().lower(), max_length=128)
    password = data.get('password', '')
    verified = data.get('otp_verified', False)

    if not verified:
        return jsonify({'success': False, 'error': {'code': 'OTP_REQUIRED', 'message': 'Verify OTP first'}}), 400

    user = User.query.filter_by(email=email, is_deleted=False).first()
    if not user:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'User not found'}}), 404

    if not user.password_hash or not user.check_password(password):
        note_account_failure(email)
        return jsonify({'success': False, 'error': {'code': 'INVALID_CREDENTIALS', 'message': 'Invalid password'}}), 401

    session_token = _make_session(user)
    if not session_token:
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Session creation failed'}}), 500
    clear_account_failures(email)
    return jsonify({'success': True, 'data': {'user': _serialize_user(user), 'session_token': session_token}})


# ── Step 3a alt: Login without password (OTP-only) ────────────

@spav2_login_v3_bp.route('/login-otp-only', methods=['POST'])
@rate_limit('login_otp_only', max_requests=5, window=60)
def login_otp_only():
    data = request.get_json() or {}
    email = sanitize_string(data.get('email', '').strip().lower(), max_length=128)
    verified = data.get('otp_verified', False)

    if not verified:
        return jsonify({'success': False, 'error': {'code': 'OTP_REQUIRED', 'message': 'Verify OTP first'}}), 400

    user = User.query.filter_by(email=email, is_deleted=False).first()
    if not user:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'User not found'}}), 404

    session_token = _make_session(user)
    if not session_token:
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Session creation failed'}}), 500
    return jsonify({'success': True, 'data': {'user': _serialize_user(user), 'session_token': session_token}})


# ── Step 2b alt: Register - send email verification ────────────

@spav2_login_v3_bp.route('/register-send-code', methods=['POST'])
@rate_limit('register_send', max_requests=5, window=300)
def register_send_code():
    data = request.get_json() or {}
    email = sanitize_string(data.get('email', '').strip().lower(), max_length=128)
    if not email or '@' not in email:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'Valid email required'}}), 400
    if User.query.filter_by(email=email, is_deleted=False).first():
        return jsonify({'success': False, 'error': {'code': 'EMAIL_TAKEN', 'message': 'Email already registered'}}), 409

    code = _new_otp_code()
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=10)

    existing = EmailVerification.query.filter_by(email=email, verified=False).first()
    if existing:
        existing.token = code
        existing.expires_at = expires_at
    else:
        db.session.add(EmailVerification(email=email, token=code, expires_at=expires_at))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Failed to send code'}}), 500

    try:
        from flask_mail import Message as MailMessage
        msg = MailMessage(
            subject='Your Kiselgram verification code',
            sender=current_app.config.get('MAIL_DEFAULT_SENDER'),
            recipients=[email],
        )
        msg.body = f"Your verification code: {code}\nThis code expires in 10 minutes.\n\nIf you didn't request this, ignore this email."
        if _mail_configured():
            _send_mail_fast(msg)
        else:
            raise RuntimeError('SMTP not configured')
        current_app.logger.info(f"Registration code for {email}: {code}")
    except Exception as e:
        current_app.logger.error(f"Failed to send registration code via email: {e}")
        current_app.logger.info(f"Registration code for {email}: {code}")
        if current_app.debug:
            # Dev fallback: no SMTP here, hand the code to the caller so the
            # flow can be completed (never enabled in production).
            return jsonify({'success': True, 'data': {'message': 'Code sent to email', 'debug_code': code}})
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Failed to send email'}}), 500

    return jsonify({'success': True, 'data': {'message': 'Code sent to email'}})


@spav2_login_v3_bp.route('/register-verify-code', methods=['POST'])
@rate_limit('register_verify', max_requests=10, window=60)
def register_verify_code():
    data = request.get_json() or {}
    email = sanitize_string(data.get('email', '').strip().lower(), max_length=128)
    code = data.get('code', '').strip()

    ev = EmailVerification.query.filter_by(email=email, token=code, verified=False).order_by(EmailVerification.id.desc()).first()
    if not ev:
        return jsonify({'success': False, 'error': {'code': 'INVALID_CODE', 'message': 'Invalid code'}}), 400
    if ev.expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
        return jsonify({'success': False, 'error': {'code': 'EXPIRED_CODE', 'message': 'Code expired'}}), 400

    ev.verified = True
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Failed to verify code'}}), 500
    return jsonify({'success': True, 'data': {'message': 'Email verified', 'email': email}})


# ── Step 3b: Finish registration ───────────────────────────────

@spav2_login_v3_bp.route('/register-finish', methods=['POST'])
@rate_limit('register_finish', max_requests=5, window=300)
def register_finish():
    data = request.get_json() or {}
    email = sanitize_string(data.get('email', '').strip().lower(), max_length=128)
    username = sanitize_string(data.get('username', ''), max_length=32)
    display_name = sanitize_string(data.get('display_name', ''), max_length=80)
    bio = sanitize_string(data.get('bio', ''), max_length=200) or None
    avatar = data.get('avatar', '')
    email_verified = data.get('email_verified', False)

    if not email_verified:
        return jsonify({'success': False, 'error': {'code': 'VERIFY_REQUIRED', 'message': 'Verify email first'}}), 400
    if not email or '@' not in email:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'Valid email required'}}), 400
    if User.query.filter_by(email=email, is_deleted=False).first():
        return jsonify({'success': False, 'error': {'code': 'EMAIL_TAKEN', 'message': 'Email already registered'}}), 409

    errors = {}
    if len(username) < 3 or not re.match(r'^[a-zA-Z0-9_]+$', username):
        errors['username'] = '3-32 chars, letters, numbers, underscores'
    if User.query.filter_by(username=username, is_deleted=False).first():
        errors['username'] = 'Username taken'
    if errors:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'Validation failed', 'fields': errors}}), 400

    avatar_url = None
    if avatar and re.match(r'^[a-zA-Z0-9_][a-zA-Z0-9_\-\.]*\.(jpg|jpeg|png|gif|webp)$', avatar):
        avatar_url = f"/static/uploads/preloaded-avatars/{avatar}"

    ref_code = data.get('ref', '').strip()

    user = User(
        username=username,
        email=email,
        display_name=display_name or username,
        bio=bio,
        avatar_url=avatar_url,
        email_verified=True,
    )
    db.session.add(user)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'DUPLICATE', 'message': 'Email or username already taken'}}), 409

    if ref_code:
        inviter = User.query.filter_by(username=ref_code, is_deleted=False).first()
        if inviter and inviter.id != user.id:
            existing_ref = Referral.query.filter_by(invited_user_id=user.id).first()
            if not existing_ref:
                try:
                    ref = Referral(inviter_id=inviter.id, invited_user_id=user.id)
                    db.session.add(ref)
                    db.session.flush()
                    count = Referral.query.filter_by(inviter_id=inviter.id).count()
                    if count >= 10 and not inviter.is_premium:
                        inviter.is_premium = True
                        if not inviter.status_emoji:
                            inviter.status_emoji = '\u2b50'
                except IntegrityError:
                    db.session.rollback()
                    current_app.logger.warning(f"Duplicate referral for user {user.id}")

    session_token = _make_session(user)
    if not session_token:
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Session creation failed'}}), 500
    return jsonify({'success': True, 'data': {'user': _serialize_user(user), 'session_token': session_token}})


@spav2_login_v3_bp.route('/preloaded-avatars', methods=['GET'])
def list_preloaded_avatars():
    try:
        import os
        base = os.path.join(current_app.root_path, '..', 'static', 'uploads', 'preloaded-avatars')
        files = os.listdir(base) if os.path.isdir(base) else []
        images = [f for f in files if f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp'))]
        return jsonify({'success': True, 'data': {'avatars': images}})
    except Exception as e:
        current_app.logger.error(f"Failed to list preloaded avatars: {e}")
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Failed to list avatars'}})
