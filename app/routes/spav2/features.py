from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from app import db
from app.models import User, Message, Poll, PollVote, Pin, Forward, Chat, ChatMember, ChatSubscriber, InviteLink, File, Archive, SavedMessage, PinnedChat
from app.utils.helpers import get_current_user_id, get_current_user, message_to_dict

spav2_features_bp = Blueprint('spav2_features', __name__, url_prefix='/api')


def _chat_access(user_id, chat_id):
    """Sputnik-style participation check: is user allowed in this chat?"""
    from app.models import ChannelAdmin
    chat = Chat.query.get(chat_id)
    if not chat or not user_id:
        return None
    if chat.chat_type == 'channel':
        if chat.owner_id == user_id:
            return chat
        if ChatSubscriber.query.filter_by(chat_id=chat.id, user_id=user_id).first():
            return chat
        if ChannelAdmin.query.filter_by(chat_id=chat.id, user_id=user_id).first():
            return chat
        return None
    if ChatMember.query.filter_by(chat_id=chat.id, user_id=user_id).first():
        return chat
    return None


# ── Polls ───────────────────────────────────────────────────

@spav2_features_bp.route('/polls/create', methods=['POST'])
def create_poll():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    data = request.get_json() or {}
    question = data.get('question', '').strip()
    options = data.get('options', [])
    is_multiple = data.get('is_multiple', False)
    is_anonymous = data.get('is_anonymous', True)
    chat_type = data.get('chat_type')
    chat_id = data.get('chat_id')

    if not question or len(question) > 255:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION', 'message': 'Question required (max 255 chars)'}}), 400
    if len(options) < 2 or len(options) > 10:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION', 'message': '2-10 options required'}}), 400
    for o in options:
        if not o.strip() or len(o) > 100:
            return jsonify({'success': False, 'error': {'code': 'VALIDATION', 'message': 'Invalid option'}}), 400

    poll = Poll(
        question=question,
        options=options,
        is_multiple=is_multiple,
        is_anonymous=is_anonymous,
        creator_id=current_user_id,
        chat_type=chat_type,
        chat_id=chat_id,
        closed=False
    )
    db.session.add(poll)
    db.session.flush()

    msg = Message(
        sender_id=current_user_id,
        content='',
        poll_id=poll.id,
        poll_question=question,
        chat_id=chat_id
    )
    db.session.add(msg)
    db.session.commit()

    return jsonify({'success': True, 'data': {'poll_id': poll.id, 'message_id': msg.id}})


@spav2_features_bp.route('/polls/vote', methods=['POST'])
def vote_poll():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    data = request.get_json() or {}
    poll_id = data.get('poll_id')
    option_idx = data.get('option_index')

    poll = Poll.query.get(poll_id)
    if not poll:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Poll not found'}}), 404
    if poll.closed:
        return jsonify({'success': False, 'error': {'code': 'CLOSED', 'message': 'Poll is closed'}}), 400

    existing = PollVote.query.filter_by(poll_id=poll_id, user_id=current_user_id).first()
    if existing:
        if not poll.is_multiple:
            return jsonify({'success': False, 'error': {'code': 'ALREADY_VOTED', 'message': 'Already voted'}}), 400
        existing.option_index = option_idx
    else:
        vote = PollVote(poll_id=poll_id, user_id=current_user_id, option_index=option_idx, voted_at=datetime.now(timezone.utc))
        db.session.add(vote)
    db.session.commit()

    return jsonify({'success': True, 'data': {'poll_id': poll_id}})


# ── Forward Messages ────────────────────────────────────────

@spav2_features_bp.route('/messages/forward', methods=['POST'])
def forward_message():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    data = request.get_json() or {}
    msg_id = data.get('message_id')
    target_chat_id = data.get('target_chat_id')

    orig = Message.query.get(msg_id)
    if not orig:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Message not found'}}), 404

    src_chat = Chat.query.get(orig.chat_id) if orig.chat_id else None
    if src_chat is not None and getattr(src_chat, 'no_forwards', False):
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'Forwarding is disabled in this chat'}}), 403

    if not target_chat_id or not _chat_access(current_user_id, target_chat_id):
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'You are not in the target chat'}}), 403

    new_msg = Message(
        sender_id=current_user_id,
        content=orig.content,
        file_path=orig.file_path,
        file_type=orig.file_type,
        file_name=orig.file_name,
        file_size=orig.file_size,
        chat_id=target_chat_id,
        forwarded_from_id=orig.id,
        forwarded_by_id=current_user_id
    )
    db.session.add(new_msg)
    db.session.flush()

    fwd = Forward(
        original_message_id=orig.id,
        forwarded_message_id=new_msg.id,
        forwarded_by_id=current_user_id,
        original_sender_name=orig.sender.username if orig.sender else None
    )
    db.session.add(fwd)
    db.session.commit()

    return jsonify({'success': True, 'data': {'message_id': new_msg.id}})


# ── GIF Search ──────────────────────────────────────────────

@spav2_features_bp.route('/gifs/search', methods=['GET'])
def search_gifs():
    q = request.args.get('q', 'trending')
    limit = int(request.args.get('limit', 30))
    try:
        import urllib.request, json as j, ssl
        ctx = ssl._create_unverified_context()
        api_key = 'LIVDSRZULELA'
        url = f'https://g.tenor.com/v1/search?q={urllib.request.quote(q)}&key={api_key}&limit={limit}'
        with urllib.request.urlopen(url, timeout=5, context=ctx) as r:
            data = j.loads(r.read())
        gifs = []
        for r in data.get('results', []):
            media = r.get('media', [{}])[0]
            gif = media.get('gif', {})
            if gif.get('url'):
                gifs.append({'url': gif['url'], 'preview': gif.get('preview', gif['url'])})
        return jsonify({'success': True, 'data': {'gifs': gifs}})
    except Exception as e:
        return jsonify({'success': False, 'error': {'code': 'API_ERROR', 'message': str(e)}}), 500


# ── Message Search In-Chat ─────────────────────────────────

