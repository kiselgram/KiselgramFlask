import secrets
import re
import time
from flask import Blueprint, request, jsonify, session
from datetime import datetime
from sqlalchemy import case
from app import db
from app.models import User, Message, Chat, ChatMember, ChatSubscriber, PinnedChat, BlockedUser, Reaction
from app.utils.helpers import get_current_user_id, get_blocked_user_ids, has_active_story
from app.utils.security import sanitize_string

spav2_chat_bp = Blueprint('spav2_chat', __name__, url_prefix='/api')


def _serialize_peer(user):
    is_premium = (user.premium and user.premium.is_premium) or False
    return {
        'user_id': user.id,
        'username': user.username,
        'display_name': user.display_name or user.username,
        'avatar_url': user.avatar_url,
        'is_online': getattr(user, 'is_online', False),
        'last_seen': user.last_seen.isoformat() if user.last_seen else None,
        'status_emoji': user.status_emoji or ('\u2b50' if is_premium else ''),
        'is_premium': is_premium,
        'is_bot': getattr(user, 'is_bot', False),
        'bot_webapp_url': getattr(user, 'bot_webapp_url', None) or None
    }


from app.routes.spav2.messages import _serialize_message


@spav2_chat_bp.route('/chat_list', methods=['GET'])
def chat_list():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 100)
    blocked_ids = get_blocked_user_ids(current_user_id)
    chats = []

    self_msgs = Message.query.filter(
        (Message.sender_id == current_user_id) & (Message.receiver_id == current_user_id)
    ).order_by(Message.timestamp.desc()).first()
    current_user = User.query.filter(User.id == current_user_id, User.is_deleted.is_(False)).first()
    if not current_user:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'User not found'}}), 404
    chats.append({
        'chat_type': 'personal',
        'is_saved': True,
        'peer': {
            'user_id': current_user_id,
            'username': 'saved_messages',
            'display_name': 'Saved Messages',
            'avatar_url': None,
            'is_online': False,
            'last_seen': None,
            'status_emoji': '',
            'is_bot': False,
            'bot_webapp_url': None
        },
        'last_message': {
            'message_id': self_msgs.id,
            'content': self_msgs.content,
            'sender_id': self_msgs.sender_id,
            'timestamp': self_msgs.timestamp.isoformat() if self_msgs.timestamp else None,
            'is_read': True
        } if self_msgs else None,
        'unread_count': 0
    })

    sent = db.session.query(Message.receiver_id).filter_by(sender_id=current_user_id).filter(Message.receiver_id != current_user_id).distinct().limit(500).all()
    recv = db.session.query(Message.sender_id).filter_by(receiver_id=current_user_id).filter(Message.sender_id != current_user_id).distinct().limit(500).all()
    chat_user_ids = {r[0] for r in sent} | {r[0] for r in recv}
    chat_user_ids -= set(blocked_ids)

    users = {}
    last_msg_by_conversation = {}
    unread_counts = {}
    if chat_user_ids:
        user_rows = User.query.filter(User.id.in_(chat_user_ids), User.is_deleted.is_(False)).all()
        users = {u.id: u for u in user_rows}
        chat_user_ids = set(users.keys())

        all_conv_msgs = Message.query.filter(
            ((Message.sender_id == current_user_id) & (Message.receiver_id != current_user_id)) |
            ((Message.receiver_id == current_user_id) & (Message.sender_id != current_user_id))
        ).order_by(Message.timestamp.desc()).all()
        seen_pairs = set()
        for msg in all_conv_msgs:
            pair = (min(msg.sender_id, msg.receiver_id), max(msg.sender_id, msg.receiver_id))
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                other_id = msg.receiver_id if msg.sender_id == current_user_id else msg.sender_id
                last_msg_by_conversation[other_id] = msg

        unread_counts = dict(
            db.session.query(Message.sender_id, db.func.count(Message.id))
            .filter(
                Message.receiver_id == current_user_id,
                Message.sender_id.in_(chat_user_ids),
                Message.is_read.is_(False)
            )
            .group_by(Message.sender_id)
            .all()
        )

    for uid in chat_user_ids:
        user = users.get(uid)
        if not user:
            continue
        last = last_msg_by_conversation.get(uid)
        unread = unread_counts.get(uid, 0)
        chats.append({
            'chat_type': 'personal',
            'peer': _serialize_peer(user),
            'last_message': {
                'message_id': last.id,
                'content': last.content,
                'sender_id': last.sender_id,
                'timestamp': last.timestamp.isoformat() if last.timestamp else None,
                'is_read': last.is_read
            } if last else None,
            'unread_count': unread
        })

    memberships = ChatMember.query.filter_by(user_id=current_user_id).all()
    chat_ids = [m.chat_id for m in memberships]
    chats_map = {c.id: c for c in Chat.query.filter(Chat.id.in_(chat_ids)).all()} if chat_ids else {}

    last_msg_for_group = {}
    unread_for_group = {}
    if chat_ids:
        group_last_ids = db.session.query(
            db.func.max(Message.id).label('msg_id')
        ).filter(
            Message.chat_id.in_(chat_ids)
        ).group_by(Message.chat_id).subquery()

        group_msgs = Message.query.filter(
            Message.id.in_(db.session.query(group_last_ids.c.msg_id))
        ).all()
        last_msg_for_group = {m.chat_id: m for m in group_msgs}

        unread_for_group = dict(
            db.session.query(Message.chat_id, db.func.count(Message.id))
            .filter(
                Message.chat_id.in_(chat_ids),
                Message.is_read.is_(False),
                Message.sender_id != current_user_id
            )
            .group_by(Message.chat_id)
            .all()
        )

    for m in memberships:
        chat = chats_map.get(m.chat_id)
        if not chat:
            continue
        last = last_msg_for_group.get(chat.id)
        unread = unread_for_group.get(chat.id, 0)
        chats.append({
            'chat_type': 'group',
            'group': {
                'group_id': chat.id,
                'name': chat.name,
                'avatar_url': chat.avatar_url
            },
            'last_message': {
                'message_id': last.id,
                'content': last.content,
                'sender_id': last.sender_id,
                'sender_username': last.sender.username if last.sender else None,
                'timestamp': last.timestamp.isoformat() if last.timestamp else None
            } if last else None,
            'unread_count': unread
        })

    subscriptions = ChatSubscriber.query.filter_by(user_id=current_user_id).all()
    chan_ids_list = [s.chat_id for s in subscriptions]
    chans_map = {c.id: c for c in Chat.query.filter(Chat.id.in_(chan_ids_list)).all()} if chan_ids_list else {}

    last_msg_for_channel = {}
    if chan_ids_list:
        chan_last_ids = db.session.query(
            db.func.max(Message.id).label('msg_id')
        ).filter(
            Message.chat_id.in_(chan_ids_list)
        ).group_by(Message.chat_id).subquery()

        chan_msgs = Message.query.filter(
            Message.id.in_(db.session.query(chan_last_ids.c.msg_id))
        ).all()
        last_msg_for_channel = {m.chat_id: m for m in chan_msgs}

    for s in subscriptions:
        chat = chans_map.get(s.chat_id)
        if not chat:
            continue
        last = last_msg_for_channel.get(chat.id)
        chats.append({
            'chat_type': 'channel',
            'channel': {
                'channel_id': chat.id,
                'name': chat.name,
                'avatar_url': chat.avatar_url
            },
            'last_message': {
                'message_id': last.id,
                'content': last.content,
                'timestamp': last.timestamp.isoformat() if last.timestamp else None
            } if last else None,
            'unread_count': 0
        })

    total = len(chats)
    pages = (total + per_page - 1) // per_page if total else 1
    start = (page - 1) * per_page
    page_chats = chats[start:start + per_page]

    return jsonify({'success': True, 'data': {
        'chats': page_chats,
        'pagination': {'page': page, 'per_page': per_page, 'total': total, 'pages': pages}
    }})


