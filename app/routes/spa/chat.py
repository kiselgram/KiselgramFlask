# app/routes/chats.py
# Kiselgram Chat Routes

from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from datetime import datetime
from app import db
from app.models import User, Message, Chat, ChatMember, ChatSubscriber, PinnedChat, BlockedUser
from app.utils.helpers import get_current_user, get_current_user_id, get_blocked_user_ids, has_active_story, message_to_dict

spa_chat_bp = Blueprint('chats', __name__)

@spa_chat_bp.route('/app')
def picker():
    return redirect('/k', code=302)

@spa_chat_bp.route('/a')
def chat_list():
    """Main chat list view - serves premium or free HTML based on user status"""
    if not get_current_user():
        return redirect('/')

    current_user = get_current_user()
    current_user_id = current_user.id
    is_premium = current_user.premium.is_premium if current_user.premium else False

    chats_data = []

    # 1. Get personal chats
    sent_chats = db.session.query(Message.receiver_id).filter_by(sender_id=current_user_id).distinct()
    received_chats = db.session.query(Message.sender_id).filter_by(receiver_id=current_user_id).distinct()
    chat_user_ids = set([id[0] for id in sent_chats] + [id[0] for id in received_chats])

    for user_id in chat_user_ids:
        user = User.query.get(user_id)
        if user and user.id != current_user_id:
            last_message = Message.query.filter(
                ((Message.sender_id == current_user_id) & (Message.receiver_id == user_id)) |
                ((Message.sender_id == user_id) & (Message.receiver_id == current_user_id))
            ).order_by(Message.timestamp.desc()).first()

            unread_count = Message.query.filter_by(
                sender_id=user_id,
                receiver_id=current_user_id,
                is_read=False
            ).count()

            timestamp = ''
            last_message_data = None

            if last_message:
                time_diff = datetime.utcnow() - last_message.timestamp
                if time_diff.days == 0:
                    timestamp = last_message.timestamp.strftime('%H:%M')
                elif time_diff.days == 1:
                    timestamp = 'Yesterday'
                else:
                    timestamp = last_message.timestamp.strftime('%d.%m.%Y')

                last_message_data = {
                    'content': last_message.content[:50] + '...' if last_message.content and len(
                        last_message.content) > 50 else last_message.content,
                    'sender_id': last_message.sender_id,
                    'sender': {'username': last_message.sender.username}
                }

            # Check if pinned
            pinned = PinnedChat.query.filter_by(
                user_id=current_user_id, chat_type='personal', chat_id=user_id
            ).first() is not None

            chats_data.append({
                'type': 'personal',
                'id': user.id,
                'name': user.display_name or user.username,
                'username': user.username,
                'avatar': user.username[0].upper() if user.username else '?',
                'avatar_url': getattr(user, 'avatar_url', None),
                'last_message': last_message_data,
                'unread_count': unread_count,
                'timestamp': timestamp,
                'is_online': getattr(user, 'is_online', False),
                'is_pinned': pinned
            })

    # 2. Get groups the user is member of
    user_groups = ChatMember.query.filter_by(user_id=current_user_id).all()
    for membership in user_groups:
        chat = Chat.query.get(membership.chat_id)
        if chat:
            last_message = Message.query.filter_by(chat_id=chat.id).order_by(Message.timestamp.desc()).first()

            timestamp = ''
            last_message_data = None

            if last_message:
                time_diff = datetime.utcnow() - last_message.timestamp
                if time_diff.days == 0:
                    timestamp = last_message.timestamp.strftime('%H:%M')
                elif time_diff.days == 1:
                    timestamp = 'Yesterday'
                else:
                    timestamp = last_message.timestamp.strftime('%d.%m.%Y')

                last_message_data = {
                    'content': last_message.content[:50] + '...' if last_message.content and len(
                        last_message.content) > 50 else last_message.content,
                    'sender_id': last_message.sender_id,
                    'sender': {'username': last_message.sender.username}
                }

            member_count = ChatMember.query.filter_by(chat_id=chat.id).count()

            pinned = PinnedChat.query.filter_by(
                user_id=current_user_id, chat_type='group', chat_id=chat.id
            ).first() is not None

            chats_data.append({
                'type': 'group',
                'id': chat.id,
                'name': chat.name,
                'avatar': '👥',
                'avatar_url': getattr(chat, 'avatar_url', None),
                'last_message': last_message_data,
                'unread_count': 0,
                'timestamp': timestamp,
                'member_count': member_count,
                'role': membership.role,
                'is_pinned': pinned
            })

    # 3. Get channels the user is subscribed to
    user_channels = ChatSubscriber.query.filter_by(user_id=current_user_id).all()
    for subscription in user_channels:
        chat = Chat.query.get(subscription.chat_id)
        if chat:
            last_message = Message.query.filter_by(chat_id=chat.id).order_by(Message.timestamp.desc()).first()

            timestamp = ''
            last_message_data = None

            if last_message:
                time_diff = datetime.utcnow() - last_message.timestamp
                if time_diff.days == 0:
                    timestamp = last_message.timestamp.strftime('%H:%M')
                elif time_diff.days == 1:
                    timestamp = 'Yesterday'
                else:
                    timestamp = last_message.timestamp.strftime('%d.%m.%Y')

                last_message_data = {
                    'content': last_message.content[:50] + '...' if last_message.content and len(
                        last_message.content) > 50 else last_message.content,
                    'sender_id': last_message.sender_id,
                    'sender': {'username': last_message.sender.username}
                }

            subscriber_count = ChatSubscriber.query.filter_by(chat_id=chat.id).count()

            pinned = PinnedChat.query.filter_by(
                user_id=current_user_id, chat_type='channel', chat_id=chat.id
            ).first() is not None

            chats_data.append({
                'type': 'channel',
                'id': chat.id,
                'name': chat.name,
                'avatar': '📢',
                'avatar_url': getattr(chat, 'avatar_url', None),
                'last_message': last_message_data,
                'unread_count': 0,
                'timestamp': timestamp,
                'subscriber_count': subscriber_count,
                'is_owner': chat.owner_id == current_user_id,
                'is_pinned': pinned
            })

    # Sort: pinned first, then by most recent
    chats_data.sort(key=lambda x: (not x.get('is_pinned', False), x.get('timestamp', '')), reverse=False)
    chats_data.sort(key=lambda x: x.get('is_pinned', False), reverse=True)

    # Serve premium or free template based on user status
    template_name = 'prem.html' if is_premium else 'free.html'

    return render_template(
        template_name,
        current_user=current_user,
        chats=chats_data,
        is_premium=is_premium,
        session={'user_id': current_user_id}
    )