@spav2_features_bp.route('/messages/search', methods=['GET'])
def search_messages():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    q = request.args.get('q', '').strip()
    chat_id = request.args.get('chat_id', type=int)

    if not q or not chat_id:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION', 'message': 'q, chat_id required'}}), 400

    messages = Message.query.filter(
        Message.chat_id == chat_id,
        Message.is_deleted == False
    ).order_by(Message.timestamp.desc()).limit(50).all()

    messages = [m for m in messages if m.content and q.lower() in m.content.lower()]

    return jsonify({
        'success': True,
        'data': {
            'messages': [message_to_dict(m) for m in messages]
        }
    })


# ── Pinned Messages ────────────────────────────────────────

@spav2_features_bp.route('/messages/pin', methods=['POST'])
def pin_message():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    data = request.get_json() or {}
    msg_id = data.get('message_id')
    chat_id = data.get('chat_id')

    if not chat_id or not _chat_access(current_user_id, chat_id):
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'You are not in this chat'}}), 403

    msg = Message.query.get(msg_id)
    if not msg or msg.chat_id != chat_id:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Message not found in this chat'}}), 404

    existing = Pin.query.filter_by(message_id=msg_id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({'success': True, 'data': {'pinned': False}})

    pin = Pin(
        message_id=msg_id,
        chat_id=chat_id,
        pinned_by=current_user_id,
        pinned_at=datetime.now(timezone.utc)
    )
    db.session.add(pin)
    Pin.query.filter(Pin.chat_id == chat_id, Pin.id != pin.id).delete()
    db.session.commit()
    return jsonify({'success': True, 'data': {'pinned': True}})


@spav2_features_bp.route('/messages/pinned', methods=['GET'])
def get_pinned():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    chat_id = request.args.get('chat_id', type=int)
    if not chat_id:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION', 'message': 'chat_id required'}}), 400
    if not _chat_access(current_user_id, chat_id):
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'You are not in this chat'}}), 403

    pins = Pin.query.filter_by(chat_id=chat_id).order_by(Pin.pinned_at.desc()).all()
    msgs = []
    for p in pins:
        msg = Message.query.get(p.message_id)
        if msg:
            msgs.append(message_to_dict(msg))
    return jsonify({'success': True, 'data': {'messages': msgs}})


@spav2_features_bp.route('/messages/pinned/dismiss', methods=['POST'])
def dismiss_pinned():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    chat_id = (request.get_json() or {}).get('chat_id')
    if not chat_id or not _chat_access(current_user_id, chat_id):
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'You are not in this chat'}}), 403
    Pin.query.filter_by(chat_id=chat_id).delete()
    db.session.commit()
    return jsonify({'success': True})


# ── Group Admin Tools ──────────────────────────────────────

@spav2_features_bp.route('/groups/<int:chat_id>/invites', methods=['GET'])
def get_group_invites(chat_id):
    chat = Chat.query.get(chat_id)
    if not chat:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Group not found'}}), 404
    invites = InviteLink.query.filter_by(group_id=chat_id).all()
    return jsonify({
        'success': True,
        'data': {
            'invites': [{'id': i.id, 'code': i.code, 'link': i.link, 'uses': i.uses} for i in invites]
        }
    })


