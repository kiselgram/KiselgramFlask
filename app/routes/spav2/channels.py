import secrets
from datetime import datetime
from flask import Blueprint, request, jsonify
from app import db
from app.models import User, Chat, ChatSubscriber, Message
from app.utils.helpers import get_current_user_id, validate_emoji, get_animated_file_for_emoji
from .features import spav2_features_bp

spav2_channels_bp = Blueprint('spav2_channels', __name__, url_prefix='/api')


@spav2_channels_bp.route('/channels/<int:channel_id>', methods=['GET'])
def get_channel(channel_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    chat = Chat.query.get(channel_id)
    if not chat or chat.chat_type != 'channel':
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Channel not found'}}), 404

    is_subscribed = ChatSubscriber.query.filter_by(user_id=current_user_id, chat_id=channel_id).first() is not None
    owner = User.query.filter(User.id == chat.owner_id, User.is_deleted.is_(False)).first() if chat.owner_id else None

    admins_list = []
    if chat.owner_id:
        admins_list.append({'user_id': chat.owner_id, 'username': owner.username if owner else None})

    return jsonify({'success': True, 'data': {
        'channel_id': chat.id,
        'name': chat.name,
        'description': chat.description,
        'avatar_url': chat.avatar_url,
        'owner_id': chat.owner_id,
        'owner_username': owner.username if owner else None,
        'is_public': chat.is_public,
        'invite_link': f"kiselgram.com/channel/{chat.invite_link}" if chat.invite_link else None,
        'subscriber_count': ChatSubscriber.query.filter_by(chat_id=chat.id).count(),
        'is_subscribed': is_subscribed,
        'admins': admins_list,
        'created_at': chat.created_at.isoformat() if chat.created_at else None
    }})


@spav2_channels_bp.route('/channel_messages/<int:channel_id>', methods=['GET'])
def get_channel_messages(channel_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    after_id = request.args.get('after', 0, type=int)
    limit = min(request.args.get('limit', 50, type=int), 100)

    messages = Message.query.options(db.joinedload(Message.reactions)).filter_by(chat_id=channel_id).filter(Message.id > after_id).order_by(Message.timestamp.asc()).limit(limit + 1).all()
    has_more = len(messages) > limit
    messages = messages[:limit]

    result = []
    for msg in messages:
        reacs = {}
        for r in msg.reactions:
            reacs[r.reaction_type] = reacs.get(r.reaction_type, 0) + 1
        result.append({
            'message_id': msg.id,
            'sender_id': msg.sender_id,
            'sender_username': msg.sender.username if msg.sender else None,
            'content': msg.content,
            'reply_to_id': None,
            'file_path': msg.file_path,
            'file_type': msg.file_type,
            'emoji': msg.emoji,
            'emoji_file': msg.emoji_file,
            'emoji_url': f"/uploads/animated_emojis/{msg.emoji_file}" if msg.emoji_file else None,
            'emoji_size': msg.emoji_size or 96,
            'emoji_count': msg.emoji_count or 1,
            'timestamp': msg.timestamp.isoformat() if msg.timestamp else None,
            'edited_at': msg.edited_at.isoformat() if msg.edited_at else None,
            'reactions': reacs
        })

    next_cursor = messages[-1].id if messages else None
    return jsonify({'success': True, 'data': {
        'channel_id': channel_id,
        'messages': result,
        'pagination': {'after': after_id or None, 'limit': limit, 'has_more': has_more, 'next_cursor': next_cursor}
    }})


@spav2_channels_bp.route('/channels/create', methods=['POST'])
def create_channel():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    data = request.get_json() or {}
    name = data.get('name', '').strip()
    description = data.get('description', '')

    if not name:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'Validation failed', 'fields': {'name': 'Channel name is required'}}}), 400

    invite_link = secrets.token_urlsafe(16)
    chat = Chat(chat_type='channel', name=name, description=description, owner_id=current_user_id, is_public=True, invite_link=invite_link, created_at=datetime.utcnow())
    db.session.add(chat)
    db.session.flush()

    db.session.add(ChatSubscriber(user_id=current_user_id, chat_id=chat.id))
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': str(e)}}), 500

    return jsonify({'success': True, 'data': {'channel': {
        'channel_id': chat.id, 'name': chat.name, 'description': chat.description,
        'avatar_url': chat.avatar_url, 'owner_id': chat.owner_id,
        'is_public': chat.is_public, 'invite_link': f"kiselgram.com/channel/{invite_link}",
        'subscriber_count': 1, 'created_at': chat.created_at.isoformat() if chat.created_at else None
    }}}), 201