@spa_chat_bp.route('/app_1')
def index():
    """Root route - redirect to chat list or login"""
    if get_current_user():
        return redirect(url_for('chats.picker'))
    return redirect(url_for('auth.login'))


@spa_chat_bp.route('/k')
def k_version():
    """Kiselgram Web K - SPA v2 frontend"""
    current_user = get_current_user()
    is_premium = current_user.premium.is_premium if current_user and current_user.premium else False
    return render_template(
        'k.html',
        current_user=current_user,
        is_premium=is_premium,
        session={'user_id': current_user.id if current_user else None}
    )

@spa_chat_bp.route('/mobile')
def mobile():
    if not get_current_user():
        return redirect('/')

    current_user = get_current_user()
    is_premium = current_user.premium.is_premium if current_user.premium else False
    return render_template('mobile.html', is_premium=is_premium)


@spa_chat_bp.route('/kis_info')
def kis_info():
    """About page"""
    current_user = get_current_user()
    return render_template(
        'kis_info.html',
        current_user=current_user,
        is_premium=current_user.premium.is_premium if current_user and current_user.premium else False
    )


@spa_chat_bp.route('/premium')
def premium_page():
    """Premium landing page"""
    current_user = get_current_user()
    if not current_user:
        return redirect(url_for('auth.login'))

    return render_template(
        'premium/index.html',
        current_user=current_user,
        is_premium=current_user.premium.is_premium if current_user.premium else False
    )


@spa_chat_bp.route('/chat/<int:chat_id>')
def chat_detail(chat_id):
    """Direct chat view - redirects to main app with chat open"""
    if not get_current_user():
        return redirect('/')

    return redirect(url_for('chats.chat_list') + f'?chat={chat_id}')