@spav2_features_bp.route('/groups/<int:chat_id>/invites/create', methods=['POST'])
def create_invite(chat_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    chat = Chat.query.get(chat_id)
    if not chat:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Group not found'}}), 404

    import secrets
    code = secrets.token_hex(8)
    link = f'https://kiselgram.ru/join/{code}'
    inv = InviteLink(group_id=chat_id, code=code, link=link, created_by=current_user_id)
    db.session.add(inv)
    chat.invite_link = code
    db.session.commit()
    return jsonify({'success': True, 'data': {'id': inv.id, 'code': code, 'link': link}})


@spav2_features_bp.route('/groups/<int:chat_id>/invites/revoke', methods=['POST'])
def revoke_invite(chat_id):
    data = request.get_json() or {}
    link_id = data.get('link_id')
    inv = InviteLink.query.filter_by(id=link_id, group_id=chat_id).first()
    if inv:
        db.session.delete(inv)
        db.session.commit()
    return jsonify({'success': True})


@spav2_features_bp.route('/groups/<int:chat_id>/promote', methods=['POST'])
def promote_member(chat_id):
    data = request.get_json() or {}
    user_id = data.get('user_id')
    member = ChatMember.query.filter_by(chat_id=chat_id, user_id=user_id).first()
    if member and member.role != 'owner':
        member.role = 'admin'
        db.session.commit()
    return jsonify({'success': True})


@spav2_features_bp.route('/groups/<int:chat_id>/demote', methods=['POST'])
def demote_member(chat_id):
    data = request.get_json() or {}
    user_id = data.get('user_id')
    member = ChatMember.query.filter_by(chat_id=chat_id, user_id=user_id).first()
    if member and member.role == 'admin':
        member.role = 'member'
        db.session.commit()
    return jsonify({'success': True})


@spav2_features_bp.route('/groups/<int:chat_id>/remove_member', methods=['POST'])
def remove_member(chat_id):
    data = request.get_json() or {}
    user_id = data.get('user_id')
    ChatMember.query.filter_by(chat_id=chat_id, user_id=user_id).delete()
    db.session.commit()
    return jsonify({'success': True})


@spav2_features_bp.route('/groups/<int:chat_id>/update', methods=['POST'])
def update_group(chat_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    data = request.get_json() or {}
    chat = Chat.query.get(chat_id)
    if not chat:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Group not found'}}), 404

    if data.get('name'):
        chat.name = data['name']
    if 'description' in data:
        chat.description = data.get('description', '')
    if 'is_public' in data:
        chat.is_public = data['is_public']
    db.session.commit()
    return jsonify({'success': True})


# ── Emoji / Sticker Sets ──────────────────────────────────

# ── Archive / Unarchive ─────────────────────────────────

@spav2_features_bp.route('/chats/<int:chat_id>/archive', methods=['POST'])
def archive_chat(chat_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    existing = Archive.query.filter_by(user_id=current_user_id, chat_id=chat_id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({'success': True, 'data': {'archived': False}})
    db.session.add(Archive(user_id=current_user_id, chat_id=chat_id))
    db.session.commit()
    return jsonify({'success': True, 'data': {'archived': True}})


@spav2_features_bp.route('/chats/<int:chat_id>/mute', methods=['POST'])
def mute_chat(chat_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    data = request.get_json() or {}
    until_ts = data.get('until')  # unix timestamp or None for forever
    chat = Chat.query.get(chat_id)
    if not chat:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Chat not found'}}), 404
    if until_ts:
        chat.muted_until = datetime.fromtimestamp(until_ts, tz=timezone.utc)
    else:
        chat.muted_until = datetime(2099, 1, 1)
    db.session.commit()
    return jsonify({'success': True, 'data': {'muted': True}})


@spav2_features_bp.route('/chats/<int:chat_id>/unmute', methods=['POST'])
def unmute_chat(chat_id):
    chat = Chat.query.get(chat_id)
    if chat:
        chat.muted_until = None
        db.session.commit()
    return jsonify({'success': True, 'data': {'muted': False}})


@spav2_features_bp.route('/chats/<int:chat_id>/theme', methods=['POST'])
def set_chat_theme(chat_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    if not _chat_access(current_user_id, chat_id):
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'You are not in this chat'}}), 403
    data = request.get_json() or {}
    chat = Chat.query.get(chat_id)
    if not chat:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Chat not found'}}), 404
    if 'theme_color' in data:
        chat.theme_color = data['theme_color']
    if 'wallpaper' in data:
        chat.wallpaper = data['wallpaper']
    if 'auto_delete_ttl' in data:
        chat.auto_delete_ttl = data['auto_delete_ttl']
    db.session.commit()
    return jsonify({'success': True, 'data': {'theme_color': chat.theme_color, 'wallpaper': chat.wallpaper}})


# ── Schedule Message ────────────────────────────────────

@spav2_features_bp.route('/messages/schedule', methods=['POST'])
def schedule_message():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    data = request.get_json() or {}
    content = data.get('content', '').strip()
    chat_id = data.get('chat_id')
    send_at = data.get('send_at')
    if not content or not chat_id or not send_at:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION', 'message': 'content, chat_id, send_at required'}}), 400
    try:
        scheduled = datetime.fromtimestamp(send_at, tz=timezone.utc)
    except Exception:
        return jsonify({'success': False, 'error': {'code': 'INVALID_DATE', 'message': 'Invalid timestamp'}}), 400
    msg = Message(
        sender_id=current_user_id,
        content=content,
        chat_id=chat_id,
        timestamp=datetime.now(timezone.utc),
        scheduled_at=scheduled
    )
    db.session.add(msg)
    db.session.commit()
    return jsonify({'success': True, 'data': {'message_id': msg.id, 'scheduled_at': scheduled.isoformat()}})


# ── Message Translation ─────────────────────────────────

@spav2_features_bp.route('/messages/translate', methods=['POST'])
def translate_message():
    data = request.get_json() or {}
    text = data.get('text', '')
    target_lang = data.get('target_lang', 'en')
    if not text:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION', 'message': 'text required'}}), 400
    try:
        import urllib.request, urllib.parse, json as j, ssl
        ctx = ssl._create_unverified_context()
        url = f'https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={target_lang}&dt=t&q={urllib.parse.quote(text)}'
        with urllib.request.urlopen(url, timeout=5, context=ctx) as r:
            result = r.read().decode('utf-8')
            parsed = j.loads(result)
            translated = ''.join([p[0] for p in parsed[0] if p[0]])
        return jsonify({'success': True, 'data': {'translated': translated, 'source_lang': parsed[2]}})
    except Exception as e:
        return jsonify({'success': False, 'error': {'code': 'API_ERROR', 'message': str(e)}}), 500


# ── Read Receipts ───────────────────────────────────────

@spav2_features_bp.route('/messages/<int:msg_id>/read_by', methods=['GET'])
def read_receipts(msg_id):
    msg = Message.query.get(msg_id)
    if not msg:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Message not found'}}), 404
    if msg.is_read and msg.read_at:
        readers = []
        chat = Chat.query.get(msg.chat_id)
        if chat and chat.chat_type == 'personal':
            reader_id = msg.receiver_id if msg.sender_id != msg.receiver_id else msg.sender_id
            reader = User.query.get(reader_id)
            if reader:
                readers.append({'user_id': reader.id, 'username': reader.username, 'read_at': msg.read_at.isoformat() if msg.read_at else None})
        return jsonify({'success': True, 'data': {'readers': readers, 'read_at': msg.read_at.isoformat() if msg.read_at else None}})
    return jsonify({'success': True, 'data': {'readers': [], 'read_at': None}})


# ── Search by Date ─────────────────────────────────────

@spav2_features_bp.route('/messages/search_by_date', methods=['GET'])
def search_by_date():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    chat_id = request.args.get('chat_id', type=int)
    date_str = request.args.get('date', '')
    if not chat_id or not date_str:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION', 'message': 'chat_id and date required'}}), 400
    try:
        from datetime import timedelta
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        dt_end = dt + timedelta(days=1)
    except Exception:
        return jsonify({'success': False, 'error': {'code': 'INVALID_DATE', 'message': 'Use YYYY-MM-DD'}}), 400
    msgs = Message.query.filter(
        Message.chat_id == chat_id,
        Message.timestamp >= dt,
        Message.timestamp < dt_end,
        Message.is_deleted == False
    ).order_by(Message.timestamp.asc()).limit(100).all()
    return jsonify({'success': True, 'data': {'messages': [message_to_dict(m) for m in msgs]}})


# ── Delete for everyone ────────────────────────────────

@spav2_features_bp.route('/messages/<int:msg_id>/delete_for_all', methods=['POST'])
def delete_for_all(msg_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    msg = Message.query.get(msg_id)
    if not msg:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Not found'}}), 404
    if msg.sender_id != current_user_id:
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'Not your message'}}), 403
    msg.is_deleted = True
    msg.deleted_for_all = True
    msg.content = ''
    db.session.commit()
    return jsonify({'success': True})

EMOJI_CATEGORIES = [
    {'id': 'smileys', 'name': 'Smileys', 'emojis': ['😀','😃','😄','😁','😅','😂','🤣','😊','😇','🙂','😉','😌','😍','🥰','😘','😗','😙','😚','😋','😛','😜','🤪','😝','🤑','🤗','🤭','🫢','🤫','🤔','🫡','🤐','🤨','😐','😑','😶','🫥','😏','😒','🙄','😬','🤥','😌','😔','😪','🤤','😴','😷','🤒','🤕','🤢','🤮','🥴','😵','🤯','🥳','🥺','😢','😭','😤','😠','😡','🤬','💀','☠️']},
    {'id': 'gestures', 'name': 'Gestures', 'emojis': ['👋','🤚','🖐','✋','🖖','🫱','🫲','🫳','🫴','👌','🤌','🤏','✌️','🤞','🫰','🤟','🤘','🤙','👈','👉','👆','🖕','👇','☝️','🫵','👍','👎','✊','👊','🤛','🤜','👏','🙌','🫶','👐','🤲','🤝','🙏','✍️','💅','🤳','💪','🦵','🦶','👂','🦻','👃','🧠','🫀','🫁','🦷','🦴','👀','👁','👅','👄']},
    {'id': 'people', 'name': 'People', 'emojis': ['👶','🧒','👦','👧','🧑','👱','👨','🧔','👩','🧓','👴','👵','🙍','🙎','🙅','🙆','💁','🙋','🧏','🙇','🤦','🤷','👮','🕵️','💂','🥷','👷','🫅','🤴','👸','👳','👲','🧕','🤵','👰','🤰','🫃','🫄','🤱','👼','🎅','🤶','🦸','🦹','🧙','🧚','🧛','🧜','🧝','🧞','🧟','🧌','💆','💇','🚶','🧍','🧎','🏃','💃','🕺','🕴️','👯','🧖','🧗','🤸','⛹️','🏋️','🚴','🚵','🤼','🤽','🤾','🤺','⛷️','🏂','🏄','🚣','🏊','🤿','🧘']},
    {'id': 'animals', 'name': 'Animals', 'emojis': ['🐶','🐱','🐭','🐹','🐰','🦊','🐻','🐼','🐻‍❄️','🐨','🐯','🦁','🐮','🐷','🐸','🐵','🙈','🙉','🙊','🐒','🐔','🐧','🐦','🐤','🐣','🐥','🦆','🦅','🦉','🦇','🐺','🐗','🐴','🦄','🐝','🐛','🦋','🐌','🐞','🐜','🦟','🦗','🦂','🐢','🐍','🦎','🦖','🦕','🐙','🦑','🦐','🦞','🦀','🐡','🐠','🐟','🐬','🐳','🐋','🦈','🐊','🐅','🐆','🦓','🦍','🦧','🐘','🦛','🦏','🐪','🐫','🦒','🦘','🦬','🐃','🐂','🐄','🐎','🐖','🐏','🐑','🦙','🐐','🦌','🐕','🐩','🦮','🐕‍🦺','🐈','🐈‍⬛','🪶','🐓','🦃','🦤','🦚','🦜','🦢','🦩','🕊️','🐇','🦝','🦨','🦡','🦫','🦦','🦥','🐁','🐀','🐿️','🦔','🐾','🐉','🐲']},
    {'id': 'food', 'name': 'Food', 'emojis': ['🍏','🍎','🍐','🍊','🍋','🍌','🍉','🍇','🍓','🫐','🍈','🍒','🍑','🥭','🍍','🥥','🥝','🍅','🍆','🥑','🥦','🥬','🥒','🌶️','🫑','🌽','🥕','🫒','🧄','🧅','🥔','🍠','🫘','🥐','🍞','🥖','🥨','🧀','🥚','🍳','🧈','🥞','🧇','🥓','🥩','🍗','🍖','🦴','🌭','🍔','🍟','🍕','🫓','🥪','🥙','🧆','🌮','🌯','🫔','🥗','🥘','🫕','🥫','🍝','🍜','🍲','🍛','🍣','🍱','🥟','🦪','🍤','🍙','🍚','🍘','🍥','🥠','🥮','🍢','🍡','🍧','🍨','🍦','🥧','🧁','🍰','🎂','🍮','🍭','🍬','🍫','🍿','🍩','🍪','🌰','🥜','🍯','🥛','🍼','🫖','☕','🍵','🧃','🥤','🧋','🍶','🍺','🍻','🥂','🍷','🫗','🥃','🍸','🍹','🧉','🍾','🧊','🥄','🍴','🍽️','🥣','🥡','🥢','🧂']},
    {'id': 'activity', 'name': 'Activity', 'emojis': ['⚽','🏀','🏈','⚾','🥎','🎾','🏐','🏉','🥏','🎱','🪀','🏓','🏸','🏒','🏑','🥍','🏏','🪃','🥅','⛳','🪁','🏹','🎣','🤿','🥊','🥋','🎯','🛝','⛸️','🎿','⛷️','🏂','🪂','🏋️','🤼','🤸','🤺','⛹️','🤾','🏌️','🏇','🧘','🏄','🏊','🤽','🚣','🧗','🚵','🚴','🎪','🎭','🎨','🎬','🎤','🎧','🎼','🎹','🥁','🪘','🎷','🎺','🪗','🎸','🪕','🎻','🎲','♟️','🎯','🎳','🎮','🕹️','🎰','🧩']},
    {'id': 'places', 'name': 'Places', 'emojis': ['🚗','🚕','🚙','🚌','🚎','🏎️','🚓','🚑','🚒','🚐','🛻','🚚','🚛','🚜','🏍️','🛵','🛺','🚲','🛴','🛹','🛼','🚏','🛣️','🛤️','⛽','🛑','🚨','🚥','🚦','🚧','⚓','🛟','⛵','🛶','🚤','🛳️','⛴️','🛥️','🚢','✈️','🛩️','🛫','🛬','🪂','💺','🚁','🚟','🚠','🚡','🛰️','🚀','🛸','🏠','🏡','🏘️','🏚️','🏗️','🏢','🏭','🏣','🏤','🏥','🏦','🏨','🏩','🏪','🏫','🏬','🏯','🏰','💒','🗼','🗽','⛪','🕌','🛕','🕍','⛩️','🕋','⛲','⛺','🌁','🌃','🏙️','🌄','🌅','🌆','🌇','🌉','🗾','🏔️','⛰️','🌋','🗻','🏕️','🏖️','🏜️','🏝️','🏞️']},
    {'id': 'objects', 'name': 'Objects', 'emojis': ['⌚','📱','💻','⌨️','🖥️','🖨️','🖱️','🖲️','🕹️','🗜️','💾','💿','📀','📼','📷','📸','📹','🎥','📽️','🎞️','📞','☎️','📟','📠','📺','📻','🎙️','🎚️','🎛️','🧭','⏱️','⏲️','⏰','🕰️','⌛','📡','🔋','🪫','🔌','💡','🔦','🕯️','🪔','🧯','🗑️','🛢️','💸','💵','💴','💶','💷','🪙','💰','💳','💎','⚖️','🪜','🧰','🪛','🔧','🔨','⚒️','🛠️','⛏️','🪚','🔩','⚙️','🪤','🧱','⛓️','🧲','🔫','💣','🧨','🪓','🔪','🗡️','⚔️','🛡️','🚬','⚰️','🪦','⚱️','🏺','🔮','📿','🧿','🪬','💈','⚗️','🔭','🔬','🕳️','🩻','🩹','🩺','💊','💉','🩸','🧬','🦠','🧫','🧪','🌡️','🧹','🪠','🧺','🧻','🚽','🚰','🚿','🛁','🛀','🧼','🪥','🪒','🧽','🪣','🧴','🛎️','🔑','🗝️','🚪','🪑','🛋️','🛏️','🛌','🧸','🪆','🖼️','🪞','🪟','🛍️','🛒','🎁','🎈','🎏','🎀','🪄','🪅','🎊','🎉','🎎','🏮','🎐','🧧','✉️','📩','📨','📧','💌','📥','📤','📦','🏷️','🪧','📪','📫','📬','📭','📮','📯','📜','📃','📄','📑','🧾','📊','📈','📉','🗒️','🗓️','📆','📅','🗑️','📇','🗃️','🗳️','🗄️','📋','📁','📂','🗂️','🗞️','📰','📓','📔','📒','📕','📗','📘','📙','📚','📖','🔖','🧷','🔗','📎','🖇️','📐','📏','🧮','📌','📍','✂️','🖊️','🖋️','✒️','🖌️','🖍️','📝','✏️','🔍','🔎','🔏','🔐','🔒','🔓']},
    {'id': 'symbols', 'name': 'Symbols', 'emojis': ['❤️','🧡','💛','💚','💙','💜','🖤','🤍','🤎','💔','❣️','💕','💞','💓','💗','💖','💘','💝','💟','☮️','✝️','☪️','🕉️','☸️','✡️','🔯','🕎','☯️','☦️','🛐','⛎','♈','♉','♊','♋','♌','♍','♎','♏','♐','♑','♒','♓','🆔','⚛️','🉑','☢️','☣️','📴','📳','🈶','🈚','🈸','🈺','🈷️','✴️','🉐','💹','🆚','🅰️','🅱️','🆎','🆑','🅾️','🆘','❌','⭕','🛑','⛔','📛','🚫','💯','💢','♨️','🚷','🚯','🚳','🚱','🔞','📵','🚭','❗','❕','❓','❔','‼️','⁉️','🔅','🔆','〽️','⚠️','🚸','🔱','⚜️','🔰','♻️','✅','🈯','💠','🌀','➿','🌐','Ⓜ️','🏧','🈂️','🛂','🛃','🛄','🛅','♿️','🚹','🚺','🚻','🚼','🚾','🛜','🆕','🆓','🆙','🆒','🆕','🆖','🆗','🆙','🆙','🆙','🆙']},
]


@spav2_features_bp.route('/emojis', methods=['GET'])
def get_emojis():
    return jsonify({'success': True, 'data': {'categories': EMOJI_CATEGORIES}})


# ── Forward to multiple chats (Telegram parity) ──────────

@spav2_features_bp.route('/messages/forward_multi', methods=['POST'])
def forward_message_multi():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    data = request.get_json() or {}
    msg_id = data.get('message_id')
    target_chat_ids = data.get('target_chat_ids') or []
    if not isinstance(target_chat_ids, list) or not target_chat_ids:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION', 'message': 'target_chat_ids (list) required'}}), 400

    orig = Message.query.get(msg_id)
    if not orig:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Message not found'}}), 404

    src_chat = Chat.query.get(orig.chat_id) if orig.chat_id else None
    if src_chat is not None and getattr(src_chat, 'no_forwards', False):
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'Forwarding is disabled in this chat'}}), 403

    created = []
    for tcid in target_chat_ids:
        if not _chat_access(current_user_id, tcid):
            continue
        new_msg = Message(
            sender_id=current_user_id, content=orig.content, file_path=orig.file_path,
            file_type=orig.file_type, file_name=orig.file_name, file_size=orig.file_size,
            chat_id=tcid, forwarded_from_id=orig.id, forwarded_by_id=current_user_id
        )
        db.session.add(new_msg)
        db.session.flush()
        db.session.add(Forward(original_message_id=orig.id, forwarded_message_id=new_msg.id,
                              forwarded_by_id=current_user_id,
                              original_sender_name=orig.sender.username if orig.sender else None))
        created.append(new_msg.id)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Database error'}}), 500
    return jsonify({'success': True, 'data': {'forwarded_ids': created, 'count': len(created)}})


