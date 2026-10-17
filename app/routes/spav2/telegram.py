# app/routes/spav2/telegram.py
"""Telegram parity pack — Telegram features missing in Kiselgram.

Topics/threads, slow mode, quiz polls, dice, live location, auto-delete
+ story archive, voice chats, discussion linking + comments, no-forward
protection, saved tags, hidden members, bot commands, message deep links.
"""

from __future__ import annotations

import random
import re
import time
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from app import db
from app.models import (
    ChannelAdmin,
    Chat,
    ChatMember,
    ChatSubscriber,
    Message,
    Poll,
    PollVote,
    Reply,
    SavedMessage,
    Story,
    TgBotCommand,
    TgCollectible,
    TgLiveLocation,
    TgTopic,
    User,
    VideoCall,
)
from app.utils.helpers import get_current_user_id, slow_mode_ok

spav2_telegram_bp = Blueprint('spav2_telegram', __name__, url_prefix='/api')

_prune_at = 0.0


def _auth():
    uid = get_current_user_id()
    if not uid:
        return None, (jsonify({'success': False, 'error': 'Not authenticated'}), 401)
    return uid, None


def _is_admin(uid: int) -> bool:
    u = User.query.get(uid)
    return bool(u and u.is_admin)


def _group_admin(chat_id, uid):
    chat = Chat.query.get(chat_id)
    if not chat or chat.chat_type != 'group':
        return None
    if chat.owner_id == uid or _is_admin(uid):
        return chat
    m = ChatMember.query.filter_by(chat_id=chat_id, user_id=uid).first()
    if m and (m.role or '') in ('owner', 'admin'):
        return chat
    return None


def _member(chat_id, uid):
    return ChatMember.query.filter_by(chat_id=chat_id, user_id=uid).first()


def _prune():
    """Delete TTL-expired messages, archive 24h+ stories. Throttled 60s."""
    global _prune_at
    now = time.time()
    if now - _prune_at < 60:
        return
    _prune_at = now
    try:
        for chat in Chat.query.filter(Chat.auto_delete_ttl.isnot(None)).all():
            cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=chat.auto_delete_ttl or 0)
            Message.query.filter(Message.chat_id == chat.id, Message.timestamp < cutoff).delete()
        day_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
        Story.query.filter(Story.created_at < day_ago, Story.is_archived.is_(False)).update({'is_archived': True})
        db.session.commit()
    except Exception:
        db.session.rollback()


def _slow(uid, chat_id):
    ok, retry = slow_mode_ok(uid, chat_id)
    if not ok:
        return jsonify({'success': False, 'error': f'Slow mode: wait {retry}s'}), 429
    return None


# --- 1. forum topics ----------------------------------------------------------

@spav2_telegram_bp.route('/tg/groups/<int:chat_id>/topics', methods=['POST'])
def tg_topic_create(chat_id):
    uid, err = _auth()
    if err:
        return err
    if not _member(chat_id, uid):
        return jsonify({'success': False, 'error': 'Not a member'}), 403
    data = request.get_json() or {}
    title = (data.get('title') or '').strip()[:80]
    if not title:
        return jsonify({'success': False, 'error': 'Title required'}), 400
    t = TgTopic(chat_id=chat_id, title=title, icon=(data.get('icon') or '')[:16] or None, created_by=uid)
    db.session.add(t)
    db.session.commit()
    return jsonify({'success': True, 'data': {'topic_id': t.id}})


@spav2_telegram_bp.route('/tg/groups/<int:chat_id>/topics', methods=['GET'])
def tg_topic_list(chat_id):
    uid, err = _auth()
    if err:
        return err
    if not _member(chat_id, uid):
        return jsonify({'success': False, 'error': 'Not a member'}), 403
    out = []
    for t in TgTopic.query.filter_by(chat_id=chat_id).order_by(TgTopic.created_at.asc()).all():
        n = Message.query.filter_by(topic_id=t.id, is_deleted=False).count()
        last = Message.query.filter_by(topic_id=t.id, is_deleted=False).order_by(Message.timestamp.desc()).first()
        out.append({'topic_id': t.id, 'title': t.title, 'icon': t.icon, 'is_closed': t.is_closed,
                    'messages': n, 'last_at': last.timestamp.isoformat() if last and last.timestamp else None})
    return jsonify({'success': True, 'data': {'topics': out}})


