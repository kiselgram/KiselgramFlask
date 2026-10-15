from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from app import db
from app.models import User, Message, Poll, PollVote, Pin, Forward, Chat, ChatMember, ChatSubscriber, InviteLink, File, Archive, SavedMessage
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