# ── Chat export (Telegram parity) ────────────────────────

@spav2_features_bp.route('/chats/<int:chat_id>/export', methods=['GET'])
def export_chat(chat_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    if not _chat_access(current_user_id, chat_id):
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'You are not in this chat'}}), 403

    chat = Chat.query.get(chat_id)
    if not chat:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Chat not found'}}), 404

    msgs = Message.query.filter_by(chat_id=chat_id, is_deleted=False).order_by(Message.timestamp.asc()).all()
    out = []
    for m in msgs:
        out.append({
            'id': m.id, 'sender_id': m.sender_id,
            'sender': m.sender.username if m.sender else None,
            'content': m.content, 'file_type': m.file_type, 'file_name': m.file_name,
            'timestamp': m.timestamp.isoformat() if m.timestamp else None,
            'is_read': m.is_read,
        })
    return jsonify({'success': True, 'data': {
        'chat_id': chat_id, 'chat_type': chat.chat_type, 'name': chat.name,
        'exported_at': datetime.now(timezone.utc).isoformat(),
        'messages': out, 'count': len(out)
    }})


# ── Delete account (Telegram parity) ─────────────────────

@spav2_features_bp.route('/account/delete', methods=['POST'])
def delete_account():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    data = request.get_json() or {}
    user = User.query.get(current_user_id)
    if not user:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'User not found'}}), 404
    # require password confirmation
    pw = data.get('password')
    if pw and not user.check_password(pw):
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'Invalid password'}}), 403
    user.is_deleted = True
    user.deleted_at = datetime.now(timezone.utc)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Database error'}}), 500
    return jsonify({'success': True, 'data': {'message': 'Account deleted'}})