@spav2_telegram_bp.route('/tg/topics/<int:tid>', methods=['POST'])
def tg_topic_update(tid):
    uid, err = _auth()
    if err:
        return err
    t = TgTopic.query.get(tid)
    if not t:
        return jsonify({'success': False, 'error': 'Topic not found'}), 404
    if not _group_admin(t.chat_id, uid) and t.created_by != uid:
        return jsonify({'success': False, 'error': 'Not allowed'}), 403
    data = request.get_json() or {}
    if 'title' in data:
        title = (data.get('title') or '').strip()[:80]
        if not title:
            return jsonify({'success': False, 'error': 'Title required'}), 400
        t.title = title
    if 'is_closed' in data:
        t.is_closed = bool(data['is_closed'])
    db.session.commit()
    return jsonify({'success': True})


@spav2_telegram_bp.route('/tg/topics/<int:tid>', methods=['DELETE'])
def tg_topic_delete(tid):
    uid, err = _auth()
    if err:
        return err
    t = TgTopic.query.get(tid)
    if not t:
        return jsonify({'success': False, 'error': 'Topic not found'}), 404
    if not _group_admin(t.chat_id, uid):
        return jsonify({'success': False, 'error': 'Not allowed'}), 403
    Message.query.filter_by(topic_id=t.id).update({'topic_id': None})
    db.session.delete(t)
    db.session.commit()
    return jsonify({'success': True})


@spav2_telegram_bp.route('/tg/topics/<int:tid>/send', methods=['POST'])
def tg_topic_send(tid):
    uid, err = _auth()
    if err:
        return err
    t = TgTopic.query.get(tid)
    if not t:
        return jsonify({'success': False, 'error': 'Topic not found'}), 404
    if not _member(t.chat_id, uid):
        return jsonify({'success': False, 'error': 'Not a member'}), 403
    if t.is_closed:
        return jsonify({'success': False, 'error': 'Topic is closed'}), 403
    slow = _slow(uid, t.chat_id)
    if slow:
        return slow
    _prune()
    content = ((request.get_json() or {}).get('content') or '').strip()
    if not content:
        return jsonify({'success': False, 'error': 'Content required'}), 400
    m = Message(sender_id=uid, chat_id=t.chat_id, receiver_id=uid, content=content,
                topic_id=t.id, timestamp=datetime.now(timezone.utc).replace(tzinfo=None))
    db.session.add(m)
    db.session.commit()
    return jsonify({'success': True, 'data': {'message_id': m.id}}), 201


@spav2_telegram_bp.route('/tg/topics/<int:tid>/messages', methods=['GET'])
def tg_topic_messages(tid):
    uid, err = _auth()
    if err:
        return err
    t = TgTopic.query.get(tid)
    if not t:
        return jsonify({'success': False, 'error': 'Topic not found'}), 404
    if not _member(t.chat_id, uid):
        return jsonify({'success': False, 'error': 'Not a member'}), 403
    limit = min(request.args.get('limit', 50, type=int) or 50, 100)
    msgs = Message.query.filter_by(topic_id=t.id, is_deleted=False).order_by(Message.timestamp.desc()).limit(limit).all()
    return jsonify({'success': True, 'data': {'messages': [
        {'message_id': m.id, 'sender_id': m.sender_id, 'content': m.content,
         'timestamp': m.timestamp.isoformat() if m.timestamp else None} for m in reversed(msgs)]}})


# --- 2. slow mode ---------------------------------------------------------------

@spav2_telegram_bp.route('/tg/groups/<int:chat_id>/slowmode', methods=['GET'])
def tg_slow_get(chat_id):
    uid, err = _auth()
    if err:
        return err
    if not _member(chat_id, uid):
        return jsonify({'success': False, 'error': 'Not a member'}), 403
    chat = Chat.query.get(chat_id)
    return jsonify({'success': True, 'data': {'slow_mode': getattr(chat, 'slow_mode', 0) or 0}})


@spav2_telegram_bp.route('/tg/groups/<int:chat_id>/slowmode', methods=['POST'])
def tg_slow_set(chat_id):
    uid, err = _auth()
    if err:
        return err
    if not _group_admin(chat_id, uid):
        return jsonify({'success': False, 'error': 'Not allowed'}), 403
    try:
        secs = int((request.get_json() or {}).get('seconds', 0))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Bad seconds'}), 400
    if secs < 0 or secs > 300:
        return jsonify({'success': False, 'error': 'Range 0-300'}), 400
    chat = Chat.query.get(chat_id)
    chat.slow_mode = secs
    db.session.commit()
    return jsonify({'success': True, 'data': {'slow_mode': secs}})


# --- 3. quiz polls ------------------------------------------------------------------

