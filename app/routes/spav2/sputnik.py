# app/routes/spav2/sputnik.py
"""Sputnik ideas pack — ported from https://github.com/ilyyagoncharow12/sputnik.

Covers the Sputnik ideas missing in Kiselgram (which already had polls,
scheduled messages, pins, typing, markdown, premium promos, story
reply/stats, mute/archive):
  1. message edit history (was -> now)
  2. message-level trash with restore/clear
  3. SSRF-safe link preview
  4. albums (gallery message groups) + reorder
  5. video circles ("round" file_type, <=60s) + deduped views
  6. custom stickers (upload/favorite/from_message/send)
  7. chat folders keyed by (chat_type, chat_id)
  8. user cloud password (2FA) + app-lock PIN (bcrypt)
  9. contact import (.vcf text / manual list)
  10. multi-account linking/switch list
  11. db health + orphan cleanup (admin)
  12. deduped per-user message views (one view per user)
  13. scheduled list/send-now/delete reusing Message.scheduled_at
"""

from __future__ import annotations

import html
import ipaddress
import re
import secrets
import socket
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from app import db
from app.models import (
    Chat,
    ChatMember,
    ChatSubscriber,
    Contact,
    Message,
    Poll,
    PollVote,
    SputnikAlbum,
    SputnikDraft,
    SputnikFolder,
    SputnikFolderChat,
    SputnikGroupRestrict,
    SputnikJoinRequest,
    SputnikMemberPerm,
    SputnikMessageEdit,
    SputnikMessageView,
    SputnikSecret,
    SputnikSticker,
    SputnikTrash,
    Story,
    User,
)
from app.utils.helpers import get_current_user_id
from app.utils.security import account_locked, note_account_failure, clear_account_failures

spav2_sputnik_bp = Blueprint('spav2_sputnik', __name__, url_prefix='/api')

# Public invite landing pages (Sputnik /join/<link>, /c/<link> showcase idea).
# No url prefix — mounted at site root, registered in app/__init__.py.
sputnik_pages_bp = Blueprint('sputnik_pages', __name__)


@sputnik_pages_bp.route('/join/<code>')
def sputnik_join_group_page(code):
    from flask import render_template
    chat = Chat.query.filter_by(chat_type='group', invite_link=code).first()
    if not chat:
        return render_template('errors/404.html'), 404
    n = ChatMember.query.filter_by(chat_id=chat.id).count()
    return render_template('sputnik_join.html', chat=chat, members=n, code=code)


@sputnik_pages_bp.route('/c/<code>')
def sputnik_join_channel_page(code):
    from flask import render_template
    chat = Chat.query.filter_by(chat_type='channel', invite_link=code).first()
    if not chat:
        return render_template('errors/404.html'), 404
    n = ChatSubscriber.query.filter_by(chat_id=chat.id).count()
    return render_template('sputnik_join.html', chat=chat, members=n, code=code)

_ROUND_MAX_SECONDS = 60
_URL_RE = re.compile(r'^https?://', re.IGNORECASE)


def _auth():
    uid = get_current_user_id()
    if not uid:
        return None, (jsonify({'success': False, 'error': 'Not authenticated'}), 401)
    return uid, None


def _is_admin(uid: int) -> bool:
    u = User.query.get(uid)
    return bool(u and u.is_admin)


@spav2_sputnik_bp.route('/sputnik/messages/<int:message_id>/edit', methods=['POST'])
def sputnik_edit_message(message_id):
    uid, err = _auth()
    if err:
        return err
    msg = Message.query.get(message_id)
    if not msg:
        return jsonify({'success': False, 'error': 'Message not found'}), 404
    if msg.sender_id != uid:
        return jsonify({'success': False, 'error': 'You can only edit your own messages'}), 403
    data = request.get_json() or {}
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({'success': False, 'error': 'Content cannot be empty'}), 400
    old = msg.content
    if old == content:
        return jsonify({'success': True, 'data': {'message_id': msg.id, 'unchanged': True}})
    db.session.add(SputnikMessageEdit(message_id=msg.id, editor_id=uid, old_text=old, new_text=content))
    msg.content = content
    msg.edited_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({'success': True, 'data': {'message_id': msg.id}})


@spav2_sputnik_bp.route('/sputnik/messages/<int:message_id>/edits', methods=['GET'])
def sputnik_message_edits(message_id):
    uid, err = _auth()
    if err:
        return err
    edits = (
        SputnikMessageEdit.query.filter_by(message_id=message_id)
        .order_by(SputnikMessageEdit.created_at.asc()).all()
    )
    return jsonify({'success': True, 'data': {'edits': [
        {'id': e.id, 'editor_id': e.editor_id, 'old_text': e.old_text,
         'new_text': e.new_text, 'created_at': e.created_at.isoformat() if e.created_at else None}
        for e in edits
    ]}})


@spav2_sputnik_bp.route('/sputnik/trash', methods=['GET'])
def sputnik_trash_list():
    uid, err = _auth()
    if err:
        return err
    items = SputnikTrash.query.filter_by(owner_id=uid).order_by(SputnikTrash.created_at.desc()).all()
    return jsonify({'success': True, 'data': {'trash': [
        {'message_id': t.message_id, 'snapshot': t.snapshot,
         'deleted_at': t.created_at.isoformat() if t.created_at else None} for t in items
    ]}})


@spav2_sputnik_bp.route('/sputnik/trash/restore', methods=['POST'])
def sputnik_trash_restore():
    uid, err = _auth()
    if err:
        return err
    data = request.get_json() or {}
    mid = data.get('message_id')
    entry = SputnikTrash.query.filter_by(message_id=mid, owner_id=uid).first()
    if not entry:
        return jsonify({'success': False, 'error': 'Trash entry not found'}), 404
    msg = Message.query.get(mid)
    if msg and msg.sender_id == uid:
        msg.is_deleted = False
        msg.deleted_at = None
    db.session.delete(entry)
    db.session.commit()
    return jsonify({'success': True, 'data': {'message_id': mid}})


@spav2_sputnik_bp.route('/sputnik/trash/clear', methods=['POST'])
def sputnik_trash_clear():
    uid, err = _auth()
    if err:
        return err
    SputnikTrash.query.filter_by(owner_id=uid).delete()
    db.session.commit()
    return jsonify({'success': True})


@spav2_sputnik_bp.route('/sputnik/messages/<int:message_id>/trash', methods=['POST'])
def sputnik_move_to_trash(message_id):
    uid, err = _auth()
    if err:
        return err
    msg = Message.query.get(message_id)
    if not msg:
        return jsonify({'success': False, 'error': 'Message not found'}), 404
    if msg.sender_id != uid:
        return jsonify({'success': False, 'error': 'You can only trash your own messages'}), 403
    msg.is_deleted = True
    msg.deleted_at = datetime.now(timezone.utc)
    snap = (msg.content or '')[:2000]
    if not SputnikTrash.query.filter_by(message_id=msg.id, owner_id=uid).first():
        db.session.add(SputnikTrash(message_id=msg.id, owner_id=uid, snapshot=snap))
    db.session.commit()
    return jsonify({'success': True, 'data': {'message_id': msg.id}})