# ── Account self-destruction setting (Telegram parity) ───

@spav2_features_bp.route('/account/self_destruct', methods=['GET', 'POST'])
def self_destruct():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    user = User.query.get(current_user_id)
    if not user:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'User not found'}}), 404

    if request.method == 'GET':
        # default 6 months if not set
        days = getattr(user, 'self_destruct_days', None)
        return jsonify({'success': True, 'data': {'days': days if days is not None else 182}})

    data = request.get_json() or {}
    days = data.get('days')
    if days is not None:
        try:
            days = int(days)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': {'code': 'VALIDATION', 'message': 'days must be integer'}}), 400
        if days not in (30, 90, 182, 365):
            return jsonify({'success': False, 'error': {'code': 'VALIDATION', 'message': 'days must be 30, 90, 182 or 365'}}), 400
    # store on user if column exists; otherwise no-op but still respond
    if hasattr(user, 'self_destruct_days'):
        user.self_destruct_days = days
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Database error'}}), 500
    return jsonify({'success': True, 'data': {'days': days}})


# ── Recent actions log (Telegram parity) ─────────────────

@spav2_features_bp.route('/account/recent_actions', methods=['GET'])
def recent_actions():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    limit = min(int(request.args.get('limit', 50)), 200)
    msgs = Message.query.filter_by(sender_id=current_user_id).order_by(Message.timestamp.desc()).limit(limit).all()
    out = []
    for m in msgs:
        out.append({'id': m.id, 'chat_id': m.chat_id, 'content': (m.content or '')[:80],
                    'timestamp': m.timestamp.isoformat() if m.timestamp else None,
                    'is_deleted': m.is_deleted})
    return jsonify({'success': True, 'data': {'actions': out, 'count': len(out)}})