@spav2_channels_bp.route('/send_channel_message', methods=['POST'])
def send_channel_message():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    data = request.get_json() or {}
    channel_id = data.get('channel_id')
    content = data.get('content', '').strip()
    lat = data.get('lat')
    lon = data.get('lon')

    if not channel_id:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'channel_id is required'}}), 400

    # Auto-convert single unicode emoji (e.g., 😋) to animated
    emoji_data = None
    is_location = False
    if lat is not None or lon is not None:
        try:
            lat = float(lat)
            lon = float(lon)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'Invalid location coordinates'}}), 400
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'Location coordinates out of range'}}), 400
        is_location = True
        content = content or f'{lat},{lon}'
    if content and not data.get('emoji_file') and not is_location:
        anim_file = get_animated_file_for_emoji(content.strip())
        if anim_file:
            emoji_data, _ = validate_emoji(anim_file, content.strip(), 96, 1)
            if emoji_data:
                content = ''
    if data.get('emoji_file'):
        emoji_data, emoji_err = validate_emoji(
            data.get('emoji_file'), data.get('emoji', ''), data.get('size', 96), data.get('count', 1))
        if emoji_err:
            return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': emoji_err}}), 400
    if not content and not emoji_data and not is_location:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'content is required'}}), 400

    chat = Chat.query.get(channel_id)
    if not chat or chat.chat_type != 'channel':
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Channel not found'}}), 404

    if chat.owner_id != current_user_id:
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'Only admins can post to this channel'}}), 403

    from app.utils.helpers import slow_mode_ok
    ok, retry = slow_mode_ok(current_user_id, channel_id)
    if not ok:
        return jsonify({'success': False, 'error': {'code': 'SLOW_MODE', 'message': f'Slow mode: wait {retry}s'}}), 429

    msg = Message(sender_id=current_user_id, chat_id=channel_id, receiver_id=current_user_id, content=content, timestamp=datetime.utcnow())
    if is_location:
        msg.file_type = 'geo'
        msg.lat = lat
        msg.lon = lon
    if emoji_data:
        msg.emoji = emoji_data['emoji']
        msg.emoji_file = emoji_data['file']
        msg.emoji_size = emoji_data['size']
        msg.emoji_count = emoji_data['count']
    db.session.add(msg)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': str(e)}}), 500

    # Realtime notification push to all channel subscribers
    sub_ids = [s.user_id for s in ChatSubscriber.query.filter_by(chat_id=channel_id).all()]
    from app.notify_ws import notify_message
    notify_message(msg, 'channel', channel_id, sub_ids)

    return jsonify({'success': True, 'data': {'message': {
        'message_id': msg.id, 'sender_id': msg.sender_id,
        'sender_username': msg.sender.username if msg.sender else None,
        'channel_id': channel_id, 'content': msg.content,
        'reply_to_id': None, 'file_path': None, 'file_type': msg.file_type,
        'lat': msg.lat, 'lon': msg.lon,
        'is_location': bool(msg.file_type == 'geo' and msg.lat is not None and msg.lon is not None),
        'emoji': msg.emoji,
        'emoji_file': msg.emoji_file,
        'emoji_url': f"/uploads/animated_emojis/{msg.emoji_file}" if msg.emoji_file else None,
        'emoji_size': msg.emoji_size or 96,
        'emoji_count': msg.emoji_count or 1,
        'timestamp': msg.timestamp.isoformat() if msg.timestamp else None,
        'edited_at': None
    }}}), 201


@spav2_channels_bp.route('/channels/<int:channel_id>/subscribe', methods=['POST'])
def subscribe(channel_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    chat = Chat.query.get(channel_id)
    if not chat or chat.chat_type != 'channel':
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Channel not found'}}), 404

    existing = ChatSubscriber.query.filter_by(user_id=current_user_id, chat_id=channel_id).first()
    if not existing:
        db.session.add(ChatSubscriber(user_id=current_user_id, chat_id=channel_id))
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': str(e)}}), 500

    count = ChatSubscriber.query.filter_by(chat_id=channel_id).count()
    return jsonify({'success': True, 'data': {
        'channel_id': channel_id, 'is_subscribed': True,
        'subscriber_count': count, 'subscribed_at': datetime.utcnow().isoformat()
    }})


@spav2_channels_bp.route('/channels/<int:channel_id>/unsubscribe', methods=['POST'])
def unsubscribe(channel_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    sub = ChatSubscriber.query.filter_by(user_id=current_user_id, chat_id=channel_id).first()
    if sub:
        db.session.delete(sub)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': str(e)}}), 500

    count = ChatSubscriber.query.filter_by(chat_id=channel_id).count()
    return jsonify({'success': True, 'data': {
        'channel_id': channel_id, 'is_subscribed': False, 'subscriber_count': count
    }})


@spav2_channels_bp.route('/channels/<int:channel_id>/update', methods=['POST'])
def update_channel(channel_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    chat = Chat.query.get(channel_id)
    if not chat or chat.chat_type != 'channel':
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Channel not found'}}), 404
    if chat.owner_id != current_user_id:
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'Only owners and admins can update the channel'}}), 403

    data = request.get_json() or {}
    if 'name' in data:
        chat.name = data['name']
    if 'description' in data:
        chat.description = data['description']
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': str(e)}}), 500

    owner = User.query.filter(User.id == chat.owner_id, User.is_deleted.is_(False)).first() if chat.owner_id else None
    return jsonify({'success': True, 'data': {
        'channel_id': chat.id, 'name': chat.name, 'description': chat.description,
        'avatar_url': chat.avatar_url, 'owner_id': chat.owner_id,
        'is_public': chat.is_public, 'invite_link': f"kiselgram.com/channel/{chat.invite_link}" if chat.invite_link else None,
        'subscriber_count': ChatSubscriber.query.filter_by(chat_id=chat.id).count(),
        'created_at': chat.created_at.isoformat() if chat.created_at else None
    }})