def _preview_fetch(url: str) -> dict:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError('Only http(s) URLs allowed')
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise ValueError('DNS failed') from exc
    for info in infos:
        try:
            if ipaddress.ip_address(info[4][0]).is_private:
                raise ValueError('Private hosts blocked')
        except ValueError:
            raise
        except Exception:
            continue
    req = urllib.request.Request(url, headers={'User-Agent': 'KiselgramBot/1.0'}, method='GET')
    with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310 - host allowlisted above
        ctype = resp.headers.get('Content-Type', '')
        if 'text/html' not in ctype:
            return {'url': url, 'content_type': ctype}
        raw = resp.read(65536).decode('utf-8', 'ignore')
    title = re.search(r'<title[^>]*>(.*?)</title>', raw, re.I | re.S)
    desc = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', raw, re.I | re.S)
    return {
        'url': url,
        'title': html.unescape(title.group(1).strip())[:300] if title else '',
        'description': html.unescape(desc.group(1).strip())[:500] if desc else '',
    }


@spav2_sputnik_bp.route('/sputnik/link_preview', methods=['GET'])
def sputnik_link_preview():
    uid, err = _auth()
    if err:
        return err
    url = (request.args.get('url') or '').strip()
    if not url or not _URL_RE.match(url):
        return jsonify({'success': False, 'error': 'Valid http(s) url required'}), 400
    try:
        return jsonify({'success': True, 'data': _preview_fetch(url)})
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    except Exception:
        return jsonify({'success': False, 'error': 'Preview fetch failed'}), 502


@spav2_sputnik_bp.route('/sputnik/albums/create', methods=['POST'])
def sputnik_album_create():
    uid, err = _auth()
    if err:
        return err
    data = request.get_json() or {}
    ids = data.get('message_ids') or []
    if not (2 <= len(ids) <= 10):
        return jsonify({'success': False, 'error': 'Album needs 2-10 messages'}), 400
    msgs = Message.query.filter(Message.id.in_(ids), Message.sender_id == uid).all()
    if len(msgs) != len(ids):
        return jsonify({'success': False, 'error': 'Messages must be yours'}), 403
    album_uid = secrets.token_hex(8)
    for pos, mid in enumerate(ids):
        db.session.add(SputnikAlbum(album_uid=album_uid, owner_id=uid, message_id=mid, position=pos))
    db.session.commit()
    return jsonify({'success': True, 'data': {'album_id': album_uid}})


@spav2_sputnik_bp.route('/sputnik/albums/<album_id>', methods=['GET'])
def sputnik_album_get(album_id):
    uid, err = _auth()
    if err:
        return err
    rows = SputnikAlbum.query.filter_by(album_uid=album_id).order_by(SputnikAlbum.position.asc()).all()
    if not rows:
        return jsonify({'success': False, 'error': 'Album not found'}), 404
    return jsonify({'success': True, 'data': {'album_id': album_id, 'message_ids': [r.message_id for r in rows]}})


@spav2_sputnik_bp.route('/sputnik/albums/<album_id>/reorder', methods=['POST'])
def sputnik_album_reorder(album_id):
    uid, err = _auth()
    if err:
        return err
    data = request.get_json() or {}
    ids = data.get('message_ids') or []
    rows = SputnikAlbum.query.filter_by(album_uid=album_id, owner_id=uid).all()
    if not rows or {r.message_id for r in rows} != set(ids):
        return jsonify({'success': False, 'error': 'Album mismatch'}), 400
    order = {mid: pos for pos, mid in enumerate(ids)}
    for r in rows:
        r.position = order[r.message_id]
    db.session.commit()
    return jsonify({'success': True, 'data': {'album_id': album_id}})


def _resolve_chat_id(uid, data):
    """Resolve a Message.chat_id from flexible frontend refs.

    Accepts chat_id directly, or (chat_type + peer_id) where personal chats
    carry the peer user id (as K.state.activeChat does) and groups/channels
    carry the chats-table id. Personal chats are found or created, mirroring
    the convention in files.upload_file (plus ChatMember participants).
    Returns (chat_id, receiver_id, error_response); receiver_id is set for
    personal chats so conversation lists pick the message up.
    """
    if data.get('chat_id'):
        try:
            cid = int(data['chat_id'])
        except (TypeError, ValueError):
            return None, None, (jsonify({'success': False, 'error': 'Bad chat_id'}), 400)
        from app.routes.spav2.features import _chat_access
        if not _chat_access(uid, cid):
            return None, None, (jsonify({'success': False, 'error': 'You are not in this chat'}), 403)
        return cid, None, None
    ctype = (data.get('chat_type') or '')[:20]
    try:
        peer = int(data.get('peer_id'))
    except (TypeError, ValueError):
        return None, None, (jsonify({'success': False, 'error': 'chat_id or peer_id required'}), 400)
    if ctype == 'personal':
        other = User.query.get(peer)
        if not other:
            return None, None, (jsonify({'success': False, 'error': 'Peer not found'}), 404)
        a, b = sorted([uid, peer])
        chat = Chat.query.filter_by(chat_type='personal', user1_id=a, user2_id=b).first()
        if not chat:
            chat = Chat(chat_type='personal', user1_id=a, user2_id=b)
            db.session.add(chat)
            db.session.flush()
            for member_id in (a, b):
                if not ChatMember.query.filter_by(chat_id=chat.id, user_id=member_id).first():
                    db.session.add(ChatMember(chat_id=chat.id, user_id=member_id, role='participant'))
        return chat.id, peer, None
    if ctype in ('group', 'channel'):
        from app.routes.spav2.features import _chat_access
        if not _chat_access(uid, peer):
            return None, None, (jsonify({'success': False, 'error': 'You are not in this chat'}), 403)
        return peer, None, None
    return None, None, (jsonify({'success': False, 'error': 'Unknown chat_type'}), 400)


@spav2_sputnik_bp.route('/sputnik/albums/lookup', methods=['POST'])
def sputnik_album_lookup():
    """Bulk lookup: message_id -> album membership (for grid rendering)."""
    uid, err = _auth()
    if err:
        return err
    ids = (request.get_json() or {}).get('message_ids') or []
    rows = SputnikAlbum.query.filter(SputnikAlbum.message_id.in_(ids[:200])).all()
    by_msg = {}
    by_album: dict[str, list] = {}
    for r in rows:
        by_album.setdefault(r.album_uid, []).append(r)
    for album_uid, items in by_album.items():
        items.sort(key=lambda r: r.position)
        for r in items:
            by_msg[r.message_id] = {'album_id': album_uid, 'position': r.position,
                                     'members': [i.message_id for i in items]}
    return jsonify({'success': True, 'data': {'albums': by_msg}})