# ── Import chat history (Telegram parity) ────────────────

@spav2_features_bp.route('/chats/<int:chat_id>/import_history', methods=['POST'])
def import_chat_history(chat_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    if not _chat_access(current_user_id, chat_id):
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'You are not in this chat'}}), 403

    data = request.get_json() or {}
    items = data.get('messages') or []
    if not isinstance(items, list) or not items:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION', 'message': 'messages (list) required'}}), 400

    created = 0
    for it in items[:500]:
        content = (it.get('content') or '').strip() if isinstance(it, dict) else str(it).strip()
        if not content:
            continue
        ts = None
        if isinstance(it, dict) and it.get('timestamp'):
            try:
                ts = datetime.fromisoformat(it['timestamp'].replace('Z', '+00:00')).replace(tzinfo=None)
            except Exception:
                ts = None
        msg = Message(content=content, sender_id=current_user_id, chat_id=chat_id,
                      timestamp=ts or datetime.utcnow())
        db.session.add(msg)
        created += 1
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Database error'}}), 500
    return jsonify({'success': True, 'data': {'imported': created}})


# ── Mark all chats read (Telegram parity) ────────────────

@spav2_features_bp.route('/chats/mark_all_read', methods=['POST'])
def mark_all_chats_read():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    from app.models import Chat, ChatMember, ChatSubscriber
    chat_ids = set()
    for m in ChatMember.query.filter_by(user_id=current_user_id).all():
        chat_ids.add(m.chat_id)
    for s in ChatSubscriber.query.filter_by(user_id=current_user_id).all():
        chat_ids.add(s.chat_id)
    updated = 0
    for cid in chat_ids:
        updated += Message.query.filter_by(chat_id=cid, is_read=False).filter(Message.sender_id != current_user_id).update({'is_read': True, 'read_at': datetime.now(timezone.utc)})
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Database error'}}), 500
    return jsonify({'success': True, 'data': {'marked': updated}})


# ── Clear chat history (Telegram parity) ─────────────────

@spav2_features_bp.route('/chats/<int:chat_id>/clear', methods=['POST'])
def clear_chat_history(chat_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    if not _chat_access(current_user_id, chat_id):
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'You are not in this chat'}}), 403
    Message.query.filter_by(chat_id=chat_id).delete()
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Database error'}}), 500
    return jsonify({'success': True, 'data': {'cleared': True}})


# ── Delete chat (Telegram parity) ────────────────────────

@spav2_features_bp.route('/chats/<int:chat_id>/delete', methods=['POST'])
def delete_chat(chat_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    chat = Chat.query.get(chat_id)
    if not chat:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Chat not found'}}), 404
    if chat.chat_type == 'personal':
        if current_user_id not in (chat.user1_id, chat.user2_id):
            return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'You are not in this chat'}}), 403
    else:
        if chat.owner_id != current_user_id:
            return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'Only owner can delete'}}), 403
    Message.query.filter_by(chat_id=chat_id).delete()
    ChatMember.query.filter_by(chat_id=chat_id).delete()
    ChatSubscriber.query.filter_by(chat_id=chat_id).delete()
    db.session.delete(chat)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Database error'}}), 500
    return jsonify({'success': True, 'data': {'deleted': True}})


