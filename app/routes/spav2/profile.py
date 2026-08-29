import os
from datetime import datetime
from flask import Blueprint, request, jsonify, session
from app import db
from app.models import User
from app.utils.helpers import get_current_user
from app.utils.security import sanitize_string, rate_limit

spav2_profile_bp = Blueprint('spav2_profile', __name__, url_prefix='/api')


@spav2_profile_bp.route('/profile', methods=['GET'])
def get_profile():
    current_user = get_current_user()
    if not current_user:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    is_premium = (current_user.premium and current_user.premium.is_premium) or False

    if is_premium and not current_user.status_emoji:
        current_user.status_emoji = '\u2b50'
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

    return jsonify({'success': True, 'data': {
        'user_id': current_user.id,
        'username': current_user.username,
        'email': current_user.email,
        'display_name': current_user.display_name or current_user.username,
        'avatar_url': current_user.avatar_url,
        'bio': getattr(current_user, 'bio', None),
        'is_premium': is_premium,
        'is_admin': getattr(current_user, 'is_admin', False),
        'is_online': getattr(current_user, 'is_online', False),
        'last_seen': current_user.last_seen.isoformat() if current_user.last_seen else None,
        'created_at': current_user.created_at.isoformat() if current_user.created_at else datetime.utcnow().isoformat(),
        'status_emoji': current_user.status_emoji or ('\u2b50' if is_premium else '')
    }})


@spav2_profile_bp.route('/users/<int:user_id>', methods=['GET'])
def get_user(user_id):
    current_user = get_current_user()
    if not current_user:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    user = User.query.get(user_id)
    if not user:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'User not found'}}), 404

    is_premium = (user.premium and user.premium.is_premium) or False

    return jsonify({'success': True, 'data': {
        'user_id': user.id,
        'username': user.username,
        'display_name': user.display_name or user.username,
        'avatar_url': user.avatar_url,
        'bio': getattr(user, 'bio', None),
        'is_premium': is_premium,
        'is_bot': getattr(user, 'is_bot', False),
        'is_online': getattr(user, 'is_online', False),
        'last_seen': user.last_seen.isoformat() if user.last_seen else None,
        'status_emoji': user.status_emoji or ('\u2b50' if is_premium else '')
    }})


@spav2_profile_bp.route('/users/<int:user_id>/music', methods=['GET'])
def get_user_music(user_id):
    current_user = get_current_user()
    if not current_user:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    user = User.query.get(user_id)
    if not user:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'User not found'}}), 404

    return jsonify({'success': True, 'data': []})


@spav2_profile_bp.route('/users/<int:user_id>/files', methods=['GET'])
def get_user_files(user_id):
    current_user = get_current_user()
    if not current_user:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    user = User.query.get(user_id)
    if not user:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'User not found'}}), 404

    return jsonify({'success': True, 'data': []})


@spav2_profile_bp.route('/profile', methods=['PUT'])
def update_profile():
    current_user = get_current_user()
    if not current_user:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    data = request.get_json() or {}
    if 'display_name' in data:
        current_user.display_name = sanitize_string(data['display_name'], max_length=50)
    if 'bio' in data:
        current_user.bio = sanitize_string(data['bio'], max_length=200)
    if 'status_emoji' in data:
        emoji = sanitize_string(data['status_emoji'], max_length=10)
        is_premium = (current_user.premium and current_user.premium.is_premium) or False
        if not is_premium:
            return jsonify({'success': False, 'error': {'code': 'PREMIUM_REQUIRED', 'message': 'Status emoji is a premium feature'}}), 400
        if not emoji:
            return jsonify({'success': False, 'error': {'code': 'PREMIUM_STATUS_LOCKED', 'message': 'Premium users cannot remove status emoji'}}), 400
        current_user.status_emoji = emoji
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Database error'}}), 500
    return jsonify({'success': True, 'data': {'message': 'Profile updated'}})


@spav2_profile_bp.route('/profile/settings', methods=['GET'])
def get_settings():
    current_user = get_current_user()
    if not current_user:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    settings = getattr(current_user, 'settings', None)
    return jsonify({'success': True, 'data': {
        'theme': getattr(settings, 'theme', 'dark') if settings else 'dark',
        'font_size': getattr(settings, 'font_size', 'medium') if settings else 'medium',
        'colors': {
            'primary': getattr(settings, 'primary_color', '#4A90D9') if settings else '#4A90D9',
            'accent': getattr(settings, 'accent_color', '#F5A623') if settings else '#F5A623',
            'background': getattr(settings, 'background_color', '#1E1E2E') if settings else '#1E1E2E',
            'chat_bubble_self': getattr(settings, 'bubble_self_color', '#4A90D9') if settings else '#4A90D9',
            'chat_bubble_other': getattr(settings, 'bubble_other_color', '#2E2E3E') if settings else '#2E2E3E'
        }
    }})


@spav2_profile_bp.route('/profile/privacy', methods=['GET'])
def get_privacy():
    current_user = get_current_user()
    if not current_user:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    privacy = getattr(current_user, 'privacy_settings', None)
    return jsonify({'success': True, 'data': {
        'last_seen': getattr(privacy, 'last_seen', 'contacts_only') if privacy else 'contacts_only',
        'profile_photo': getattr(privacy, 'profile_photo', 'everyone') if privacy else 'everyone',
        'calls': getattr(privacy, 'calls', 'contacts_only') if privacy else 'contacts_only',
        'messages': getattr(privacy, 'messages', 'everyone') if privacy else 'everyone'
    }})


@spav2_profile_bp.route('/profile/avatar', methods=['POST'])
@rate_limit('v2_avatar', max_requests=5, window=120)
def upload_avatar():
    current_user = get_current_user()
    if not current_user:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    if 'avatar' not in request.files:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'Avatar must be a JPEG or PNG under 5MB'}}), 400

    file = request.files['avatar']
    if file.filename == '':
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'No file selected'}}), 400

    ext = (file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'jpg')
    if ext not in {'jpg', 'jpeg', 'png', 'webp'}:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'Invalid file type'}}), 400
    filename = f"avatar_{current_user.id}_{os.urandom(4).hex()}.{ext}"
    upload_dir = os.path.join('uploads', 'avatars')
    os.makedirs(upload_dir, exist_ok=True)
    file.save(os.path.join(upload_dir, filename))

    current_user.avatar_url = f"/uploads/avatars/{filename}"
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Database error'}}), 500

    return jsonify({'success': True, 'data': {
        'user_id': current_user.id,
        'avatar_url': current_user.avatar_url,
        'updated_at': datetime.utcnow().isoformat()
    }})