@spav2_sputnik_bp.route('/sputnik/round/send', methods=['POST'])
def sputnik_round_send():
    uid, err = _auth()
    if err:
        return err
    data = request.get_json() or {}
    chat_id, receiver_id, cerr = _resolve_chat_id(uid, data)
    if cerr:
        return cerr
    file_path = (data.get('file_path') or '').strip()
    duration = int(data.get('duration') or 0)
    if not file_path:
        return jsonify({'success': False, 'error': 'file_path required'}), 400
    if duration < 1 or duration > _ROUND_MAX_SECONDS:
        return jsonify({'success': False, 'error': 'Circle must be 1-60 seconds'}), 400
    if '..' in file_path or file_path.startswith('/'):
        return jsonify({'success': False, 'error': 'Invalid file path'}), 400
    msg = Message(sender_id=uid, chat_id=chat_id, receiver_id=receiver_id or uid,
                  content=data.get('caption') or '',
                  file_type='round', file_path=file_path)
    db.session.add(msg)
    db.session.commit()
    return jsonify({'success': True, 'data': {'message_id': msg.id}})


@spav2_sputnik_bp.route('/sputnik/messages/<int:message_id>/view', methods=['POST'])
def sputnik_message_view(message_id):
    uid, err = _auth()
    if err:
        return err
    msg = Message.query.get(message_id)
    if not msg:
        return jsonify({'success': False, 'error': 'Message not found'}), 404
    if not SputnikMessageView.query.filter_by(message_id=message_id, user_id=uid).first():
        db.session.add(SputnikMessageView(message_id=message_id, user_id=uid))
        db.session.commit()
    count = SputnikMessageView.query.filter_by(message_id=message_id).count()
    return jsonify({'success': True, 'data': {'message_id': message_id, 'views': count}})


@spav2_sputnik_bp.route('/sputnik/stickers', methods=['GET'])
def sputnik_stickers_list():
    uid, err = _auth()
    if err:
        return err
    fav = request.args.get('favorite')
    q = SputnikSticker.query.filter_by(owner_id=uid)
    if fav == '1':
        q = q.filter_by(is_favorite=True)
    rows = q.order_by(SputnikSticker.created_at.desc()).limit(200).all()
    return jsonify({'success': True, 'data': {'stickers': [
        {'id': s.id, 'file_path': s.file_path, 'emoji': s.emoji, 'is_favorite': s.is_favorite} for s in rows
    ]}})


@spav2_sputnik_bp.route('/sputnik/stickers/upload', methods=['POST'])
def sputnik_sticker_upload():
    uid, err = _auth()
    if err:
        return err
    data = request.get_json() or {}
    file_path = (data.get('file_path') or '').strip()
    if not file_path or '..' in file_path or file_path.startswith('/'):
        return jsonify({'success': False, 'error': 'Valid file_path required'}), 400
    s = SputnikSticker(owner_id=uid, file_path=file_path, emoji=(data.get('emoji') or '')[:16])
    db.session.add(s)
    db.session.commit()
    return jsonify({'success': True, 'data': {'sticker_id': s.id}})


@spav2_sputnik_bp.route('/sputnik/stickers/<int:sid>/favorite', methods=['POST'])
def sputnik_sticker_fav(sid):
    uid, err = _auth()
    if err:
        return err
    s = SputnikSticker.query.filter_by(id=sid, owner_id=uid).first()
    if not s:
        return jsonify({'success': False, 'error': 'Sticker not found'}), 404
    data = request.get_json() or {}
    s.is_favorite = bool(data.get('favorite', not s.is_favorite))
    db.session.commit()
    return jsonify({'success': True, 'data': {'sticker_id': s.id, 'is_favorite': s.is_favorite}})


@spav2_sputnik_bp.route('/sputnik/stickers/from_message', methods=['POST'])
def sputnik_sticker_from_message():
    uid, err = _auth()
    if err:
        return err
    data = request.get_json() or {}
    msg = Message.query.get(data.get('message_id'))
    if not msg or not msg.file_path:
        return jsonify({'success': False, 'error': 'Message has no image'}), 400
    s = SputnikSticker(owner_id=uid, file_path=msg.file_path, emoji=(data.get('emoji') or '')[:16])
    db.session.add(s)
    db.session.commit()
    return jsonify({'success': True, 'data': {'sticker_id': s.id}})


@spav2_sputnik_bp.route('/sputnik/stickers/send', methods=['POST'])
def sputnik_sticker_send():
    uid, err = _auth()
    if err:
        return err
    data = request.get_json() or {}
    s = SputnikSticker.query.filter_by(id=data.get('sticker_id'), owner_id=uid).first()
    if not s:
        return jsonify({'success': False, 'error': 'Sticker not found'}), 404
    chat_id, receiver_id, cerr = _resolve_chat_id(uid, data)
    if cerr:
        return cerr
    msg = Message(sender_id=uid, chat_id=chat_id, receiver_id=receiver_id or uid, content='',
                  file_type='sticker', file_path=s.file_path, emoji=s.emoji)
    db.session.add(msg)
    db.session.commit()
    return jsonify({'success': True, 'data': {'message_id': msg.id}})


@spav2_sputnik_bp.route('/sputnik/folders', methods=['GET'])
def sputnik_folders_list():
    uid, err = _auth()
    if err:
        return err
    folders = SputnikFolder.query.filter_by(user_id=uid).order_by(SputnikFolder.sort_order.asc()).all()
    out = []
    for f in folders:
        chats = SputnikFolderChat.query.filter_by(folder_id=f.id).all()
        out.append({'id': f.id, 'name': f.name,
                    'chats': [{'chat_type': c.chat_type, 'chat_id': c.chat_id} for c in chats]})
    return jsonify({'success': True, 'data': {'folders': out}})


@spav2_sputnik_bp.route('/sputnik/folders/create', methods=['POST'])
def sputnik_folder_create():
    uid, err = _auth()
    if err:
        return err
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name or len(name) > 80:
        return jsonify({'success': False, 'error': 'Folder name required (<=80)'}), 400
    f = SputnikFolder(user_id=uid, name=name)
    db.session.add(f)
    db.session.commit()
    return jsonify({'success': True, 'data': {'folder_id': f.id}})