# ── Star / favorite messages (Telegram parity) ───────────

@spav2_features_bp.route('/messages/<int:message_id>/star', methods=['POST'])
def star_message(message_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    msg = Message.query.get(message_id)
    if not msg:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Message not found'}}), 404
    msg.is_saved = True
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Database error'}}), 500
    return jsonify({'success': True, 'data': {'starred': True}})


@spav2_features_bp.route('/messages/<int:message_id>/unstar', methods=['POST'])
def unstar_message(message_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    msg = Message.query.get(message_id)
    if not msg:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Message not found'}}), 404
    msg.is_saved = False
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Database error'}}), 500
    return jsonify({'success': True, 'data': {'starred': False}})


@spav2_features_bp.route('/messages/starred', methods=['GET'])
def starred_messages():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    chat_id = request.args.get('chat_id', type=int)
    q = Message.query.filter_by(is_saved=True)
    if chat_id:
        q = q.filter_by(chat_id=chat_id)
    msgs = q.order_by(Message.timestamp.desc()).limit(100).all()
    return jsonify({'success': True, 'data': {'messages': [message_to_dict(m, current_user_id) for m in msgs], 'count': len(msgs)}})


# ── Online users (Telegram parity) ───────────────────────

@spav2_features_bp.route('/users/online', methods=['GET'])
def online_users():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    from app.models import User
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)
    users = User.query.filter(User.is_online == True, User.last_seen >= cutoff).all()
    out = [{'id': u.id, 'username': u.username, 'display_name': u.display_name,
            'avatar_url': u.avatar_url} for u in users]
    return jsonify({'success': True, 'data': {'users': out, 'count': len(out)}})


# ── Chat info (Telegram parity) ───────────────────────────

@spav2_features_bp.route('/chats/<int:chat_id>/info', methods=['GET'])
def chat_info(chat_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    if not _chat_access(current_user_id, chat_id):
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'You are not in this chat'}}), 403
    chat = Chat.query.get(chat_id)
    if not chat:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Chat not found'}}), 404
    member_count = ChatMember.query.filter_by(chat_id=chat_id).count() if chat.chat_type in ('personal', 'group') else ChatSubscriber.query.filter_by(chat_id=chat_id).count()
    msg_count = Message.query.filter_by(chat_id=chat_id, is_deleted=False).count()
    return jsonify({'success': True, 'data': {
        'id': chat.id, 'chat_type': chat.chat_type, 'name': chat.name,
        'description': chat.description, 'avatar_url': chat.avatar_url,
        'owner_id': chat.owner_id, 'is_public': chat.is_public,
        'created_at': chat.created_at.isoformat() if chat.created_at else None,
        'member_count': member_count, 'message_count': msg_count,
        'muted_until': chat.muted_until.isoformat() if chat.muted_until else None,
        'theme_color': chat.theme_color, 'wallpaper': chat.wallpaper,
        'slow_mode': getattr(chat, 'slow_mode', 0),
        'no_forwards': getattr(chat, 'no_forwards', False),
    }})


# ── Leave chat (Telegram parity) ─────────────────────────

@spav2_features_bp.route('/chats/<int:chat_id>/leave', methods=['POST'])
def leave_chat(chat_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    chat = Chat.query.get(chat_id)
    if not chat:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Chat not found'}}), 404
    if chat.chat_type == 'personal':
        return jsonify({'success': False, 'error': {'code': 'VALIDATION', 'message': 'Cannot leave a personal chat'}}), 400
    if chat.chat_type == 'group':
        m = ChatMember.query.filter_by(chat_id=chat_id, user_id=current_user_id).first()
        if not m:
            return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Not a member'}}), 404
        if m.role == 'owner':
            return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'Owner cannot leave. Transfer ownership or delete.'}}), 403
        db.session.delete(m)
    elif chat.chat_type == 'channel':
        s = ChatSubscriber.query.filter_by(chat_id=chat_id, user_id=current_user_id).first()
        if s:
            db.session.delete(s)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Database error'}}), 500
    return jsonify({'success': True, 'data': {'left': True}})


# ── Join chat (Telegram parity) ──────────────────────────