@spav2_telegram_bp.route('/tg/polls/<int:poll_id>/quiz', methods=['POST'])
def tg_quiz_set(poll_id):
    uid, err = _auth()
    if err:
        return err
    poll = Poll.query.get(poll_id)
    if not poll:
        return jsonify({'success': False, 'error': 'Poll not found'}), 404
    if poll.creator_id != uid and not _is_admin(uid):
        return jsonify({'success': False, 'error': 'Only the creator'}), 403
    data = request.get_json() or {}
    try:
        ans = int(data.get('answer'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'answer required'}), 400
    if not (0 <= ans < len(poll.options or [])):
        return jsonify({'success': False, 'error': 'Bad answer index'}), 400
    poll.quiz_answer = ans
    poll.quiz_explanation = (data.get('explanation') or '')[:500] or None
    db.session.commit()
    return jsonify({'success': True})


@spav2_telegram_bp.route('/tg/polls/<int:poll_id>/answer', methods=['GET'])
def tg_quiz_answer(poll_id):
    uid, err = _auth()
    if err:
        return err
    poll = Poll.query.get(poll_id)
    if not poll:
        return jsonify({'success': False, 'error': 'Poll not found'}), 404
    options = poll.options or []
    counts = [0] * len(options)
    for v in PollVote.query.filter_by(poll_id=poll.id).all():
        if 0 <= v.option_index < len(counts):
            counts[v.option_index] += 1
    mine = PollVote.query.filter_by(poll_id=poll.id, user_id=uid).order_by(PollVote.id.desc()).first()
    data = {'poll_id': poll.id, 'closed': poll.closed, 'options': options,
            'counts': counts, 'total': sum(counts)}
    if poll.quiz_answer is not None:
        data['quiz_answer'] = poll.quiz_answer
        data['quiz_explanation'] = poll.quiz_explanation
        data['my_correct'] = (mine.option_index == poll.quiz_answer) if mine else None
    return jsonify({'success': True, 'data': data})


# --- 4. dice --------------------------------------------------------------------------

_DICE_FACES = ['⚀', '⚁', '⚂', '⚃', '⚄', '⚅']


@spav2_telegram_bp.route('/tg/dice', methods=['POST'])
def tg_dice():
    from app.routes.spav2.sputnik import _resolve_chat_id
    uid, err = _auth()
    if err:
        return err
    data = request.get_json() or {}
    chat_id, receiver_id, cerr = _resolve_chat_id(uid, data)
    if cerr:
        return cerr
    slow = _slow(uid, chat_id)
    if slow:
        return slow
    _prune()
    value = random.randint(1, 6)
    m = Message(sender_id=uid, chat_id=chat_id, receiver_id=receiver_id or uid,
                content=str(value), file_type='dice', emoji=_DICE_FACES[value - 1],
                timestamp=datetime.now(timezone.utc).replace(tzinfo=None))
    db.session.add(m)
    db.session.commit()
    return jsonify({'success': True, 'data': {'message_id': m.id, 'value': value}}), 201


# --- 5. live location --------------------------------------------------------------------

@spav2_telegram_bp.route('/tg/geo/share', methods=['POST'])
def tg_geo_share():
    from app.routes.spav2.sputnik import _resolve_chat_id
    uid, err = _auth()
    if err:
        return err
    data = request.get_json() or {}
    chat_id, receiver_id, cerr = _resolve_chat_id(uid, data)
    if cerr:
        return cerr
    slow = _slow(uid, chat_id)
    if slow:
        return slow
    _prune()
    try:
        lat, lon = float(data.get('lat')), float(data.get('lon'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'lat/lon required'}), 400
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return jsonify({'success': False, 'error': 'Bad coordinates'}), 400
    try:
        live_min = int(data.get('live_minutes') or 0)
    except (TypeError, ValueError):
        live_min = 0
    if live_min and not (1 <= live_min <= 480):
        return jsonify({'success': False, 'error': 'live_minutes 1-480'}), 400
    m = Message(sender_id=uid, chat_id=chat_id, receiver_id=receiver_id or uid,
                content=f'{lat},{lon}', file_type='geo',
                timestamp=datetime.now(timezone.utc).replace(tzinfo=None))
    db.session.add(m)
    db.session.flush()
    if live_min:
        db.session.add(TgLiveLocation(
            message_id=m.id, user_id=uid, chat_id=chat_id, lat=lat, lon=lon,
            until=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=live_min)))
    db.session.commit()
    return jsonify({'success': True, 'data': {'message_id': m.id, 'live': bool(live_min)}}), 201