@spav2_sputnik_bp.route('/sputnik/folders/<int:folder_id>/chats', methods=['POST'])
def sputnik_folder_set_chats(folder_id):
    uid, err = _auth()
    if err:
        return err
    f = SputnikFolder.query.filter_by(id=folder_id, user_id=uid).first()
    if not f:
        return jsonify({'success': False, 'error': 'Folder not found'}), 404
    data = request.get_json() or {}
    chats = data.get('chats') or []
    SputnikFolderChat.query.filter_by(folder_id=f.id).delete()
    for c in chats[:200]:
        ctype = (c.get('chat_type') or 'personal')[:20]
        try:
            cid = int(c.get('chat_id'))
        except (TypeError, ValueError):
            continue
        db.session.add(SputnikFolderChat(folder_id=f.id, chat_type=ctype, chat_id=cid))
    db.session.commit()
    return jsonify({'success': True, 'data': {'folder_id': f.id, 'count': len(chats)}})


@spav2_sputnik_bp.route('/sputnik/folders/<int:folder_id>', methods=['DELETE'])
def sputnik_folder_delete(folder_id):
    uid, err = _auth()
    if err:
        return err
    f = SputnikFolder.query.filter_by(id=folder_id, user_id=uid).first()
    if not f:
        return jsonify({'success': False, 'error': 'Folder not found'}), 404
    SputnikFolderChat.query.filter_by(folder_id=f.id).delete()
    db.session.delete(f)
    db.session.commit()
    return jsonify({'success': True})


@spav2_sputnik_bp.route('/sputnik/cloud/setup', methods=['POST'])
def sputnik_cloud_setup():
    uid, err = _auth()
    if err:
        return err
    data = request.get_json() or {}
    secret = data.get('password') or ''
    if len(secret) < 4:
        return jsonify({'success': False, 'error': 'Password too short'}), 400
    row = SputnikSecret.query.filter_by(user_id=uid, kind='cloud').first()
    if not row:
        row = SputnikSecret(user_id=uid, kind='cloud', secret_hash='')
        db.session.add(row)
    row.secret_hash = generate_password_hash(secret)
    row.hint = (data.get('hint') or '')[:255]
    row.email = (data.get('email') or '')[:255]
    db.session.commit()
    return jsonify({'success': True})


@spav2_sputnik_bp.route('/sputnik/cloud/verify', methods=['POST'])
def sputnik_cloud_verify():
    uid, err = _auth()
    if err:
        return err
    data = request.get_json() or {}
    key = f'cloud:{uid}'
    if account_locked(key):
        return jsonify({'success': False, 'error': 'Too many attempts. Try again in 5 minutes.'}), 429
    row = SputnikSecret.query.filter_by(user_id=uid, kind='cloud').first()
    if not row or not check_password_hash(row.secret_hash, data.get('password') or ''):
        note_account_failure(key)
        return jsonify({'success': False, 'error': 'Invalid password'}), 403
    clear_account_failures(key)
    return jsonify({'success': True})


@spav2_sputnik_bp.route('/sputnik/applock/set', methods=['POST'])
def sputnik_applock_set():
    uid, err = _auth()
    if err:
        return err
    data = request.get_json() or {}
    pin = (data.get('pin') or '').strip()
    if not re.fullmatch(r'\d{4,12}', pin):
        return jsonify({'success': False, 'error': 'PIN must be 4-12 digits'}), 400
    row = SputnikSecret.query.filter_by(user_id=uid, kind='applock').first()
    if not row:
        row = SputnikSecret(user_id=uid, kind='applock', secret_hash='')
        db.session.add(row)
    row.secret_hash = generate_password_hash(pin)
    row.hint = (data.get('hint') or '')[:255]
    db.session.commit()
    return jsonify({'success': True})


@spav2_sputnik_bp.route('/sputnik/applock/verify', methods=['POST'])
def sputnik_applock_verify():
    uid, err = _auth()
    if err:
        return err
    data = request.get_json() or {}
    key = f'applock:{uid}'
    if account_locked(key):
        return jsonify({'success': False, 'error': 'Too many attempts. Try again in 5 minutes.'}), 429
    row = SputnikSecret.query.filter_by(user_id=uid, kind='applock').first()
    if not row or not check_password_hash(row.secret_hash, data.get('pin') or ''):
        note_account_failure(key)
        return jsonify({'success': False, 'error': 'Invalid PIN'}), 403
    clear_account_failures(key)
    return jsonify({'success': True})


@spav2_sputnik_bp.route('/sputnik/secrets/off', methods=['POST'])
def sputnik_secret_off():
    uid, err = _auth()
    if err:
        return err
    kind = (request.get_json() or {}).get('kind') or 'applock'
    if kind not in ('cloud', 'applock'):
        return jsonify({'success': False, 'error': 'Unknown kind'}), 400
    SputnikSecret.query.filter_by(user_id=uid, kind=kind).delete()
    db.session.commit()
    return jsonify({'success': True})


_VCF_TEL = re.compile(r'TEL[^:]*:(.+)', re.IGNORECASE)


@spav2_sputnik_bp.route('/sputnik/contacts/import', methods=['POST'])
def sputnik_contacts_import():
    uid, err = _auth()
    if err:
        return err
    data = request.get_json() or {}
    # Kiselgram User has no phone field, so import matches by username / user_id.
    # .vcf FN lines and explicit usernames/user_ids are supported; raw phones
    # are reported back as unmatched (Sputnik accepts .vcf / phone / manual).
    candidates: list[str] = []
    vcf = data.get('vcf') or ''
    for line in vcf.splitlines():
        s = line.strip()
        m = _VCF_TEL.search(s)
        if m:
            candidates.append(re.sub(r'[^\d+]', '', m.group(1).strip()))
        fn = re.match(r'FN:(.+)', s, re.IGNORECASE)
        if fn:
            candidates.append(fn.group(1).strip())
    for item in data.get('usernames') or []:
        candidates.append(str(item).strip().lstrip('@'))
    target_ids = set()
    for item in data.get('user_ids') or []:
        try:
            target_ids.add(int(item))
        except (TypeError, ValueError):
            continue
    for name in {c for c in candidates if c}:
        u = User.query.filter(User.username.ilike(name)).first()
        if u:
            target_ids.add(u.id)
    matched = []
    added = 0
    for target_id in target_ids:
        if target_id == uid:
            continue
        user = User.query.get(target_id)
        if user is None:
            continue
        matched.append({'user_id': user.id, 'username': user.username})
        if not Contact.query.filter_by(user_id=uid, contact_id=user.id).first():
            try:
                db.session.add(Contact(user_id=uid, contact_id=user.id))
                added += 1
            except Exception:
                db.session.rollback()
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
    return jsonify({'success': True, 'data': {'found': matched, 'added': added}})