@spav2_chat_bp.route('/messages/<int:user_id>', methods=['GET'])
def get_personal_messages(user_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    if BlockedUser.query.filter_by(user_id=user_id, blocked_user_id=current_user_id).first():
        return jsonify({'success': False, 'error': {'code': 'BLOCKED', 'message': 'You are blocked by this user'}}), 403

    after_id = request.args.get('after', 0, type=int)
    limit = min(request.args.get('limit', 50, type=int), 100)

    peer = User.query.filter(User.id == user_id, User.is_deleted.is_(False)).first()
    if not peer:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'User not found'}}), 404

    if user_id == current_user_id:
        messages = Message.query.filter(
            (Message.sender_id == current_user_id) & (Message.receiver_id == current_user_id)
        ).filter(Message.id > after_id).order_by(Message.timestamp.asc()).limit(limit + 1).all()
    else:
        messages = Message.query.filter(
            ((Message.sender_id == current_user_id) & (Message.receiver_id == user_id)) |
            ((Message.sender_id == user_id) & (Message.receiver_id == current_user_id))
        ).filter(Message.id > after_id).order_by(Message.timestamp.asc()).limit(limit + 1).all()

    has_more = len(messages) > limit
    messages = messages[:limit]
    next_cursor = messages[-1].id if messages else None

    return jsonify({'success': True, 'data': {
        'peer': _serialize_peer(peer),
        'messages': [_serialize_message(m, current_user_id) for m in messages],
        'pagination': {
            'after': after_id if after_id else None,
            'limit': limit,
            'has_more': has_more,
            'next_cursor': next_cursor
        }
    }})