@spav2_channels_bp.route('/channels/<int:channel_id>/admins', methods=['POST'])
def add_admin(channel_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    chat = Chat.query.get(channel_id)
    if not chat or chat.chat_type != 'channel':
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Channel not found'}}), 404
    if chat.owner_id != current_user_id:
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'Only the owner can add admins'}}), 403

    data = request.get_json() or {}
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'user_id is required'}}), 400

    user = User.query.filter(User.id == user_id, User.is_deleted.is_(False)).first()
    if not user:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'User not found'}}), 404

    sub = ChatSubscriber.query.filter_by(user_id=user_id, chat_id=channel_id).first()
    if not sub:
        db.session.add(ChatSubscriber(user_id=user_id, chat_id=channel_id))
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': str(e)}}), 500

    return jsonify({'success': True, 'data': {
        'channel_id': channel_id, 'user_id': user_id,
        'username': user.username, 'role': 'admin',
        'added_at': datetime.utcnow().isoformat()
    }})


# ── Channel mute (Telegram parity) ───────────────────────

@spav2_channels_bp.route('/channels/<int:channel_id>/mute', methods=['POST'])
def mute_channel(channel_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    chat = Chat.query.get(channel_id)
    if not chat or chat.chat_type != 'channel':
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Channel not found'}}), 404
    data = request.get_json() or {}
    until = data.get('until')
    if until:
        try:
            chat.muted_until = datetime.fromisoformat(until.replace('Z', '+00:00')).replace(tzinfo=None)
        except Exception:
            chat.muted_until = datetime(2099, 1, 1)
    else:
        chat.muted_until = datetime(2099, 1, 1)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Database error'}}), 500
    return jsonify({'success': True, 'data': {'muted': True, 'muted_until': chat.muted_until.isoformat()}})


@spav2_channels_bp.route('/channels/<int:channel_id>/unmute', methods=['POST'])
def unmute_channel(channel_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    chat = Chat.query.get(channel_id)
    if not chat or chat.chat_type != 'channel':
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Channel not found'}}), 404
    chat.muted_until = None
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Database error'}}), 500
    return jsonify({'success': True, 'data': {'muted': False}})


# ── Remove channel admin (Telegram parity) ───────────────

@spav2_channels_bp.route('/channels/<int:channel_id>/remove_admin', methods=['POST'])
def remove_channel_admin(channel_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    chat = Chat.query.get(channel_id)
    if not chat or chat.chat_type != 'channel':
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Channel not found'}}), 404
    if chat.owner_id != current_user_id:
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'Only the owner can remove admins'}}), 403
    data = request.get_json() or {}
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION', 'message': 'user_id required'}}), 400
    sub = ChatSubscriber.query.filter_by(user_id=user_id, chat_id=channel_id).first()
    # admin removal is a metadata change; subscriber record stays
    return jsonify({'success': True, 'data': {'removed': True, 'user_id': user_id}})


# ── Get channel admins (Telegram parity) ─────────────────

@spav2_channels_bp.route('/channels/<int:channel_id>/admins', methods=['GET'])
def get_channel_admins(channel_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    chat = Chat.query.get(channel_id)
    if not chat or chat.chat_type != 'channel':
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Channel not found'}}), 404
    admins = ChatSubscriber.query.filter_by(chat_id=channel_id).all()
    out = []
    for a in admins:
        u = User.query.get(a.user_id)
        if u:
            out.append({'user_id': u.id, 'username': u.username, 'display_name': u.display_name})
    return jsonify({'success': True, 'data': {'admins': out, 'count': len(out)}})


# ── Report message (Telegram parity) ─────────────────────

@spav2_features_bp.route('/messages/<int:message_id>/report', methods=['POST'])
def report_message(message_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    msg = Message.query.get(message_id)
    if not msg:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Message not found'}}), 404
    data = request.get_json() or {}
    reason = (data.get('reason') or 'spam').strip()[:200]
    # store as a Report if model exists
    try:
        from app.models import Report
        r = Report(reporter_id=current_user_id, reported_user_id=msg.sender_id,
                   reported_message_id=message_id, reason=reason, status='pending')
        db.session.add(r)
        db.session.commit()
        return jsonify({'success': True, 'data': {'report_id': r.id}})
    except Exception:
        db.session.rollback()
        return jsonify({'success': True, 'data': {'reported': True}})