@spav2_sputnik_bp.route('/sputnik/db/health', methods=['GET'])
def sputnik_db_health():
    uid, err = _auth()
    if err:
        return err
    if not _is_admin(uid):
        return jsonify({'success': False, 'error': 'Admin only'}), 403
    counts = {
        'edits': SputnikMessageEdit.query.count(),
        'trash': SputnikTrash.query.count(),
        'folders': SputnikFolder.query.count(),
        'stickers': SputnikSticker.query.count(),
        'albums': SputnikAlbum.query.count(),
        'views': SputnikMessageView.query.count(),
    }
    return jsonify({'success': True, 'data': counts})


@spav2_sputnik_bp.route('/sputnik/db/cleanup_orphans', methods=['POST'])
def sputnik_cleanup_orphans():
    uid, err = _auth()
    if err:
        return err
    if not _is_admin(uid):
        return jsonify({'success': False, 'error': 'Admin only'}), 403
    mids = [m.id for m in Message.query.with_entities(Message.id).all()]
    removed = 0
    for model in (SputnikMessageEdit, SputnikAlbum, SputnikMessageView):
        orphans = model.query.filter(~model.message_id.in_(mids)).all() if mids else model.query.all()
        for o in orphans:
            db.session.delete(o)
            removed += 1
    trash_orphans = SputnikTrash.query.filter(~SputnikTrash.message_id.in_(mids)).all() if mids else []
    for o in trash_orphans:
        db.session.delete(o)
        removed += 1
    db.session.commit()
    return jsonify({'success': True, 'data': {'removed': removed}})


@spav2_sputnik_bp.route('/sputnik/scheduled', methods=['GET'])
def sputnik_scheduled_list():
    uid, err = _auth()
    if err:
        return err
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    msgs = Message.query.filter(Message.sender_id == uid, Message.scheduled_at.isnot(None),
                                Message.scheduled_at > now).order_by(Message.scheduled_at.asc()).all()
    return jsonify({'success': True, 'data': {'scheduled': [
        {'message_id': m.id, 'chat_id': m.chat_id, 'content': m.content,
         'send_at': m.scheduled_at.isoformat() if m.scheduled_at else None} for m in msgs
    ]}})


@spav2_sputnik_bp.route('/sputnik/scheduled/<int:message_id>/send_now', methods=['POST'])
def sputnik_scheduled_send_now(message_id):
    uid, err = _auth()
    if err:
        return err
    m = Message.query.filter_by(id=message_id, sender_id=uid).first()
    if not m:
        return jsonify({'success': False, 'error': 'Message not found'}), 404
    m.scheduled_at = None
    db.session.commit()
    return jsonify({'success': True, 'data': {'message_id': m.id}})


@spav2_sputnik_bp.route('/sputnik/scheduled/<int:message_id>', methods=['DELETE'])
def sputnik_scheduled_delete(message_id):
    uid, err = _auth()
    if err:
        return err
    m = Message.query.filter_by(id=message_id, sender_id=uid).first()
    if not m:
        return jsonify({'success': False, 'error': 'Message not found'}), 404
    db.session.delete(m)
    db.session.commit()
    return jsonify({'success': True})


@spav2_sputnik_bp.route('/sputnik/features', methods=['GET'])
def sputnik_features():
    return jsonify({'success': True, 'data': {'source': 'https://github.com/ilyyagoncharow12/sputnik',
        'ideas': ['edit-history', 'trash', 'link-preview', 'albums', 'video-circles',
                  'stickers', 'folders', 'cloud-2fa', 'app-lock', 'contact-import',
                  'db-health', 'dedup-views', 'scheduled-list',
                  'poll-close-results', 'drafts', 'banner', 'profile-media', 'discover',
                  'join-requests', 'member-perms', 'group-restrict', 'story-share-replace',
                  'data-export', 'db-backup', 'cloud-recover', 'invite-pages', 'system-notify',
                  'sticker-upload', 'account-lockout', 'presence-privacy', 'pin-access']}})


def _notify_via_system(user_id, text):
    """Sputnik-style system notification via the kiselgram bot chat.

    Reuses the existing system-chat convention from login_v3
    (_send_otp_via_chat): a personal chat with the 'kiselgram' bot user.
    Best-effort: silently skips if the system user does not exist yet.
    """
    try:
        kg = User.query.filter_by(username='kiselgram', is_deleted=False).first()
        if not kg:
            return False
        chat = Chat.query.filter(
            ((Chat.user1_id == kg.id) & (Chat.user2_id == user_id)) |
            ((Chat.user1_id == user_id) & (Chat.user2_id == kg.id))).first()
        if not chat:
            chat = Chat(user1_id=min(kg.id, user_id), user2_id=max(kg.id, user_id),
                        chat_type='personal')
            db.session.add(chat)
            db.session.flush()
        db.session.add(Message(sender_id=kg.id, receiver_id=user_id, chat_id=chat.id,
                               content=text,
                               timestamp=datetime.now(timezone.utc).replace(tzinfo=None)))
        db.session.commit()
        return True
    except Exception:
        db.session.rollback()
        return False


# --- wave 3: db backup (admin, sqlite file) ----------------------------------

@spav2_sputnik_bp.route('/sputnik/db/backup', methods=['GET'])
def sputnik_db_backup():
    from flask import current_app, send_file as _send_file
    uid, err = _auth()
    if err:
        return err
    if not _is_admin(uid):
        return jsonify({'success': False, 'error': 'Admin only'}), 403
    url = str(db.engine.url)
    if not url.startswith('sqlite:///'):
        return jsonify({'success': False, 'error': 'Backup supports sqlite only'}), 400
    import os as _os
    path = url[len('sqlite:///'):]
    if not _os.path.isfile(path):
        return jsonify({'success': False, 'error': 'Database file not found'}), 404
    return _send_file(path, as_attachment=True, download_name='kiselgram-backup.db')


# --- wave 3: cloud password recovery via email (must be logged in) -----------

@spav2_sputnik_bp.route('/sputnik/cloud/recover', methods=['POST'])
def sputnik_cloud_recover():
    uid, err = _auth()
    if err:
        return err
    data = request.get_json() or {}
    email = (data.get('email') or '').strip()[:255]
    new = data.get('new_password') or ''
    if len(new) < 4:
        return jsonify({'success': False, 'error': 'New password too short'}), 400
    row = SputnikSecret.query.filter_by(user_id=uid, kind='cloud').first()
    if not row:
        return jsonify({'success': False, 'error': 'Cloud password not set'}), 404
    u = User.query.get(uid)
    allowed = { (row.email or '').lower(), ((u.email if u else '') or '').lower() } - {''}
    if not email or email.lower() not in allowed:
        note_account_failure(f'cloud-recover:{uid}')
        return jsonify({'success': False, 'error': 'Email does not match'}), 403
    row.secret_hash = generate_password_hash(new)
    db.session.commit()
    clear_account_failures(f'cloud-recover:{uid}')
    return jsonify({'success': True})