@spa_chat_bp.route('/group/<int:group_id>')
def group_detail(group_id):
    """Direct group view"""
    if not get_current_user():
        return redirect('/')

    return redirect(url_for('chats.chat_list') + f'?group={group_id}')


@spa_chat_bp.route('/channel/<int:channel_id>')
def channel_detail(channel_id):
    """Direct channel view"""
    if not get_current_user():
        return redirect('/')

    return redirect(url_for('chats.chat_list') + f'?channel={channel_id}')


@spa_chat_bp.route('/@<username>')
def user_profile(username):
    """Public user profile page"""
    from app.models import User

    user = User.query.filter_by(username=username).first()

    if not user:
        return render_template('errors/404.html'), 404

    current_user = get_current_user()
    is_premium = current_user.premium.is_premium if current_user and current_user.premium else False

    return render_template(
        'profile/public.html',
        profile_user=user,
        current_user=current_user,
        is_premium=is_premium
    )


@spa_chat_bp.route('/chat_list')
def chat_list_page():
    """Legacy alias for chat list"""
    if not get_current_user():
        return redirect('/auth/login')
    return chat_list()


@spa_chat_bp.route('/chat/<int:chat_id>')
def chat_detail_redirect(chat_id):
    return redirect('/k', code=302)


@spa_chat_bp.route('/group/<int:group_id>')
def group_detail_redirect(group_id):
    return redirect('/k', code=302)


@spa_chat_bp.route('/channel/<int:channel_id>')
def channel_detail_redirect(channel_id):
    return redirect('/k', code=302)