@spav2_telegram_bp.route('/tg/geo/<int:mid>/update', methods=['POST'])
def tg_geo_update(mid):
    uid, err = _auth()
    if err:
        return err
    row = TgLiveLocation.query.filter_by(message_id=mid, user_id=uid).first()
    if not row or row.until < datetime.now(timezone.utc).replace(tzinfo=None):
        return jsonify({'success': False, 'error': 'Share expired or missing'}), 404
    data = request.get_json() or {}
    try:
        lat, lon = float(data.get('lat')), float(data.get('lon'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'lat/lon required'}), 400
    row.lat, row.lon = lat, lon
    m = Message.query.get(mid)
    if m:
        m.content = f'{lat},{lon}'
    db.session.commit()
    return jsonify({'success': True})


@spav2_telegram_bp.route('/tg/geo/<int:mid>/stop', methods=['POST'])
def tg_geo_stop(mid):
    uid, err = _auth()
    if err:
        return err
    row = TgLiveLocation.query.filter_by(message_id=mid, user_id=uid).first()
    if not row:
        return jsonify({'success': False, 'error': 'Not found'}), 404
    db.session.delete(row)
    db.session.commit()
    return jsonify({'success': True})


@spav2_telegram_bp.route('/tg/geo/live', methods=['GET'])
def tg_geo_live():
    uid, err = _auth()
    if err:
        return err
    from app.routes.spav2.features import _chat_access
    chat_id = request.args.get('chat_id', type=int)
    q = TgLiveLocation.query.filter(TgLiveLocation.until > datetime.now(timezone.utc).replace(tzinfo=None))
    if chat_id:
        q = q.filter_by(chat_id=chat_id)
    out = []
    for r in q.order_by(TgLiveLocation.updated_at.desc()).limit(100).all():
        if not _chat_access(uid, r.chat_id):
            continue
        out.append({'message_id': r.message_id, 'user_id': r.user_id, 'chat_id': r.chat_id,
                    'lat': r.lat, 'lon': r.lon, 'until': r.until.isoformat()})
    return jsonify({'success': True, 'data': {'live': out}})


# --- 6. maintenance + story archive ---------------------------------------------------------

@spav2_telegram_bp.route('/tg/maintenance/prune', methods=['POST'])
def tg_prune():
    uid, err = _auth()
    if err:
        return err
    if not _is_admin(uid):
        return jsonify({'success': False, 'error': 'Admin only'}), 403
    global _prune_at
    _prune_at = 0
    _prune()
    return jsonify({'success': True})


@spav2_telegram_bp.route('/tg/stories/archive', methods=['GET'])
def tg_story_archive():
    uid, err = _auth()
    if err:
        return err
    rows = Story.query.filter_by(user_id=uid, is_archived=True).order_by(Story.created_at.desc()).limit(100).all()
    return jsonify({'success': True, 'data': {'stories': [
        {'story_id': s.id, 'media_path': s.media_path, 'media_type': s.media_type,
         'caption': s.caption, 'created_at': s.created_at.isoformat() if s.created_at else None}
        for s in rows]}})


# --- 7. voice chats (group audio rooms) ----------------------------------------------------------

@spav2_telegram_bp.route('/tg/voice/start', methods=['POST'])
def tg_voice_start():
    import secrets as _secrets
    uid, err = _auth()
    if err:
        return err
    chat_id = (request.get_json() or {}).get('chat_id')
    if not _member(chat_id, uid):
        return jsonify({'success': False, 'error': 'Not a member'}), 403
    live = VideoCall.query.filter_by(chat_id=chat_id, call_type='voice', status='active').first()
    if live:
        return jsonify({'success': True, 'data': {'room_id': live.room_id, 'resumed': True}})
    room = _secrets.token_hex(6)
    vc = VideoCall(room_id=room, creator_id=uid, chat_id=chat_id, call_type='voice', status='active')
    db.session.add(vc)
    db.session.commit()
    return jsonify({'success': True, 'data': {'room_id': room}}), 201


@spav2_telegram_bp.route('/tg/voice/active', methods=['GET'])
def tg_voice_active():
    uid, err = _auth()
    if err:
        return err
    chat_id = request.args.get('chat_id', type=int)
    q = VideoCall.query.filter_by(call_type='voice', status='active')
    if chat_id:
        if not _member(chat_id, uid):
            return jsonify({'success': False, 'error': 'Not a member'}), 403
        q = q.filter_by(chat_id=chat_id)
    rooms = q.order_by(VideoCall.started_at.desc()).limit(50).all()
    return jsonify({'success': True, 'data': {'rooms': [
        {'room_id': r.room_id, 'chat_id': r.chat_id, 'creator_id': r.creator_id,
         'participant_count': r.participant_count} for r in rooms]}})