# --- wave 3: raw image upload for the sticker editor -------------------------

@spav2_sputnik_bp.route('/sputnik/upload', methods=['POST'])
def sputnik_upload():
    import os as _os
    import uuid as _uuid
    uid, err = _auth()
    if err:
        return err
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file provided'}), 400
    f = request.files['file']
    ext = (f.filename.rsplit('.', 1)[1].lower() if '.' in (f.filename or '') else '')
    if ext not in ('png', 'jpg', 'jpeg', 'webp'):
        return jsonify({'success': False, 'error': 'Only png/jpg/webp images'}), 400
    try:
        from app.routes.files import get_uploads_dir
        target_dir = _os.path.join(get_uploads_dir(), 'stickers')
        _os.makedirs(target_dir, exist_ok=True)
        name = f'sputnik_{_uuid.uuid4().hex}.png'
        dest = _os.path.join(target_dir, name)
        if not _os.path.normpath(dest).startswith(_os.path.normpath(target_dir) + _os.sep):
            return jsonify({'success': False, 'error': 'Invalid path'}), 400
        f.save(dest)
    except Exception:
        return jsonify({'success': False, 'error': 'Upload failed'}), 500
    return jsonify({'success': True, 'data': {'file_path': f'stickers/{name}'}})


# --- wave 2: polls close + results (Sputnik: close_poll, get_poll) ------------

@spav2_sputnik_bp.route('/sputnik/polls/<int:poll_id>/close', methods=['POST'])
def sputnik_poll_close(poll_id):
    uid, err = _auth()
    if err:
        return err
    poll = Poll.query.get(poll_id)
    if not poll:
        return jsonify({'success': False, 'error': 'Poll not found'}), 404
    if poll.creator_id != uid and not _is_admin(uid):
        return jsonify({'success': False, 'error': 'Only the creator can close'}), 403
    poll.closed = True
    db.session.commit()
    return jsonify({'success': True, 'data': {'poll_id': poll.id}})


@spav2_sputnik_bp.route('/sputnik/polls/<int:poll_id>/results', methods=['GET'])
def sputnik_poll_results(poll_id):
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
    total = sum(counts)
    return jsonify({'success': True, 'data': {
        'poll_id': poll.id, 'question': poll.question, 'closed': poll.closed,
        'options': options, 'counts': counts, 'total': total,
    }})


# --- wave 2: drafts (Sputnik drafts.js) ---------------------------------------

@spav2_sputnik_bp.route('/sputnik/drafts', methods=['GET'])
def sputnik_drafts_list():
    uid, err = _auth()
    if err:
        return err
    rows = SputnikDraft.query.filter_by(user_id=uid).order_by(SputnikDraft.updated_at.desc()).all()
    return jsonify({'success': True, 'data': {'drafts': [
        {'chat_type': d.chat_type, 'chat_id': d.chat_id, 'text': d.text} for d in rows
    ]}})


@spav2_sputnik_bp.route('/sputnik/drafts/save', methods=['POST'])
def sputnik_draft_save():
    uid, err = _auth()
    if err:
        return err
    data = request.get_json() or {}
    ctype = (data.get('chat_type') or 'personal')[:20]
    try:
        cid = int(data.get('chat_id'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'chat_id required'}), 400
    text = (data.get('text') or '')[:4000]
    row = SputnikDraft.query.filter_by(user_id=uid, chat_type=ctype, chat_id=cid).first()
    if not text:
        if row:
            db.session.delete(row)
            db.session.commit()
        return jsonify({'success': True, 'data': {'cleared': True}})
    if not row:
        row = SputnikDraft(user_id=uid, chat_type=ctype, chat_id=cid, text=text)
        db.session.add(row)
    else:
        row.text = text
    db.session.commit()
    return jsonify({'success': True})


# --- wave 2: profile banner (stored on User, ex-SputnikProfile) ---------------

@spav2_sputnik_bp.route('/sputnik/profile/banner', methods=['GET'])
def sputnik_banner_get():
    uid, err = _auth()
    if err:
        return err
    try:
        target = int(request.args.get('user_id') or uid)
    except (TypeError, ValueError):
        target = uid
    u = User.query.get(target)
    return jsonify({'success': True, 'data': {
        'banner_color': (u.banner_color if u and u.banner_color else '#2b8d8d'),
        'banner_image': u.banner_image if u else None,
    }})


@spav2_sputnik_bp.route('/sputnik/profile/banner', methods=['POST'])
def sputnik_banner_set():
    uid, err = _auth()
    if err:
        return err
    data = request.get_json() or {}
    color = (data.get('banner_color') or '#2b8d8d')[:20]
    image = (data.get('banner_image') or '')[:500] or None
    if image and ('..' in image or image.startswith('/')):
        return jsonify({'success': False, 'error': 'Invalid image path'}), 400
    u = User.query.get(uid)
    if not u:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    u.banner_color = color
    u.banner_image = image
    db.session.commit()
    return jsonify({'success': True})


# --- wave 2: profile media grid with counters (Sputnik profile media) ---------

_MEDIA_BUCKETS = {'photo': ('photo', 'image', 'sticker'), 'video': ('video', 'round'),
                   'audio': ('audio', 'voice', 'music'), 'file': ('file', 'document')}


@spav2_sputnik_bp.route('/sputnik/users/<int:user_id>/media', methods=['GET'])
def sputnik_profile_media(user_id):
    uid, err = _auth()
    if err:
        return err
    filt = (request.args.get('filter') or 'all')[:10]
    q = Message.query.filter(
        ((Message.sender_id == user_id) | (Message.receiver_id == user_id)),
        Message.file_path.isnot(None), Message.is_deleted.is_(False))
    if filt in _MEDIA_BUCKETS:
        q = q.filter(Message.file_type.in_(_MEDIA_BUCKETS[filt]))
    rows = q.order_by(Message.timestamp.desc()).limit(100).all()
    counts = {}
    for name, types in _MEDIA_BUCKETS.items():
        counts[name] = Message.query.filter(
            ((Message.sender_id == user_id) | (Message.receiver_id == user_id)),
            Message.file_type.in_(types), Message.is_deleted.is_(False)).count()
    return jsonify({'success': True, 'data': {
        'counts': counts,
        'items': [{'message_id': m.id, 'file_type': m.file_type, 'file_path': m.file_path,
                   'timestamp': m.timestamp.isoformat() if m.timestamp else None} for m in rows],
    }})


# --- wave 2: discover public groups/channels (Sputnik showcase) ---------------