@spav2_features_bp.route('/chats/<int:chat_id>/join', methods=['POST'])
def join_chat(chat_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    chat = Chat.query.get(chat_id)
    if not chat:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Chat not found'}}), 404
    if chat.chat_type == 'group':
        existing = ChatMember.query.filter_by(chat_id=chat_id, user_id=current_user_id).first()
        if not existing:
            db.session.add(ChatMember(chat_id=chat_id, user_id=current_user_id, role='member'))
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Database error'}}), 500
    elif chat.chat_type == 'channel':
        existing = ChatSubscriber.query.filter_by(chat_id=chat_id, user_id=current_user_id).first()
        if not existing:
            db.session.add(ChatSubscriber(chat_id=chat_id, user_id=current_user_id))
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Database error'}}), 500
    return jsonify({'success': True, 'data': {'joined': True}})


# ── Pin chat (Telegram parity) ───────────────────────────

@spav2_features_bp.route('/chats/<int:chat_id>/pin', methods=['POST'])
def pin_chat(chat_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    chat = Chat.query.get(chat_id)
    if not chat:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Chat not found'}}), 404
    chat_type = chat.chat_type
    existing = PinnedChat.query.filter_by(user_id=current_user_id, chat_type=chat_type, chat_id=chat_id).first()
    if existing:
        return jsonify({'success': True, 'data': {'pinned': True}})
    db.session.add(PinnedChat(user_id=current_user_id, chat_type=chat_type, chat_id=chat_id))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Database error'}}), 500
    return jsonify({'success': True, 'data': {'pinned': True}})


@spav2_features_bp.route('/chats/<int:chat_id>/unpin', methods=['POST'])
def unpin_chat(chat_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    chat = Chat.query.get(chat_id)
    if not chat:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Chat not found'}}), 404
    PinnedChat.query.filter_by(user_id=current_user_id, chat_type=chat.chat_type, chat_id=chat_id).delete()
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Database error'}}), 500
    return jsonify({'success': True, 'data': {'pinned': False}})


@spav2_features_bp.route('/chats/pinned', methods=['GET'])
def pinned_chats():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    pins = PinnedChat.query.filter_by(user_id=current_user_id).order_by(PinnedChat.pinned_at.desc()).all()
    out = [{'chat_type': p.chat_type, 'chat_id': p.chat_id, 'pinned_at': p.pinned_at.isoformat() if p.pinned_at else None} for p in pins]
    return jsonify({'success': True, 'data': {'pinned': out, 'count': len(out)}})


@spav2_features_bp.route('/chats/archived', methods=['GET'])
def archived_chats():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    from app.models import Chat, ChatMember, ChatSubscriber
    ids = set()
    for m in ChatMember.query.filter_by(user_id=current_user_id).all():
        ids.add(m.chat_id)
    for s in ChatSubscriber.query.filter_by(user_id=current_user_id).all():
        ids.add(s.chat_id)
    chats = Chat.query.filter(Chat.id.in_(ids), Chat.archived == True).all() if ids else []
    out = [{'id': c.id, 'chat_type': c.chat_type, 'name': c.name} for c in chats]
    return jsonify({'success': True, 'data': {'chats': out, 'count': len(out)}})


@spav2_features_bp.route('/chats/<int:chat_id>/unarchive', methods=['POST'])
def unarchive_chat(chat_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    chat = Chat.query.get(chat_id)
    if not chat:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Chat not found'}}), 404
    chat.archived = False
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Database error'}}), 500
    return jsonify({'success': True, 'data': {'archived': False}})


# ── Get chat members count (Telegram parity) ─────────────

@spav2_features_bp.route('/chats/<int:chat_id>/members_count', methods=['GET'])
def chat_members_count(chat_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    if not _chat_access(current_user_id, chat_id):
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'You are not in this chat'}}), 403
    chat = Chat.query.get(chat_id)
    if not chat:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Chat not found'}}), 404
    if chat.chat_type in ('personal', 'group'):
        count = ChatMember.query.filter_by(chat_id=chat_id).count()
    else:
        count = ChatSubscriber.query.filter_by(chat_id=chat_id).count()
    return jsonify({'success': True, 'data': {'chat_id': chat_id, 'count': count}})


# ── Set chat wallpaper (Telegram parity) ─────────────────

@spav2_features_bp.route('/chats/<int:chat_id>/wallpaper', methods=['POST'])
def set_chat_wallpaper(chat_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    if not _chat_access(current_user_id, chat_id):
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'You are not in this chat'}}), 403
    chat = Chat.query.get(chat_id)
    if not chat:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Chat not found'}}), 404
    data = request.get_json() or {}
    chat.wallpaper = data.get('wallpaper')
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Database error'}}), 500
    return jsonify({'success': True, 'data': {'wallpaper': chat.wallpaper}})


# ── Get chat wallpaper (Telegram parity) ─────────────────

@spav2_features_bp.route('/chats/<int:chat_id>/wallpaper', methods=['GET'])
def get_chat_wallpaper(chat_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    if not _chat_access(current_user_id, chat_id):
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'You are not in this chat'}}), 403
    chat = Chat.query.get(chat_id)
    if not chat:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Chat not found'}}), 404
    return jsonify({'success': True, 'data': {'wallpaper': chat.wallpaper, 'theme_color': chat.theme_color}})


# ── Get chat members (Telegram parity) ───────────────────

@spav2_features_bp.route('/chats/<int:chat_id>/members', methods=['GET'])
def chat_members(chat_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    if not _chat_access(current_user_id, chat_id):
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'You are not in this chat'}}), 403
    chat = Chat.query.get(chat_id)
    if not chat:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Chat not found'}}), 404
    if chat.chat_type in ('personal', 'group'):
        members = ChatMember.query.filter_by(chat_id=chat_id).all()
        out = [{'user_id': m.user_id, 'role': m.role, 'joined_at': m.joined_at.isoformat() if m.joined_at else None} for m in members]
    else:
        subs = ChatSubscriber.query.filter_by(chat_id=chat_id).all()
        out = [{'user_id': s.user_id, 'role': 'subscriber', 'subscribed_at': s.subscribed_at.isoformat() if s.subscribed_at else None} for s in subs]
    return jsonify({'success': True, 'data': {'members': out, 'count': len(out)}})


# ── Update group (Telegram parity) ───────────────────────

@spav2_features_bp.route('/groups/<int:group_id>/update', methods=['POST'])
def update_group_v2(group_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    chat = Chat.query.get(group_id)
    if not chat or chat.chat_type != 'group':
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Group not found'}}), 404
    if chat.owner_id != current_user_id:
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'Only owner can update'}}), 403
    data = request.get_json() or {}
    if 'name' in data:
        chat.name = data['name']
    if 'description' in data:
        chat.description = data['description']
    if 'is_public' in data:
        chat.is_public = bool(data['is_public'])
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Database error'}}), 500
    return jsonify({'success': True, 'data': {'updated': True}})


# ── Update channel (Telegram parity) ─────────────────────

@spav2_features_bp.route('/channels/<int:channel_id>/update', methods=['POST'])
def update_channel_v2(channel_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401
    chat = Chat.query.get(channel_id)
    if not chat or chat.chat_type != 'channel':
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Channel not found'}}), 404
    if chat.owner_id != current_user_id:
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'Only owner can update'}}), 403
    data = request.get_json() or {}
    if 'name' in data:
        chat.name = data['name']
    if 'description' in data:
        chat.description = data['description']
    if 'is_public' in data:
        chat.is_public = bool(data['is_public'])
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Database error'}}), 500
    return jsonify({'success': True, 'data': {'updated': True}})