@spav2_telegram_bp.route('/tg/voice/<room_id>/end', methods=['POST'])
def tg_voice_end(room_id):
    uid, err = _auth()
    if err:
        return err
    vc = VideoCall.query.filter_by(room_id=room_id, call_type='voice').first()
    if not vc:
        return jsonify({'success': False, 'error': 'Room not found'}), 404
    if vc.creator_id != uid and not _group_admin(vc.chat_id, uid) and not _is_admin(uid):
        return jsonify({'success': False, 'error': 'Not allowed'}), 403
    vc.status = 'ended'
    vc.ended_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.commit()
    return jsonify({'success': True})


# --- 8. discussion linking + comments -----------------------------------------------------------------

@spav2_telegram_bp.route('/tg/channels/<int:cid>/link', methods=['POST'])
def tg_disc_link(cid):
    uid, err = _auth()
    if err:
        return err
    ch = Chat.query.get(cid)
    if not ch or ch.chat_type != 'channel':
        return jsonify({'success': False, 'error': 'Channel not found'}), 404
    if ch.owner_id != uid and not ChannelAdmin.query.filter_by(chat_id=cid, user_id=uid).first() and not _is_admin(uid):
        return jsonify({'success': False, 'error': 'Not a channel admin'}), 403
    try:
        gid = int((request.get_json() or {}).get('group_id'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'group_id required'}), 400
    if not _group_admin(gid, uid):
        return jsonify({'success': False, 'error': 'Not a group admin'}), 403
    ch.linked_chat_id = gid
    grp = Chat.query.get(gid)
    if grp:
        grp.linked_chat_id = cid
    db.session.commit()
    return jsonify({'success': True})


@spav2_telegram_bp.route('/tg/channels/<int:cid>/link', methods=['DELETE'])
def tg_disc_unlink(cid):
    uid, err = _auth()
    if err:
        return err
    ch = Chat.query.get(cid)
    if not ch or ch.chat_type != 'channel':
        return jsonify({'success': False, 'error': 'Channel not found'}), 404
    if ch.owner_id != uid and not _is_admin(uid):
        return jsonify({'success': False, 'error': 'Not allowed'}), 403
    if ch.linked_chat_id:
        grp = Chat.query.get(ch.linked_chat_id)
        if grp and grp.linked_chat_id == cid:
            grp.linked_chat_id = None
        ch.linked_chat_id = None
    db.session.commit()
    return jsonify({'success': True})


@spav2_telegram_bp.route('/tg/comments', methods=['POST'])
def tg_comment_add():
    uid, err = _auth()
    if err:
        return err
    data = request.get_json() or {}
    orig = Message.query.get(data.get('channel_message_id'))
    if not orig:
        return jsonify({'success': False, 'error': 'Message not found'}), 404
    ch = Chat.query.get(orig.chat_id)
    if not ch or ch.chat_type != 'channel' or not ch.linked_chat_id:
        return jsonify({'success': False, 'error': 'No discussion group linked'}), 400
    if not ChatSubscriber.query.filter_by(chat_id=ch.id, user_id=uid).first() and ch.owner_id != uid:
        return jsonify({'success': False, 'error': 'Subscribe to comment'}), 403
    if not _member(ch.linked_chat_id, uid):
        return jsonify({'success': False, 'error': 'Join the discussion group first'}), 403
    slow = _slow(uid, ch.linked_chat_id)
    if slow:
        return slow
    _prune()
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({'success': False, 'error': 'Content required'}), 400
    m = Message(sender_id=uid, chat_id=ch.linked_chat_id, receiver_id=uid, content=content,
                timestamp=datetime.now(timezone.utc).replace(tzinfo=None))
    db.session.add(m)
    db.session.flush()
    db.session.add(Reply(original_message_id=orig.id, reply_message_id=m.id))
    db.session.commit()
    return jsonify({'success': True, 'data': {'message_id': m.id}}), 201


@spav2_telegram_bp.route('/tg/comments/<int:mid>', methods=['GET'])
def tg_comment_list(mid):
    uid, err = _auth()
    if err:
        return err
    rows = Reply.query.filter_by(original_message_id=mid).order_by(Reply.id.asc()).limit(100).all()
    out = []
    for r in rows:
        m = Message.query.get(r.reply_message_id)
        if m and not m.is_deleted:
            out.append({'message_id': m.id, 'sender_id': m.sender_id, 'content': m.content,
                        'timestamp': m.timestamp.isoformat() if m.timestamp else None})
    return jsonify({'success': True, 'data': {'comments': out, 'count': len(out)}})


# --- 9. content protection ------------------------------------------------------------------------------

