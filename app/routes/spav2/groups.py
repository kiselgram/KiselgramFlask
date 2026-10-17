import os
import json
import secrets
from datetime import datetime
from flask import Blueprint, request, jsonify
from app import db
from app.models import User, Chat, ChatMember, GroupPermission, Message, File, Reply
from app.utils.helpers import get_current_user_id, validate_emoji, get_animated_file_for_emoji

spav2_groups_bp = Blueprint('spav2_groups', __name__, url_prefix='/api')


def _serialize_group(chat, member_count=None, last_message=None):
    if member_count is None:
        member_count = ChatMember.query.filter_by(chat_id=chat.id).count()
    last = last_message or Message.query.filter_by(chat_id=chat.id).order_by(Message.timestamp.desc()).first()
    return {
        'group_id': chat.id,
        'name': chat.name,
        'description': chat.description,
        'avatar_url': chat.avatar_url,
        'owner_id': chat.owner_id,
        'is_public': chat.is_public,
        'invite_link': f"kiselgram.com/join/{chat.invite_link}" if chat.invite_link else None,
        'member_count': member_count,
        'my_role': None,
        'last_message': {
            'message_id': last.id,
            'content': last.content,
            'sender_username': last.sender.username if last.sender else None,
            'timestamp': last.timestamp.isoformat() if last.timestamp else None
        } if last else None,
        'created_at': chat.created_at.isoformat() if chat.created_at else None
    }


@spav2_groups_bp.route('/groups', methods=['GET'])
def get_groups():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 100)

    memberships = ChatMember.query.filter_by(user_id=current_user_id).all()
    chat_ids = [m.chat_id for m in memberships]
    chats_map = {c.id: c for c in Chat.query.filter(Chat.id.in_(chat_ids)).all()} if chat_ids else {}
    counts = dict(db.session.query(ChatMember.chat_id, db.func.count(ChatMember.id)).filter(ChatMember.chat_id.in_(chat_ids)).group_by(ChatMember.chat_id).all()) if chat_ids else {}

    last_msg_for_group = {}
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

    groups = []
    for m in memberships:
        chat = chats_map.get(m.chat_id)
        if chat:
            g = _serialize_group(chat, member_count=counts.get(chat.id, 0), last_message=last_msg_for_group.get(chat.id))
            g['my_role'] = m.role
            groups.append(g)

    total = len(groups)
    pages = (total + per_page - 1) // per_page if total else 1
    start = (page - 1) * per_page
    page_groups = groups[start:start + per_page]

    return jsonify({'success': True, 'data': {
        'groups': page_groups,
        'pagination': {'page': page, 'per_page': per_page, 'total': total, 'pages': pages}
    }})


@spav2_groups_bp.route('/groups/<int:group_id>', methods=['GET'])
def get_group(group_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    chat = Chat.query.get(group_id)
    if not chat or chat.chat_type != 'group':
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Group not found'}}), 404

    membership = ChatMember.query.filter_by(user_id=current_user_id, chat_id=group_id).first()
    if not membership and not chat.is_public:
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'You are not a member'}}), 403

    owner = User.query.filter(User.id == chat.owner_id, User.is_deleted.is_(False)).first() if chat.owner_id else None
    return jsonify({'success': True, 'data': {
        'group_id': chat.id,
        'name': chat.name,
        'description': chat.description,
        'avatar_url': chat.avatar_url,
        'owner_id': chat.owner_id,
        'owner_username': owner.username if owner else None,
        'is_public': chat.is_public,
        'invite_link': f"kiselgram.com/join/{chat.invite_link}" if chat.invite_link else None,
        'created_at': chat.created_at.isoformat() if chat.created_at else None,
        'member_count': ChatMember.query.filter_by(chat_id=chat.id).count(),
        'members_url': f"/api/groups/{group_id}/members"
    }})


@spav2_groups_bp.route('/groups/<int:group_id>/members', methods=['GET'])
def get_group_members(group_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 100)

    memberships = ChatMember.query.filter_by(chat_id=group_id).offset((page - 1) * per_page).limit(per_page).all()
    total = ChatMember.query.filter_by(chat_id=group_id).count()
    user_ids = [m.user_id for m in memberships]
    users_map = {u.id: u for u in User.query.filter(User.id.in_(user_ids), User.is_deleted.is_(False)).all()} if user_ids else {}
    members = []
    for m in memberships:
        user = users_map.get(m.user_id)
        if user:
            members.append({
                'user_id': user.id,
                'username': user.username,
                'avatar_url': user.avatar_url,
                'role': m.role,
                'joined_at': m.joined_at.isoformat() if m.joined_at else None
            })

    pages = (total + per_page - 1) // per_page if total else 1
    return jsonify({'success': True, 'data': {
        'group_id': group_id,
        'members': members,
        'pagination': {'page': page, 'per_page': per_page, 'total': total, 'pages': pages}
    }})


