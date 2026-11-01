from flask import Blueprint, request, jsonify
from app import db
from app.models import Message, Reaction, Reply, Forward, User, BlockedUser, Chat
from app.utils.helpers import get_current_user_id, message_to_dict
from datetime import datetime
import time

spa_messages_bp = Blueprint('spa_messages', __name__, url_prefix='/api')

# In-memory typing status: {chat_type_chat_id: {user_id: timestamp}}
_typing_status = {}
_TYPING_TIMEOUT = 5  # seconds

@spa_messages_bp.route('/typing/<chat_type>/<int:chat_id>', methods=['POST'])
def set_typing(chat_type, chat_id):
    """Signal that current user is typing in a chat."""
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    key = f"{chat_type}_{chat_id}"
    if key not in _typing_status:
        _typing_status[key] = {}
    _typing_status[key][current_user_id] = time.time()
    return jsonify({'success': True})

@spa_messages_bp.route('/typing/<chat_type>/<int:chat_id>', methods=['GET'])
def get_typing(chat_type, chat_id):
    """Get list of users currently typing in a chat."""
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    key = f"{chat_type}_{chat_id}"
    now = time.time()
    typists = []
    if key in _typing_status:
        expired = []
        for uid, ts in _typing_status[key].items():
            if now - ts > _TYPING_TIMEOUT:
                expired.append(uid)
            else:
                user = User.query.get(uid)
                if user and uid != current_user_id:
                    typists.append({
                        'user_id': uid,
                        'name': user.display_name or user.username
                    })
        for uid in expired:
            del _typing_status[key][uid]
        if not _typing_status[key]:
            del _typing_status[key]
    return jsonify({'typing': typists})

@spa_messages_bp.route('/send_message', methods=['POST'])
def send_personal_message():
    try:
        current_user_id = get_current_user_id()
        if not current_user_id:
            return jsonify({'success': False, 'error': 'Not authenticated'}), 401
        data = request.get_json()
        receiver_id = data.get('receiver_id')
        content = data.get('content', '').strip()
        reply_to_id = data.get('reply_to_id')
        if not content:
            return jsonify({'success': False, 'error': 'Message content required'}), 400
        receiver = User.query.get(receiver_id)
        if not receiver:
            return jsonify({'success': False, 'error': 'User not found'}), 404
        if BlockedUser.query.filter_by(user_id=receiver_id, blocked_user_id=current_user_id).first():
            return jsonify({'success': False, 'error': 'You are blocked'}), 403
        # Find or create personal chat (uses user1_id/user2_id, NOT ChatMember)
        a, b = sorted([current_user_id, receiver_id])
        chat = Chat.query.filter_by(chat_type='personal', user1_id=a, user2_id=b).first()
        if not chat:
            chat = Chat(chat_type='personal', user1_id=a, user2_id=b)
            db.session.add(chat)
            db.session.flush()
        new_message = Message(content=content, sender_id=current_user_id, receiver_id=receiver_id, chat_id=chat.id, timestamp=datetime.utcnow(), silent=bool(data.get('silent')), send_when_online=bool(data.get('send_when_online')))
        db.session.add(new_message)
        db.session.flush()
        if reply_to_id:
            original = Message.query.get(reply_to_id)
            if original:
                db.session.add(Reply(original_message_id=reply_to_id, reply_message_id=new_message.id))
        db.session.commit()
        return jsonify({'success': True, 'message': message_to_dict(new_message, current_user_id)})
    except Exception as e:
        db.session.rollback()
        print(f"Error in send_personal_message: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@spa_messages_bp.route('/reactions/<int:message_id>', methods=['GET'])
def get_reactions(message_id):
    """Get all reactions for a message."""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    reactions = Reaction.query.filter_by(message_id=message_id).all()
    grouped = {}
    for r in reactions:
        if r.reaction_type not in grouped:
            grouped[r.reaction_type] = {'type': r.reaction_type, 'count': 0}
        grouped[r.reaction_type]['count'] += 1

    user_reaction = Reaction.query.filter_by(message_id=message_id, user_id=user_id).first()
    return jsonify({
        'success': True,
        'reactions': list(grouped.values()),
        'user_reaction': user_reaction.reaction_type if user_reaction else None
    })

@spa_messages_bp.route('/reactions/add', methods=['POST'])
def add_reaction():
    """Add or change a reaction on a message. Max 3 reactions per user per message."""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    data = request.get_json()
    message_id = data.get('message_id')
    reaction_type = data.get('reaction_type')

    valid = ['👍', '❤️', '😂', '😮', '😢', '👏', '🔥', '🎉', '💯']
    if reaction_type not in valid:
        return jsonify({'success': False, 'error': 'Invalid reaction'}), 400

    # Check count
    current_reactions = Reaction.query.filter_by(message_id=message_id, user_id=user_id).all()
    if len(current_reactions) >= 3 and not any(r.reaction_type == reaction_type for r in current_reactions):
        return jsonify({'success': False, 'error': 'Maximum 3 reactions per message'}), 400

    existing = Reaction.query.filter_by(message_id=message_id, user_id=user_id, reaction_type=reaction_type).first()
    if existing:
        db.session.delete(existing)
    else:
        db.session.add(Reaction(message_id=message_id, user_id=user_id, reaction_type=reaction_type))
    db.session.commit()

    # Return updated reactions
    reactions = Reaction.query.filter_by(message_id=message_id).all()
    grouped = {}
    for r in reactions:
        if r.reaction_type not in grouped:
            grouped[r.reaction_type] = {'type': r.reaction_type, 'count': 0}
        grouped[r.reaction_type]['count'] += 1

    return jsonify({'success': True, 'reactions': list(grouped.values())})

@spa_messages_bp.route('/messages/<int:message_id>/edit', methods=['POST'])
def edit_message(message_id):
    """Edit the content of a message (only the sender can edit)."""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    msg = Message.query.get_or_404(message_id)
    if msg.sender_id != user_id:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403

    data = request.get_json()
    new_content = data.get('content', '').strip()
    if not new_content:
        return jsonify({'success': False, 'error': 'Content cannot be empty'}), 400

    msg.content = new_content
    msg.edited_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True})