@spa_chat_bp.route('/api/chat_list', methods=['GET'])
def chat_list_api():
    try:
        current_user_id = get_current_user_id()
        if not current_user_id:
            return jsonify({'success': False, 'error': 'Not authenticated'}), 401

        blocked_ids = get_blocked_user_ids(current_user_id)
        chats = []

        # Personal chats
        try:
            sent = db.session.query(Message.receiver_id).filter_by(sender_id=current_user_id).distinct().all()
            recv = db.session.query(Message.sender_id).filter_by(receiver_id=current_user_id).distinct().all()
            chat_user_ids = set([id[0] for id in sent] + [id[0] for id in recv])

            for uid in chat_user_ids:
                if uid in blocked_ids or uid == current_user_id:
                    continue
                user = User.query.get(uid)
                if user:
                    last = Message.query.filter(
                        ((Message.sender_id == current_user_id) & (Message.receiver_id == uid)) |
                        ((Message.sender_id == uid) & (Message.receiver_id == current_user_id))
                    ).order_by(Message.timestamp.desc()).first()

                    unread = Message.query.filter_by(
                        sender_id=uid,
                        receiver_id=current_user_id,
                        is_read=False
                    ).count()

                    timestamp = ''
                    if last and last.timestamp:
                        time_diff = datetime.utcnow() - last.timestamp
                        if time_diff.days == 0:
                            timestamp = last.timestamp.strftime('%H:%M')
                        elif time_diff.days == 1:
                            timestamp = 'Yesterday'
                        else:
                            timestamp = last.timestamp.strftime('%d.%m.%Y')

                    chats.append({
                        'type': 'personal',
                        'id': user.id,
                        'name': user.display_name or user.username,
                        'avatar': user.username[0].upper() if user.username else '?',
                        'avatar_url': getattr(user, 'avatar_url', None),
                        'last_message': (last.content[:50] + '...') if last and last.content and len(last.content) > 50 else (last.content if last else 'No messages yet'),
                        'timestamp': timestamp,
                        'unread_count': unread,
                        'is_online': getattr(user, 'is_online', False),
                        'is_pinned': False,
                        'has_story': has_active_story(user.id),
                        'status_emoji': getattr(user, 'status_emoji', '')
                    })
        except Exception as e:
            print(f"Error loading personal chats: {e}")

        # Groups
        try:
            memberships = ChatMember.query.filter_by(user_id=current_user_id).all()
            for membership in memberships:
                chat = Chat.query.get(membership.chat_id)
                if chat:
                    last = Message.query.filter_by(chat_id=chat.id).order_by(Message.timestamp.desc()).first()
                    unread = Message.query.filter_by(chat_id=chat.id, is_read=False).filter(Message.sender_id != current_user_id).count()
                    timestamp = ''
                    if last and last.timestamp:
                        time_diff = datetime.utcnow() - last.timestamp
                        if time_diff.days == 0:
                            timestamp = last.timestamp.strftime('%H:%M')
                        elif time_diff.days == 1:
                            timestamp = 'Yesterday'
                        else:
                            timestamp = last.timestamp.strftime('%d.%m.%Y')
                    member_count = ChatMember.query.filter_by(chat_id=chat.id).count()
                    chats.append({
                        'type': 'group',
                        'id': chat.id,
                        'name': chat.name,
                        'avatar': '👥',
                        'avatar_url': getattr(chat, 'avatar_url', None),
                        'last_message': (last.content[:50] + '...') if last and last.content and len(last.content) > 50 else (last.content if last else 'No messages yet'),
                        'timestamp': timestamp,
                        'unread_count': unread,
                        'member_count': member_count,
                        'role': membership.role,
                        'is_pinned': False
                    })
        except Exception as e:
            print(f"Error loading groups: {e}")

        # Channels
        try:
            subscriptions = ChatSubscriber.query.filter_by(user_id=current_user_id).all()
            for subscription in subscriptions:
                chat = Chat.query.get(subscription.chat_id)
                if chat:
                    last = Message.query.filter_by(chat_id=chat.id).order_by(Message.timestamp.desc()).first()
                    timestamp = ''
                    if last and last.timestamp:
                        time_diff = datetime.utcnow() - last.timestamp
                        if time_diff.days == 0:
                            timestamp = last.timestamp.strftime('%H:%M')
                        elif time_diff.days == 1:
                            timestamp = 'Yesterday'
                        else:
                            timestamp = last.timestamp.strftime('%d.%m.%Y')
                    subscriber_count = ChatSubscriber.query.filter_by(chat_id=chat.id).count()
                    chats.append({
                        'type': 'channel',
                        'id': chat.id,
                        'name': chat.name,
                        'avatar': '📢',
                        'avatar_url': getattr(chat, 'avatar_url', None),
                        'last_message': (last.content[:50] + '...') if last and last.content and len(last.content) > 50 else (last.content if last else 'No posts yet'),
                        'timestamp': timestamp,
                        'unread_count': 0,
                        'subscriber_count': subscriber_count,
                        'is_owner': chat.owner_id == current_user_id,
                        'is_pinned': False
                    })
        except Exception as e:
            print(f"Error loading channels: {e}")

        chats.sort(key=lambda x: (not x.get('is_pinned', False), x.get('timestamp', '')), reverse=False)
        chats.sort(key=lambda x: x.get('is_pinned', False), reverse=True)

        return jsonify({'success': True, 'chats': chats})
    except Exception as e:
        print(f"Fatal error in chat_list_api: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e), 'chats': []}), 500

@spa_chat_bp.route('/api/messages/<int:user_id>', methods=['GET'])
def get_personal_messages(user_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    # Check if blocked
    if BlockedUser.query.filter_by(user_id=user_id, blocked_user_id=current_user_id).first():
        return jsonify({'success': False, 'error': 'You are blocked by this user'}), 403

    after_id = request.args.get('after', 0, type=int)
    limit = request.args.get('limit', 50, type=int)

    messages = Message.query.filter(
        ((Message.sender_id == current_user_id) & (Message.receiver_id == user_id)) |
        ((Message.sender_id == user_id) & (Message.receiver_id == current_user_id))
    ).filter(Message.id > after_id) \
     .order_by(Message.timestamp.asc()) \
     .limit(limit).all()

    return jsonify({
        'success': True,
        'messages': [message_to_dict(msg, current_user_id) for msg in messages]
    })

@spa_chat_bp.route('/api/mark_read/<int:user_id>', methods=['POST'])
def mark_messages_read(user_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    Message.query.filter_by(
        sender_id=user_id,
        receiver_id=current_user_id,
        is_read=False
    ).update({'is_read': True, 'read_at': datetime.utcnow()})
    db.session.commit()
    return jsonify({'success': True})



# ============ CONTEXT PROCESSOR ============

@spa_chat_bp.app_context_processor
def inject_premium_status():
    """Inject premium status into all templates"""
    current_user = get_current_user()
    return {
        'user_is_premium': current_user.premium.is_premium if current_user and current_user.premium else False
    }