@spav2_chat_bp.route('/typing/<chat_type>/<int:chat_id>', methods=['GET'])
def get_typing(chat_type, chat_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    from .messages import _typing_status, _TYPING_TIMEOUT
    import time
    key = f"{chat_type}_{chat_id}"
    now = time.time()
    typists = []
    if key in _typing_status:
        expired = []
        active = {}
        for uid, ts in list(_typing_status[key].items()):
            if now - ts > _TYPING_TIMEOUT:
                expired.append(uid)
            elif uid != current_user_id:
                active[uid] = ts
        for uid in expired:
            del _typing_status[key][uid]
        if not _typing_status[key]:
            del _typing_status[key]

        if active:
            users_map = {
                u.id: u for u in
                User.query.filter(User.id.in_(active.keys()), User.is_deleted.is_(False)).all()
            }
            for uid, ts in active.items():
                user = users_map.get(uid)
                print(f"DEBUG typing: uid={uid} current={current_user_id} user={user} typists={typists}", flush=True)
                if user:
                    typists.append({
                        'user_id': uid,
                        'username': user.username,
                        'started_at': datetime.fromtimestamp(ts).isoformat()
                    })
    return jsonify({'success': True, 'data': {'typing_users': typists}})

@spav2_chat_bp.route('/bot/<int:bot_id>/webapp', methods=['GET'])
def get_bot_webapp(bot_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED'}}), 401
    bot = User.query.filter(User.id == bot_id, User.is_deleted.is_(False)).first()
    if not bot or not bot.is_bot:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND'}}), 404
    return jsonify({'success': True, 'data': {'bot_id': bot_id, 'webapp_url': bot.bot_webapp_url or None}})

@spav2_chat_bp.route('/bot/<int:bot_id>/webapp', methods=['PUT'])
def update_bot_webapp(bot_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED'}}), 401
    bot = User.query.filter(User.id == bot_id, User.is_deleted.is_(False)).first()
    if not bot or not bot.is_bot or bot.bot_owner_id != current_user_id:
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN'}}), 403
    data = request.get_json() or {}
    url = data.get('webapp_url', '').strip()
    if url and not url.startswith('https://'):
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'Only HTTPS URLs allowed'}}), 400
    bot.bot_webapp_url = url or None
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': str(e)}}), 500
    return jsonify({'success': True, 'data': {'bot_id': bot_id, 'webapp_url': bot.bot_webapp_url}})

@spav2_chat_bp.route('/bots', methods=['GET', 'POST'])
def handle_bots():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED'}}), 401

    if request.method == 'GET':
        bots = User.query.filter_by(bot_owner_id=current_user_id, is_bot=True, is_deleted=False).all()
        return jsonify({'success': True, 'data': {'bots': [{
            'bot_id': b.id,
            'username': b.username,
            'display_name': b.display_name or b.username,
            'avatar_url': b.avatar_url,
            'bot_webapp_url': b.bot_webapp_url or None
        } for b in bots]}})

    # POST — create a new bot
    data = request.get_json() or {}
    username = sanitize_string(data.get('username', ''), max_length=32).lower()
    display_name = sanitize_string(data.get('display_name', ''), max_length=64) or username

    errors = {}
    if len(username) < 3 or not re.match(r'^[a-zA-Z0-9_]+$', username):
        errors['username'] = 'Username must be 3-32 characters (letters, numbers, underscores)'
    if User.query.filter_by(username=username).first():
        errors['username'] = 'Username already taken'
    if errors:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'Validation failed', 'fields': errors}}), 400

    bot_token = secrets.token_urlsafe(48)
    bot = User(
        username=username,
        display_name=display_name,
        email=None,
        is_bot=True,
        bot_owner_id=current_user_id,
        bot_token=bot_token,
        is_online=False,
        last_seen=datetime.utcnow()
    )
    bot.set_password(secrets.token_urlsafe(24))
    db.session.add(bot)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': str(e)}}), 500

    return jsonify({'success': True, 'data': {
        'bot_id': bot.id,
        'username': bot.username,
        'display_name': bot.display_name,
        'bot_token': bot_token,
        'message': 'Bot created. Save the token — it is shown only once.'
    }}), 201