@spav2_telegram_bp.route('/tg/chats/<int:chat_id>/protect', methods=['POST'])
def tg_protect(chat_id):
    uid, err = _auth()
    if err:
        return err
    chat = Chat.query.get(chat_id)
    if not chat or chat.chat_type not in ('group', 'channel'):
        return jsonify({'success': False, 'error': 'Chat not found'}), 404
    allowed = chat.owner_id == uid or _is_admin(uid) or _group_admin(chat_id, uid) is not None
    if not allowed and chat.chat_type == 'channel':
        allowed = ChannelAdmin.query.filter_by(chat_id=chat_id, user_id=uid).first() is not None
    if not allowed:
        return jsonify({'success': False, 'error': 'Not allowed'}), 403
    chat.no_forwards = bool((request.get_json() or {}).get('no_forwards', True))
    db.session.commit()
    return jsonify({'success': True, 'data': {'no_forwards': chat.no_forwards}})


# --- 10. saved tags ------------------------------------------------------------------------------------------

@spav2_telegram_bp.route('/tg/saved/tag', methods=['POST'])
def tg_saved_tag():
    uid, err = _auth()
    if err:
        return err
    data = request.get_json() or {}
    mid = data.get('message_id')
    if not Message.query.get(mid):
        return jsonify({'success': False, 'error': 'Message not found'}), 404
    tag = (data.get('tag') or '')[:40] or None
    row = SavedMessage.query.filter_by(user_id=uid, message_id=mid).first()
    if not row:
        row = SavedMessage(user_id=uid, message_id=mid, tag=tag)
        db.session.add(row)
    else:
        row.tag = tag
    db.session.commit()
    return jsonify({'success': True})


@spav2_telegram_bp.route('/tg/saved', methods=['GET'])
def tg_saved_list():
    uid, err = _auth()
    if err:
        return err
    tag = (request.args.get('tag') or '')[:40]
    limit = min(request.args.get('limit', 50, type=int) or 50, 100)
    q = SavedMessage.query.filter_by(user_id=uid)
    if tag:
        q = q.filter_by(tag=tag)
    rows = q.order_by(SavedMessage.saved_at.desc()).limit(limit).all()
    return jsonify({'success': True, 'data': {'saved': [
        {'message_id': r.message_id, 'tag': r.tag} for r in rows]}})


@spav2_telegram_bp.route('/tg/saved/tags', methods=['GET'])
def tg_saved_tags():
    uid, err = _auth()
    if err:
        return err
    rows = db.session.query(SavedMessage.tag, db.func.count(SavedMessage.id)).filter(
        SavedMessage.user_id == uid, SavedMessage.tag.isnot(None)).group_by(SavedMessage.tag).all()
    return jsonify({'success': True, 'data': {'tags': [{'tag': t, 'count': c} for t, c in rows]}})


# --- 11. hidden members --------------------------------------------------------------------------------------------

@spav2_telegram_bp.route('/tg/groups/<int:chat_id>/visibility', methods=['POST'])
def tg_visibility(chat_id):
    uid, err = _auth()
    if err:
        return err
    if not _group_admin(chat_id, uid):
        return jsonify({'success': False, 'error': 'Not allowed'}), 403
    chat = Chat.query.get(chat_id)
    chat.hide_members = bool((request.get_json() or {}).get('hide_members', True))
    db.session.commit()
    return jsonify({'success': True, 'data': {'hide_members': chat.hide_members}})


@spav2_telegram_bp.route('/tg/groups/<int:chat_id>/members', methods=['GET'])
def tg_members(chat_id):
    uid, err = _auth()
    if err:
        return err
    chat = Chat.query.get(chat_id)
    if not chat or chat.chat_type != 'group':
        return jsonify({'success': False, 'error': 'Group not found'}), 404
    if not _member(chat_id, uid):
        return jsonify({'success': False, 'error': 'Not a member'}), 403
    total = ChatMember.query.filter_by(chat_id=chat_id).count()
    if chat.hide_members and not _group_admin(chat_id, uid):
        return jsonify({'success': True, 'data': {'hidden': True, 'count': total, 'members': []}})
    rows = ChatMember.query.filter_by(chat_id=chat_id).limit(200).all()
    out = []
    for m in rows:
        u = User.query.get(m.user_id)
        out.append({'user_id': m.user_id, 'role': m.role, 'username': u.username if u else None})
    return jsonify({'success': True, 'data': {'hidden': False, 'count': total, 'members': out}})


# --- 12. bot commands ---------------------------------------------------------------------------------------------------

_BOT_CMD_RE = __import__('re').compile(r'^[a-z0-9_]{1,32}$')