@spav2_groups_bp.route('/group_messages/<int:group_id>', methods=['GET'])
def get_group_messages(group_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    if not ChatMember.query.filter_by(user_id=current_user_id, chat_id=group_id).first():
        return jsonify({'success': False, 'error': {'code': 'NOT_MEMBER', 'message': 'Not a member'}}), 403

    after_id = request.args.get('after', 0, type=int)
    limit = min(request.args.get('limit', 50, type=int), 100)

    messages = Message.query.options(db.joinedload(Message.reactions)).filter_by(chat_id=group_id).filter(Message.id > after_id).order_by(Message.timestamp.asc()).limit(limit).all()
    has_more = len(messages) == limit

    result = []
    for msg in messages:
        reacs = {}
        for r in msg.reactions:
            reacs[r.reaction_type] = reacs.get(r.reaction_type, 0) + 1
        d = {
            'message_id': msg.id,
            'sender_id': msg.sender_id,
            'sender_username': msg.sender.username if msg.sender else None,
            'sender_avatar_url': msg.sender.avatar_url if msg.sender else None,
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
        }
        result.append(d)

    next_cursor = messages[-1].id if messages else None
    return jsonify({'success': True, 'data': {
        'group_id': group_id,
        'messages': result,
        'pagination': {'after': after_id or None, 'limit': limit, 'has_more': has_more, 'next_cursor': next_cursor}
    }})


@spav2_groups_bp.route('/groups/create', methods=['POST'])
def create_group():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    data = request.get_json() or {}
    name = data.get('name', '').strip()
    description = data.get('description', '')
    member_ids = data.get('member_ids', [])

    if not isinstance(member_ids, list):
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'member_ids must be a list'}}), 400

    if not name:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'Validation failed', 'fields': {'name': 'Group name is required', 'member_ids': 'At least one member is required'}}}), 400

    invite_link = secrets.token_urlsafe(16)
    chat = Chat(chat_type='group', name=name, description=description, owner_id=current_user_id, is_public=False, invite_link=invite_link, created_at=datetime.utcnow())
    db.session.add(chat)
    db.session.flush()

    db.session.add(ChatMember(user_id=current_user_id, chat_id=chat.id, role='owner'))
    for mid in member_ids:
        if mid != current_user_id:
            db.session.add(ChatMember(user_id=mid, chat_id=chat.id, role='member'))

    for role in ('owner', 'admin', 'member'):
        db.session.add(GroupPermission(chat_id=chat.id, role=role, can_send_messages=True, can_send_media=True,
                                        can_add_members=role != 'member', can_pin_messages=role != 'member',
                                        can_change_info=role != 'member', can_delete_messages=role != 'member', can_ban_users=role == 'owner'))
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': str(e)}}), 500

    return jsonify({'success': True, 'data': {'group': _serialize_group(chat)}}), 201


@spav2_groups_bp.route('/send_group_message', methods=['POST'])
def send_group_message():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    data = request.get_json() or {}
    group_id = data.get('group_id')
    content = data.get('content', '').strip()
    reply_to_id = data.get('reply_to_id')

    if not group_id:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'group_id is required'}}), 400

    # Auto-convert single unicode emoji (e.g., 😋) to animated
    emoji_data = None
    if content and not data.get('emoji_file'):
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
    if not content and not emoji_data:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'content is required'}}), 400

    membership = ChatMember.query.filter_by(user_id=current_user_id, chat_id=group_id).first()
    if not membership:
        return jsonify({'success': False, 'error': {'code': 'NOT_MEMBER', 'message': 'You are not a member of this group'}}), 403

    from app.utils.helpers import slow_mode_ok
    ok, retry = slow_mode_ok(current_user_id, group_id)
    if not ok:
        return jsonify({'success': False, 'error': {'code': 'SLOW_MODE', 'message': f'Slow mode: wait {retry}s'}}), 429

    msg = Message(sender_id=current_user_id, chat_id=group_id, receiver_id=current_user_id, content=content, timestamp=datetime.utcnow())
    if emoji_data:
        msg.emoji = emoji_data['emoji']
        msg.emoji_file = emoji_data['file']
        msg.emoji_size = emoji_data['size']
        msg.emoji_count = emoji_data['count']
    db.session.add(msg)
    db.session.flush()

    if reply_to_id:
        original = Message.query.get(reply_to_id)
        if original:
            db.session.add(Reply(original_message_id=reply_to_id, reply_message_id=msg.id))

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': str(e)}}), 500
    return jsonify({'success': True, 'data': {'message': {
        'message_id': msg.id,
        'sender_id': msg.sender_id,
        'sender_username': msg.sender.username if msg.sender else None,
        'sender_avatar_url': msg.sender.avatar_url if msg.sender else None,
        'group_id': group_id,
        'content': msg.content,
        'reply_to_id': reply_to_id,
        'file_path': None,
        'file_type': None,
        'emoji': msg.emoji,
        'emoji_file': msg.emoji_file,
        'emoji_url': f"/uploads/animated_emojis/{msg.emoji_file}" if msg.emoji_file else None,
        'emoji_size': msg.emoji_size or 96,
        'emoji_count': msg.emoji_count or 1,
        'timestamp': msg.timestamp.isoformat() if msg.timestamp else None,
        'edited_at': None
    }}}), 201