@spa_messages_bp.route('/messages/<int:message_id>/delete', methods=['DELETE'])
def delete_message(message_id):
    """Delete a message (soft delete) only for the sender."""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    msg = Message.query.get_or_404(message_id)
    if msg.sender_id != user_id:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403

    msg.is_deleted = True
    db.session.commit()
    return jsonify({'success': True})

@spa_messages_bp.route('/messages/forward', methods=['POST'])
def forward_message():
    """Forward a message to another chat, group, or channel."""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    data = request.get_json()
    original_id = data.get('message_id')
    target_type = data.get('target_type')
    target_id = data.get('target_id')

    original = Message.query.get(original_id)
    if not original:
        return jsonify({'success': False, 'error': 'Message not found'}), 404

    # Create a new message with forward metadata
    new_msg = Message(
        sender_id=user_id,
        content=f"📨 Forwarded from {original.sender.username}:\n{original.content}" if original.content else "",
        has_attachment=original.has_attachment,
        file_type=original.file_type,
        file_path=original.file_path,
        file_name=original.file_name,
        file_size=original.file_size,
        timestamp=datetime.utcnow()
    )

    if target_type == 'personal':
        new_msg.receiver_id = int(target_id)
    elif target_type == 'group':
        new_msg.chat_id = int(target_id)
        new_msg.receiver_id = user_id
    elif target_type == 'channel':
        new_msg.chat_id = int(target_id)
        new_msg.receiver_id = user_id
    else:
        return jsonify({'success': False, 'error': 'Invalid target type'}), 400

    db.session.add(new_msg)
    db.session.flush()

    # Keep forward record
    fwd = Forward(
        original_message_id=original_id,
        forwarded_message_id=new_msg.id,
        forwarded_by_id=user_id,
        original_sender_name=original.sender.username if original.sender else 'Unknown'
    )
    db.session.add(fwd)
    db.session.commit()

    # Convert to dict using a local helper (or import from chat.py)
    def message_to_dict(msg, uid):
        d = {
            'id': msg.id, 'content': msg.content, 'sender_id': msg.sender_id,
            'sender_name': msg.sender.username if msg.sender else 'Unknown',
            'timestamp': msg.timestamp.isoformat(), 'timestamp_formatted': msg.timestamp.strftime('%H:%M') if msg.timestamp else '',
            'is_own': True, 'is_read': False, 'has_attachment': msg.has_attachment,
            'reply_to_id': None, 'reply_to_content': None, 'reply_to_sender': None,
            'forwarded_from': fwd.original_sender_name,
            'reactions': {}
        }
        if msg.has_attachment:
            file = msg.file
            d['file_type'] = file.file_type if file else msg.file_type
            d['file_name'] = file.file_name if file else msg.file_name
            d['file_url'] = f"/uploads/{file.file_path if file else msg.file_path}" if (file or msg.file_path) else None
            d['preview_size'] = file.preview_size if file else (
                'big' if msg.file_type == 'image'
                else 'medium' if msg.file_type in ('video',)
                else 'none'
            )
        return d

    return jsonify({'success': True, 'message': message_to_dict(new_msg, user_id)})

@spa_messages_bp.route('/clear_chat', methods=['POST'])
def clear_chat():
    """Clear all messages in a chat/group/channel for the current user (soft delete)."""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    data = request.get_json()
    chat_id = data.get('chat_id')
    group_id = data.get('group_id')
    channel_id = data.get('channel_id')

    if not any([chat_id, group_id, channel_id]):
        return jsonify({'success': False, 'error': 'No target specified'}), 400

    filters = []
    if chat_id:
        filters.append(Message.chat_id == int(chat_id))
    if group_id:
        filters.append(Message.chat_id == int(group_id))
    if channel_id:
        filters.append(Message.chat_id == int(channel_id))

    Message.query.filter(*filters).update({'is_deleted': True})
    db.session.commit()
    return jsonify({'success': True})