@spav2_telegram_bp.route('/tg/bots/commands', methods=['POST'])
def tg_bot_cmd_set():
    uid, err = _auth()
    if err:
        return err
    me = User.query.get(uid)
    if not (me and (me.is_bot or me.is_admin)):
        return jsonify({'success': False, 'error': 'Bots only'}), 403
    data = request.get_json() or {}
    cmd = (data.get('command') or '').strip().lower().lstrip('/')
    if not _BOT_CMD_RE.match(cmd):
        return jsonify({'success': False, 'error': 'Command: 1-32 chars a-z0-9_'}), 400
    row = TgBotCommand.query.filter_by(bot_id=uid, command=cmd).first()
    if not row:
        row = TgBotCommand(bot_id=uid, command=cmd)
        db.session.add(row)
    row.description = (data.get('description') or '')[:255] or None
    db.session.commit()
    return jsonify({'success': True, 'data': {'command': cmd}})


@spav2_telegram_bp.route('/tg/bots/<int:bot_id>/commands', methods=['GET'])
def tg_bot_cmd_list(bot_id):
    rows = TgBotCommand.query.filter_by(bot_id=bot_id).order_by(TgBotCommand.command.asc()).all()
    return jsonify({'success': True, 'data': {'commands': [
        {'command': r.command, 'description': r.description} for r in rows]}})


@spav2_telegram_bp.route('/tg/bots/commands/<int:cid>', methods=['DELETE'])
def tg_bot_cmd_del(cid):
    uid, err = _auth()
    if err:
        return err
    row = TgBotCommand.query.get(cid)
    if not row:
        return jsonify({'success': False, 'error': 'Not found'}), 404
    if row.bot_id != uid and not _is_admin(uid):
        return jsonify({'success': False, 'error': 'Not allowed'}), 403
    db.session.delete(row)
    db.session.commit()
    return jsonify({'success': True})


@spav2_telegram_bp.route('/tg/features', methods=['GET'])
def tg_features():
    return jsonify({'success': True, 'data': {
        'ideas': ['topics', 'slowmode', 'quiz', 'dice', 'live-geo', 'autodelete',
                  'story-archive', 'voice-chats', 'discussion', 'no-forwards',
                  'saved-tags', 'hidden-members', 'bot-commands', 'deep-links',
                  'collectibles', 'round-record']}})


# --- 13. collectible usernames (Fragment-style, off-chain) ---------------------

_COLLECT_RE = re.compile(r'^[A-Za-z0-9_]{3,32}$')


def _collectible_name_ok(name):
    if not name or not _COLLECT_RE.match(name):
        return 'Username must be 3-32 characters (letters, numbers, underscores)'
    if User.query.filter(User.username.ilike(name)).first():
        return 'Name is taken by a user'
    if TgCollectible.query.filter(TgCollectible.username.ilike(name)).first():
        return 'Name is already a collectible'
    return None


@spav2_telegram_bp.route('/tg/collectibles/claim', methods=['POST'])
def tg_collect_claim():
    uid, err = _auth()
    if err:
        return err
    name = ((request.get_json() or {}).get('username') or '').strip()
    bad = _collectible_name_ok(name)
    if bad:
        return jsonify({'success': False, 'error': bad}), 400
    db.session.add(TgCollectible(username=name, owner_id=uid))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Name just got taken'}), 409
    return jsonify({'success': True, 'data': {'username': name}}), 201


@spav2_telegram_bp.route('/tg/collectibles/mine', methods=['GET'])
def tg_collect_mine():
    uid, err = _auth()
    if err:
        return err
    rows = TgCollectible.query.filter_by(owner_id=uid).order_by(TgCollectible.username.asc()).all()
    me = User.query.get(uid)
    return jsonify({'success': True, 'data': {
        'wearing': me.username if me else None,
        'collectibles': [{'username': r.username, 'for_sale': r.for_sale,
                          'price': r.price, 'last_sale_price': r.last_sale_price} for r in rows]}})


@spav2_telegram_bp.route('/tg/collectibles/showcase', methods=['GET'])
def tg_collect_showcase():
    rows = TgCollectible.query.filter_by(for_sale=True).order_by(
        TgCollectible.price.asc()).limit(50).all()
    out = []
    for r in rows:
        o = User.query.get(r.owner_id)
        out.append({'username': r.username, 'price': r.price,
                    'owner': o.username if o else None})
    return jsonify({'success': True, 'data': {'for_sale': out}})