@spav2_groups_bp.route('/groups/<int:group_id>/update', methods=['POST'])
def update_group(group_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    membership = ChatMember.query.filter_by(user_id=current_user_id, chat_id=group_id).first()
    if not membership or membership.role not in ('owner', 'admin'):
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'Only owners and admins can update the group'}}), 403

    data = request.get_json() or {}
    chat = Chat.query.get(group_id)
    if not chat or chat.chat_type != 'group':
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Group not found'}}), 404

    if 'name' in data:
        val = data['name']
        if not isinstance(val, str) or len(val) > 100:
            return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'Name must be a string (max 100 characters)'}}), 400
        chat.name = val
    if 'description' in data:
        val = data['description']
        if not isinstance(val, str) or len(val) > 2000:
            return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'Description must be a string (max 2000 characters)'}}), 400
        chat.description = val
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': str(e)}}), 500
    return jsonify({'success': True, 'data': {'group': _serialize_group(chat)}})


@spav2_groups_bp.route('/groups/<int:group_id>/members/<int:user_id>/role', methods=['POST'])
def update_member_role(group_id, user_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    membership = ChatMember.query.filter_by(user_id=current_user_id, chat_id=group_id).first()
    if not membership or membership.role != 'owner':
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'Only the owner can change member roles'}}), 403

    target = ChatMember.query.filter_by(user_id=user_id, chat_id=group_id).first()
    if not target:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Member not found'}}), 404
    if target.role == 'owner':
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'Cannot change the owner role'}}), 400

    data = request.get_json() or {}
    role = data.get('role')
    if role not in ('admin', 'member'):
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'Role must be one of: admin, member'}}), 400

    target.role = role
    target.updated_at = datetime.utcnow()
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': str(e)}}), 500

    user = User.query.filter(User.id == user_id, User.is_deleted.is_(False)).first()
    return jsonify({'success': True, 'data': {
        'group_id': group_id, 'user_id': user_id,
        'username': user.username if user else None,
        'role': role, 'updated_at': datetime.utcnow().isoformat()
    }})


@spav2_groups_bp.route('/join_group/<invite_link>', methods=['GET'])
def join_group(invite_link):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    chat = Chat.query.filter_by(chat_type='group', invite_link=invite_link).first()
    if not chat:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Group not found'}}), 404

    existing = ChatMember.query.filter_by(user_id=current_user_id, chat_id=chat.id).first()
    if not existing:
        db.session.add(ChatMember(user_id=current_user_id, chat_id=chat.id, role='member'))
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': str(e)}}), 500

    owner = User.query.filter(User.id == chat.owner_id, User.is_deleted.is_(False)).first() if chat.owner_id else None
    return jsonify({'success': True, 'data': {
        'group': {
            'group_id': chat.id, 'name': chat.name, 'description': chat.description,
            'avatar_url': chat.avatar_url, 'owner_id': chat.owner_id,
            'is_public': chat.is_public, 'member_count': ChatMember.query.filter_by(chat_id=chat.id).count(),
            'my_role': 'member',
            'joined_at': datetime.utcnow().isoformat()
        }
    }})


@spav2_groups_bp.route('/leave_group/<int:group_id>', methods=['POST'])
def leave_group(group_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    membership = ChatMember.query.filter_by(user_id=current_user_id, chat_id=group_id).first()
    if not membership:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Not a member'}}), 404

    if membership.role == 'owner':
        return jsonify({'success': False, 'error': {'code': 'OWNER_CANNOT_LEAVE', 'message': 'Owner cannot leave the group. Transfer ownership or delete the group.'}}), 403

    db.session.delete(membership)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': str(e)}}), 500
    return jsonify({'success': True, 'data': {'message': 'Successfully left the group', 'group_id': group_id}})