@spav2_sputnik_bp.route('/sputnik/discover', methods=['GET'])
def sputnik_discover():
    uid, err = _auth()
    if err:
        return err
    kind = (request.args.get('kind') or 'all')[:10]
    q = Chat.query.filter_by(is_public=True)
    if kind in ('group', 'channel'):
        q = q.filter_by(chat_type=kind)
    else:
        q = q.filter(Chat.chat_type.in_(['group', 'channel']))
    out = []
    for c in q.order_by(Chat.created_at.desc()).limit(50).all():
        if c.chat_type == 'group':
            n = ChatMember.query.filter_by(chat_id=c.id).count()
            mine = ChatMember.query.filter_by(chat_id=c.id, user_id=uid).first() is not None
        else:
            n = ChatSubscriber.query.filter_by(chat_id=c.id).count()
            mine = ChatSubscriber.query.filter_by(chat_id=c.id, user_id=uid).first() is not None
        req = SputnikJoinRequest.query.filter_by(chat_id=c.id, user_id=uid, status='pending').first()
        out.append({'chat_id': c.id, 'chat_type': c.chat_type, 'name': c.name,
                    'description': c.description, 'avatar_url': c.avatar_url,
                    'members': n, 'joined': mine, 'request_pending': req is not None})
    return jsonify({'success': True, 'data': {'chats': out}})


# --- wave 2: private-group join requests (Sputnik approve/reject) -------------

def _group_owner_or_admin(chat_id, uid):
    chat = Chat.query.get(chat_id)
    if not chat or chat.chat_type != 'group':
        return None
    if chat.owner_id == uid or _is_admin(uid):
        return chat
    m = ChatMember.query.filter_by(chat_id=chat_id, user_id=uid).first()
    if m and m.role in ('owner', 'admin'):
        return chat
    return None


@spav2_sputnik_bp.route('/sputnik/groups/<int:chat_id>/join', methods=['POST'])
def sputnik_join_direct(chat_id):
    """Sputnik showcase: public groups join instantly, private ones file a request."""
    uid, err = _auth()
    if err:
        return err
    chat = Chat.query.get(chat_id)
    if not chat or chat.chat_type != 'group':
        return jsonify({'success': False, 'error': 'Group not found'}), 404
    if ChatMember.query.filter_by(chat_id=chat_id, user_id=uid).first():
        return jsonify({'success': True, 'data': {'already_member': True}})
    if chat.is_public:
        db.session.add(ChatMember(chat_id=chat_id, user_id=uid, role='member'))
        db.session.commit()
        return jsonify({'success': True, 'data': {'joined': True}})
    row = SputnikJoinRequest.query.filter_by(chat_id=chat_id, user_id=uid).first()
    if not row:
        row = SputnikJoinRequest(chat_id=chat_id, user_id=uid, status='pending')
        db.session.add(row)
    else:
        row.status = 'pending'
    db.session.commit()
    return jsonify({'success': True, 'data': {'requested': True}})


@spav2_sputnik_bp.route('/sputnik/groups/<int:chat_id>/request', methods=['POST'])
def sputnik_join_request(chat_id):
    uid, err = _auth()
    if err:
        return err
    chat = Chat.query.get(chat_id)
    if not chat or chat.chat_type != 'group':
        return jsonify({'success': False, 'error': 'Group not found'}), 404
    if ChatMember.query.filter_by(chat_id=chat_id, user_id=uid).first():
        return jsonify({'success': True, 'data': {'already_member': True}})
    row = SputnikJoinRequest.query.filter_by(chat_id=chat_id, user_id=uid).first()
    if not row:
        row = SputnikJoinRequest(chat_id=chat_id, user_id=uid, status='pending')
        db.session.add(row)
    else:
        row.status = 'pending'
    db.session.commit()
    return jsonify({'success': True})


@spav2_sputnik_bp.route('/sputnik/groups/<int:chat_id>/requests', methods=['GET'])
def sputnik_join_requests(chat_id):
    uid, err = _auth()
    if err:
        return err
    if not _group_owner_or_admin(chat_id, uid):
        return jsonify({'success': False, 'error': 'Not allowed'}), 403
    rows = SputnikJoinRequest.query.filter_by(chat_id=chat_id, status='pending').all()
    out = []
    for r in rows:
        u = User.query.get(r.user_id)
        out.append({'user_id': r.user_id, 'username': u.username if u else None})
    return jsonify({'success': True, 'data': {'requests': out}})


@spav2_sputnik_bp.route('/sputnik/groups/<int:chat_id>/approve', methods=['POST'])
def sputnik_join_approve(chat_id):
    uid, err = _auth()
    if err:
        return err
    if not _group_owner_or_admin(chat_id, uid):
        return jsonify({'success': False, 'error': 'Not allowed'}), 403
    try:
        target = int((request.get_json() or {}).get('user_id'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'user_id required'}), 400
    row = SputnikJoinRequest.query.filter_by(chat_id=chat_id, user_id=target, status='pending').first()
    if not row:
        return jsonify({'success': False, 'error': 'Request not found'}), 404
    row.status = 'approved'
    if not ChatMember.query.filter_by(chat_id=chat_id, user_id=target).first():
        db.session.add(ChatMember(chat_id=chat_id, user_id=target, role='member'))
    db.session.commit()
    chat = Chat.query.get(chat_id)
    _notify_via_system(target, f"Ваша заявка в группу «{chat.name if chat else chat_id}» одобрена.")
    return jsonify({'success': True})


@spav2_sputnik_bp.route('/sputnik/groups/<int:chat_id>/reject', methods=['POST'])
def sputnik_join_reject(chat_id):
    uid, err = _auth()
    if err:
        return err
    if not _group_owner_or_admin(chat_id, uid):
        return jsonify({'success': False, 'error': 'Not allowed'}), 403
    try:
        target = int((request.get_json() or {}).get('user_id'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'user_id required'}), 400
    row = SputnikJoinRequest.query.filter_by(chat_id=chat_id, user_id=target, status='pending').first()
    if not row:
        return jsonify({'success': False, 'error': 'Request not found'}), 404
    row.status = 'rejected'
    db.session.commit()
    chat = Chat.query.get(chat_id)
    _notify_via_system(target, f"Ваша заявка в группу «{chat.name if chat else chat_id}» отклонена.")
    return jsonify({'success': True})


# --- wave 2: per-member permission overrides (Sputnik member_permissions) -----

@spav2_sputnik_bp.route('/sputnik/groups/<int:chat_id>/members/<int:target>/perms', methods=['GET'])
def sputnik_member_perms_get(chat_id, target):
    uid, err = _auth()
    if err:
        return err
    if not _group_owner_or_admin(chat_id, uid):
        return jsonify({'success': False, 'error': 'Not allowed'}), 403
    row = SputnikMemberPerm.query.filter_by(chat_id=chat_id, user_id=target).first()
    import json as _json
    return jsonify({'success': True, 'data': {
        'perms': _json.loads(row.perms) if row and row.perms else {}}})