def _collect_owned(username, uid):
    row = TgCollectible.query.filter_by(username=username).first()
    if not row:
        return None, (jsonify({'success': False, 'error': 'Collectible not found'}), 404)
    if row.owner_id != uid:
        return None, (jsonify({'success': False, 'error': 'Not your collectible'}), 403)
    return row, None


@spav2_telegram_bp.route('/tg/collectibles/transfer', methods=['POST'])
def tg_collect_transfer():
    uid, err = _auth()
    if err:
        return err
    data = request.get_json() or {}
    row, rerr = _collect_owned((data.get('username') or '').strip(), uid)
    if rerr:
        return rerr
    target = data.get('to_user_id') or data.get('to')
    to_user = None
    try:
        to_user = User.query.get(int(target))
    except (TypeError, ValueError):
        to_user = User.query.filter(User.username.ilike(str(target or '').lstrip('@'))).first()
    if not to_user or to_user.id == uid:
        return jsonify({'success': False, 'error': 'Recipient not found'}), 404
    row.owner_id = to_user.id
    row.for_sale = False
    row.price = None
    db.session.commit()
    return jsonify({'success': True})


@spav2_telegram_bp.route('/tg/collectibles/sell', methods=['POST'])
def tg_collect_sell():
    uid, err = _auth()
    if err:
        return err
    data = request.get_json() or {}
    row, rerr = _collect_owned((data.get('username') or '').strip(), uid)
    if rerr:
        return rerr
    price = data.get('price')
    if price is None:
        row.for_sale = False
        row.price = None
    else:
        try:
            price = int(price)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Bad price'}), 400
        if price <= 0:
            return jsonify({'success': False, 'error': 'Bad price'}), 400
        row.for_sale = True
        row.price = price
    db.session.commit()
    return jsonify({'success': True, 'data': {'for_sale': row.for_sale}})


@spav2_telegram_bp.route('/tg/collectibles/buy', methods=['POST'])
def tg_collect_buy():
    uid, err = _auth()
    if err:
        return err
    name = ((request.get_json() or {}).get('username') or '').strip()
    row = TgCollectible.query.filter_by(username=name, for_sale=True).first()
    if not row or row.owner_id == uid:
        return jsonify({'success': False, 'error': 'Not for sale'}), 404
    # NOTE: on-platform Stars settlement is not implemented; the transfer is
    # the primitive (price recorded as last sale price for the showcase).
    row.last_sale_price = row.price
    row.owner_id = uid
    row.for_sale = False
    row.price = None
    db.session.commit()
    return jsonify({'success': True, 'data': {'username': name}})


@spav2_telegram_bp.route('/tg/collectibles/wear', methods=['POST'])
def tg_collect_wear():
    uid, err = _auth()
    if err:
        return err
    name = ((request.get_json() or {}).get('username') or '').strip()
    row, rerr = _collect_owned(name, uid)
    if rerr:
        return rerr
    me = User.query.get(uid)
    old = me.username
    if TgCollectible.query.filter(TgCollectible.username.ilike(old)).first():
        return jsonify({'success': False, 'error': 'Current name is reserved'}), 409
    db.session.add(TgCollectible(username=old, owner_id=uid))
    db.session.delete(row)
    me.username = name
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Name just got taken'}), 409
    return jsonify({'success': True, 'data': {'username': name}})


# --- 14. video-circle recording upload --------------------------------------------

@spav2_telegram_bp.route('/tg/round/upload', methods=['POST'])
def tg_round_upload():
    import os as _os
    import uuid as _uuid
    uid, err = _auth()
    if err:
        return err
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file provided'}), 400
    f = request.files['file']
    ext = (f.filename.rsplit('.', 1)[1].lower() if '.' in (f.filename or '') else '')
    if ext not in ('mp4', 'webm'):
        return jsonify({'success': False, 'error': 'Only mp4/webm video'}), 400
    try:
        from app.routes.files import get_uploads_dir
        target_dir = _os.path.join(get_uploads_dir(), 'circles')
        _os.makedirs(target_dir, exist_ok=True)
        name = f'round_{_uuid.uuid4().hex}.{ext}'
        dest = _os.path.join(target_dir, name)
        if not _os.path.normpath(dest).startswith(_os.path.normpath(target_dir) + _os.sep):
            return jsonify({'success': False, 'error': 'Invalid path'}), 400
        f.save(dest)
        if _os.path.getsize(dest) > 15 * 1024 * 1024:
            _os.remove(dest)
            return jsonify({'success': False, 'error': 'Max 15MB'}), 400
    except Exception:
        return jsonify({'success': False, 'error': 'Upload failed'}), 500
    return jsonify({'success': True, 'data': {'file_path': f'circles/{name}'}})
