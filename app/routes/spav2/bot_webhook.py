import threading
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from app import db
from app.models import User, Message, Chat
from app.utils.helpers import get_current_user_id
from app.utils.security import rate_limit

spav2_bot_webhook_bp = Blueprint('spav2_bot_webhook', __name__, url_prefix='/api/bots')

@spav2_bot_webhook_bp.route('/webhook/<token>', methods=['POST'])
def bot_incoming_webhook(token):
    """External services POST events here for a bot, authenticated by bot token."""
    bot = User.query.filter_by(bot_token=token, is_bot=True).first()
    if not bot:
        return jsonify({'success': False, 'error': {'code': 'INVALID_TOKEN', 'message': 'Invalid bot token'}}), 403

    data = request.get_json() or {}
    event = data.get('event', 'message')
    payload = data.get('data', {})
    chat_id = payload.get('chat_id')
    receiver_id = payload.get('receiver_id')
    content = payload.get('content', '')

    if event == 'message':
        if not content:
            return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'content required'}}), 400

        # Determine target: specific chat or specific user
        if chat_id:
            msg = Message(
                content=content,
                sender_id=bot.id,
                chat_id=chat_id,
                receiver_id=receiver_id or bot.id,
                timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
                is_from_telegram=True
            )
            db.session.add(msg)
        elif receiver_id:
            a, b = sorted([bot.id, receiver_id])
            chat = Chat.query.filter_by(chat_type='personal', user1_id=a, user2_id=b).first()
            if not chat:
                chat = Chat(chat_type='personal', user1_id=a, user2_id=b)
                db.session.add(chat)
                db.session.flush()
            msg = Message(
                content=content,
                sender_id=bot.id,
                receiver_id=receiver_id,
                chat_id=chat.id,
                timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
                is_from_telegram=True
            )
            db.session.add(msg)
        else:
            return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'chat_id or receiver_id required'}}), 400

        db.session.commit()
        return jsonify({'success': True, 'data': {'message_id': msg.id}}), 201

    elif event == 'typing':
        # Bot typing indicator: best-effort, no persistent storage required.
        return jsonify({'success': True, 'data': {'message': 'typing indicator set'}})

    elif event == 'callback_query':
        return jsonify({'success': True, 'data': {'message': 'callback received'}})

    return jsonify({'success': False, 'error': {'code': 'UNKNOWN_EVENT', 'message': f'Unknown event: {event}'}}), 400


@spav2_bot_webhook_bp.route('/webhook', methods=['PUT'])
def set_webhook_url():
    """Bot owner sets an outgoing webhook URL for their bot."""
    user = get_current_user_id()
    if not user:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    data = request.get_json() or {}
    bot_id = data.get('bot_id')
    webhook_url = data.get('webhook_url', '').strip()

    if not bot_id:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'bot_id required'}}), 400

    bot = User.query.get(bot_id)
    if not bot or not bot.is_bot or bot.bot_owner_id != user:
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'Not your bot'}}), 403

    if webhook_url and not webhook_url.startswith('https://'):
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'Webhook URL must use HTTPS'}}), 400

    bot.bot_webhook_url = webhook_url or None
    db.session.commit()
    return jsonify({'success': True, 'data': {'bot_id': bot_id, 'webhook_url': bot.bot_webhook_url}})


def deliver_webhook_event(bot, event, data):
    """Deliver an event to a bot's outgoing webhook URL (runs in thread)."""
    import urllib.request, json as _json
    url = bot.bot_webhook_url
    if not url:
        return
    try:
        payload = _json.dumps({'event': event, 'data': data}).encode()
        req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'}, method='POST')
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        current_app.logger.error(f"Webhook delivery failed to {url}: {e}")