@spav2_sputnik_bp.route('/sputnik/groups/<int:chat_id>/members/<int:target>/perms', methods=['POST'])
def sputnik_member_perms_set(chat_id, target):
    uid, err = _auth()
    if err:
        return err
    if not _group_owner_or_admin(chat_id, uid):
        return jsonify({'success': False, 'error': 'Not allowed'}), 403
    import json as _json
    perms = (request.get_json() or {}).get('perms') or {}
    if not isinstance(perms, dict):
        return jsonify({'success': False, 'error': 'perms must be an object'}), 400
    row = SputnikMemberPerm.query.filter_by(chat_id=chat_id, user_id=target).first()
    if not row:
        row = SputnikMemberPerm(chat_id=chat_id, user_id=target, perms=_json.dumps(perms))
        db.session.add(row)
    else:
        row.perms = _json.dumps(perms)
    db.session.commit()
    return jsonify({'success': True})


@spav2_sputnik_bp.route('/sputnik/groups/<int:chat_id>/members/<int:target>/perms', methods=['DELETE'])
def sputnik_member_perms_reset(chat_id, target):
    uid, err = _auth()
    if err:
        return err
    if not _group_owner_or_admin(chat_id, uid):
        return jsonify({'success': False, 'error': 'Not allowed'}), 403
    SputnikMemberPerm.query.filter_by(chat_id=chat_id, user_id=target).delete()
    db.session.commit()
    return jsonify({'success': True})


# --- wave 2: group ban/mute with expiry (Sputnik group ban/mute) --------------

@spav2_sputnik_bp.route('/sputnik/groups/<int:chat_id>/restrict', methods=['POST'])
def sputnik_group_restrict(chat_id):
    uid, err = _auth()
    if err:
        return err
    if not _group_owner_or_admin(chat_id, uid):
        return jsonify({'success': False, 'error': 'Not allowed'}), 403
    data = request.get_json() or {}
    kind = (data.get('kind') or 'ban')[:10]
    if kind not in ('ban', 'mute'):
        return jsonify({'success': False, 'error': 'kind must be ban or mute'}), 400
    try:
        target = int(data.get('user_id'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'user_id required'}), 400
    until = None
    if data.get('until'):
        try:
            until = datetime.fromisoformat(str(data['until']))
        except ValueError:
            return jsonify({'success': False, 'error': 'Bad until datetime'}), 400
    row = SputnikGroupRestrict.query.filter_by(chat_id=chat_id, user_id=target, kind=kind).first()
    if not row:
        row = SputnikGroupRestrict(chat_id=chat_id, user_id=target, kind=kind, created_by=uid)
        db.session.add(row)
    row.reason = (data.get('reason') or '')[:255] or None
    row.until = until
    db.session.commit()
    return jsonify({'success': True})


@spav2_sputnik_bp.route('/sputnik/groups/<int:chat_id>/unrestrict', methods=['POST'])
def sputnik_group_unrestrict(chat_id):
    uid, err = _auth()
    if err:
        return err
    if not _group_owner_or_admin(chat_id, uid):
        return jsonify({'success': False, 'error': 'Not allowed'}), 403
    data = request.get_json() or {}
    kind = (data.get('kind') or 'ban')[:10]
    try:
        target = int(data.get('user_id'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'user_id required'}), 400
    SputnikGroupRestrict.query.filter_by(chat_id=chat_id, user_id=target, kind=kind).delete()
    db.session.commit()
    return jsonify({'success': True})


@spav2_sputnik_bp.route('/sputnik/groups/<int:chat_id>/restricted', methods=['GET'])
def sputnik_group_restricted(chat_id):
    uid, err = _auth()
    if err:
        return err
    if not _group_owner_or_admin(chat_id, uid):
        return jsonify({'success': False, 'error': 'Not allowed'}), 403
    rows = SputnikGroupRestrict.query.filter_by(chat_id=chat_id).all()
    return jsonify({'success': True, 'data': {'restricted': [
        {'user_id': r.user_id, 'kind': r.kind, 'reason': r.reason,
         'until': r.until.isoformat() if r.until else None} for r in rows]}})


# --- wave 2: story share + replace (Sputnik share_story, replace_story) -------

@spav2_sputnik_bp.route('/sputnik/stories/<int:story_id>/share', methods=['POST'])
def sputnik_story_share(story_id):
    uid, err = _auth()
    if err:
        return err
    src = Story.query.get(story_id)
    if not src:
        return jsonify({'success': False, 'error': 'Story not found'}), 404
    s = Story(user_id=uid, media_path=src.media_path, media_type=src.media_type,
              caption=src.caption, music_path=src.music_path)
    db.session.add(s)
    db.session.commit()
    return jsonify({'success': True, 'data': {'story_id': s.id}})


@spav2_sputnik_bp.route('/sputnik/stories/<int:story_id>/replace', methods=['POST'])
def sputnik_story_replace(story_id):
    uid, err = _auth()
    if err:
        return err
    s = Story.query.filter_by(id=story_id, user_id=uid).first()
    if not s:
        return jsonify({'success': False, 'error': 'Story not found'}), 404
    data = request.get_json() or {}
    if data.get('media_path'):
        mp = str(data['media_path'])[:500]
        if '..' in mp or mp.startswith('/'):
            return jsonify({'success': False, 'error': 'Invalid media path'}), 400
        s.media_path = mp
    if data.get('media_type'):
        s.media_type = str(data['media_type'])[:20]
    if 'caption' in data:
        s.caption = (data.get('caption') or '')[:1000] or None
    db.session.commit()
    return jsonify({'success': True, 'data': {'story_id': s.id}})


# --- wave 2: data export (Sputnik premium export) -----------------------------

@spav2_sputnik_bp.route('/sputnik/export', methods=['POST'])
def sputnik_export():
    uid, err = _auth()
    if err:
        return err
    u = User.query.get(uid)
    msgs = Message.query.filter_by(sender_id=uid).order_by(Message.timestamp.desc()).limit(500).all()
    folders = SputnikFolder.query.filter_by(user_id=uid).all()
    stickers = SputnikSticker.query.filter_by(owner_id=uid).all()
    return jsonify({'success': True, 'data': {
        'user': {'id': u.id, 'username': u.username, 'display_name': u.display_name,
                 'bio': u.bio, 'created_at': u.created_at.isoformat() if u.created_at else None},
        'messages': [{'id': m.id, 'chat_id': m.chat_id, 'content': m.content,
                      'file_type': m.file_type,
                      'timestamp': m.timestamp.isoformat() if m.timestamp else None} for m in msgs],
        'folders': [{'name': f.name} for f in folders],
        'stickers': [{'file_path': s.file_path, 'emoji': s.emoji} for s in stickers],
        'exported_at': datetime.now(timezone.utc).isoformat(),
    }})
