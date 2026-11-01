import time
import threading
import secrets
import re
from werkzeug.security import generate_password_hash


def hash_password(password):
    """Helper function for hashing passwords"""
    return generate_password_hash(password)


def setup_bots():
    """Initialize bot users"""
    from app import db
    from app.models import User

    bots_data = [
        {'name': 'Weather Bot', 'username': 'weather_bot', 'description': 'Get weather information'},
        {'name': 'News Bot', 'username': 'news_bot', 'description': 'Latest news headlines'},
        {'name': 'Calculator Bot', 'username': 'calc_bot', 'description': 'Mathematical calculations'},
        {'name': 'Kiselgram Help', 'username': 'kiselgram_bot', 'description': 'Official help - Premium via Stars'},
        {'name': 'Kiselgram Premium', 'username': 'kiselgram_premium', 'description': 'Premium via Telegram Stars — same workflow as @kiselgram_bot'},
    ]

    for bot_data in bots_data:
        if not User.query.filter_by(username=bot_data['username']).first():
            bot_user = User(
                username=bot_data['username'],
                display_name=bot_data['name'],
                bio=bot_data['description'],
                is_bot=True,
                password_hash=hash_password(secrets.token_hex(16)) if bot_data['username'] != "kiselgram_bot" else hash_password("kiselgramsupport"),
            )
            db.session.add(bot_user)
    db.session.commit()


def _is_premium_emoji_request(content: str, emoji: str = None, emoji_file: str = None) -> bool:
    """Check if message is requesting premium via emoji or text."""
    if emoji_file and 'kiselgram_premium' in emoji_file:
        return True
    if emoji and emoji.strip() in ('⭐', '⭐️', '💎', '✨'):
        return True
    if content:
        low = content.lower()
        if any(k in low for k in ('premium', 'премиум', 'kiselgram_premium', '5285476321705633458')):
            return True
        if '⭐' in content or '💎' in content:
            return True
    return False


def simulate_bot_interaction(app):
    """Simulate bot responses for Kiselgram internal bots, now with emoji support."""
    while True:
        try:
            with app.app_context():
                from app import db
                from app.models import User, Message
                from app.utils.helpers import get_animated_file_for_emoji

                bots = User.query.filter_by(is_bot=True).all()

                for bot in bots:
                    unread_messages = Message.query.filter_by(
                        receiver_id=bot.id,
                        is_read=False
                    ).all()

                    for message in unread_messages:
                        message.is_read = True

                        # Extract incoming emoji info
                        incoming_emoji = (message.emoji or '').strip()
                        incoming_file = (message.emoji_file or '').strip()
                        content = (message.content or '').strip()
                        content_lower = content.lower() if content else ""

                        # Default response
                        response = None
                        response_emoji = None
                        response_emoji_file = None
                        response_emoji_size = 96
                        response_emoji_count = 1

                        if bot.username == 'weather_bot':
                            response = "Will be soon! Ask Ilya for the weather!"
                        elif bot.username == 'news_bot':
                            response = "📰 Breaking: Kiselgram now supports media sending! Stay tuned for more updates and also subscribe to our telegram channel: t.me/KiseIgram"
                        elif bot.username == 'calc_bot':
                            safe = re.sub(r'[^0-9+\-*/().% ]', '', content)
                            if not safe.strip():
                                response = "❌ I can only do simple math calculations. Try something like '2+2' or '5*3'."
                            else:
                                try:
                                    result = eval(safe, {'__builtins__': {}}, {})
                                    if isinstance(result, (int, float)):
                                        response = f"🧮 Result: {result}"
                                    else:
                                        response = "❌ I can only do simple math calculations. Try something like '2+2' or '5*3'."
                                except Exception:
                                    response = "❌ I can only do simple math calculations. Try something like '2+2' or '5*3'."
                        elif bot.username in ('kiselgram', 'kiselgram_bot', 'kiselgram_help', 'kiselgram_premium'):
                            # For kiselgram_premium, use same Stars workflow as Telegram @kiselgram_bot
                            is_premium_bot = bot.username == 'kiselgram_premium'
                            # Detect language from sender (fallback en)
                            lang = 'en'
                            try:
                                sender_user = User.query.get(message.sender_id)
                                # Use sender's language if available via telegram code? default ru
                            except Exception:
                                pass

                            if is_premium_bot:
                                # Same workflow as Telegram bot, but for Kiselgram chat
                                from app.utils.i18n import t as i18n_t
                                from app.routes.telegram_stars import get_prices, _make_payload
                                from app.models import UserPremium

                                prices = get_prices()

                                if _is_premium_emoji_request(content, incoming_emoji, incoming_file):
                                    response = i18n_t('bot.premium_desc', lang) + f"\n\nhttps://web.kiselgram.ru/telegram-premium/?uid={message.sender_id}&lang={lang}"
                                    response_emoji = "⭐"
                                    response_emoji_file = "kiselgram_premium.webp"
                                    response_emoji_size = 128
                                elif content_lower in ('/start', '/start premium', '/help', 'help', 'привет', 'hi', 'hello') or content.startswith('/start'):
                                    # Handle /start premium_<id> linking (same as Telegram)
                                    m = re.search(r'(\d+)', content) if content.startswith('/start') and len(content.split())>1 else None
                                    if m and is_premium_bot:
                                        # No need to link for internal bot (already same user), just welcome
                                        pass
                                    response = i18n_t('bot.welcome', lang)
                                    response_emoji = "⭐"
                                    response_emoji_file = "kiselgram_premium.webp"
                                    response_emoji_size = 96
                                elif 'premium' in content_lower or '/premium' in content_lower or 'премиум' in content_lower:
                                    # Create invoice-like response with Stars link
                                    response = i18n_t('bot.premium_desc', lang) + f"\n\n💳 https://web.kiselgram.ru/telegram-premium/?uid={message.sender_id}&lang={lang}\n\n" + i18n_t('bot.choose_tariff', lang) + f"\n• {i18n_t('bot.inline_monthly', lang, amount=prices['monthly'])}\n• {i18n_t('bot.inline_yearly', lang, amount=prices['yearly'])}"
                                    response_emoji = "⭐"
                                    response_emoji_file = "kiselgram_premium.webp"
                                    response_emoji_size = 128
                                elif content_lower == '/status':
                                    # Check premium status for sender
                                    sender = User.query.get(message.sender_id)
                                    is_p = sender.premium.is_premium if sender and sender.premium else False
                                    exp = sender.premium.premium_expires_at if sender and sender.premium else None
                                    if is_p and exp:
                                        response = i18n_t('bot.premium_active', lang, date=exp.strftime('%d.%m.%Y'))
                                    else:
                                        response = i18n_t('bot.premium_inactive', lang)
                                    response_emoji = "⭐"
                                    response_emoji_file = "kiselgram_premium.webp"
                                elif incoming_file or incoming_emoji:
                                    if incoming_emoji in ('⭐', '⭐️') or (incoming_file and 'kiselgram' in incoming_file):
                                        response = ""
                                        response_emoji = "⭐"
                                        response_emoji_file = "kiselgram_premium.webp"
                                        response_emoji_size = message.emoji_size or 128
                                        response_emoji_count = message.emoji_count or 1
                                    else:
                                        response = ""
                                        response_emoji = incoming_emoji
                                        response_emoji_file = incoming_file
                                        response_emoji_size = message.emoji_size or 96
                                        response_emoji_count = message.emoji_count or 1
                                else:
                                    response = i18n_t('bot.welcome', lang)
                                    response_emoji = "⭐"
                                    response_emoji_file = "kiselgram_premium.webp"
                            else:
                                # Original kiselgram help logic (non-premium bot)
                                if _is_premium_emoji_request(content, incoming_emoji, incoming_file):
                                    response = "💎 Kiselgram Premium — 150⭐ / month, 1200⭐ / year\nTap /premium in Kiselgram or open https://web.kiselgram.ru/telegram-premium/?uid={} — pay with Telegram Stars!".format(message.sender_id)
                                    response_emoji = "⭐"
                                    response_emoji_file = "kiselgram_premium.webp"
                                    response_emoji_size = 128
                                    response_emoji_count = 1
                                elif incoming_file or incoming_emoji:
                                    if incoming_emoji in ('⭐', '⭐️') or (incoming_file and 'kiselgram' in incoming_file):
                                        response = ""
                                        response_emoji = "⭐"
                                        response_emoji_file = "kiselgram_premium.webp"
                                        response_emoji_size = message.emoji_size or 128
                                        response_emoji_count = message.emoji_count or 1
                                    else:
                                        response = ""
                                        response_emoji = incoming_emoji
                                        response_emoji_file = incoming_file
                                        response_emoji_size = message.emoji_size or 96
                                        response_emoji_count = message.emoji_count or 1
                                elif content_lower in ('/start', '/start premium', '/help', 'help', 'привет', 'hi', 'hello'):
                                    response = "🤖 Welcome to Kiselgram Help! I can assist you with groups, channels, and Premium.\n\n💎 Premium: 150⭐/mo | 1200⭐/yr\nSend ⭐ or type /premium — I'll show the Stars payment!"
                                    response_emoji = "⭐"
                                    response_emoji_file = "kiselgram_premium.webp"
                                    response_emoji_size = 96
                                elif 'premium' in content_lower or '/premium' in content_lower or 'премиум' in content_lower:
                                    response = "💎 Kiselgram Premium — pay with Telegram Stars (XTR)!\n\n• 150⭐ — 1 month (300₽)\n• 1200⭐ — 12 months (−17%)\n\nOpen https://web.kiselgram.ru/telegram-premium/?uid={} or message @kiselgram_bot on Telegram /premium".format(message.sender_id)
                                    response_emoji = "⭐"
                                    response_emoji_file = "kiselgram_premium.webp"
                                    response_emoji_size = 128
                                else:
                                    response = "🤖 Welcome to Kiselgram Help! I can assist you with using groups, channels, and other features. What do you need help with?\n\nSend ⭐ for the Premium logo ✨"
                        else:
                            response = "🤖 I'm a bot. How can I help you?"

                        # Build bot response message
                        bot_response = Message(
                            content=response or "",
                            sender_id=bot.id,
                            receiver_id=message.sender_id,
                            chat_id=message.chat_id,
                            timestamp=__import__('datetime').datetime.utcnow(),
                            is_from_telegram=False,
                        )
                        # Attach hero banner on every message for kiselgram_premium (Telegram Stars flow)
                        if bot.username == 'kiselgram_premium':
                            import os, shutil
                            banner_src = os.path.join(os.getcwd(), 'static', 'img', 'premium', 'banner-hero.png')
                            banner_dest_dir = os.path.join(os.getcwd(), 'uploads', 'premium')
                            os.makedirs(banner_dest_dir, exist_ok=True)
                            banner_dest = os.path.join(banner_dest_dir, 'banner-hero.png')
                            if os.path.exists(banner_src):
                                try:
                                    if not os.path.exists(banner_dest):
                                        shutil.copy(banner_src, banner_dest)
                                    bot_response.has_attachment = True
                                    bot_response.file_type = 'image'
                                    bot_response.file_path = 'premium/banner-hero.png'
                                    bot_response.file_name = 'banner-hero.png'
                                    try:
                                        bot_response.file_size = os.path.getsize(banner_dest)
                                    except Exception:
                                        pass
                                except Exception:
                                    pass
                        # Attach emoji if set
                        if response_emoji_file:
                            import os
                            base = os.path.join(os.getcwd(), 'uploads', 'animated_emojis', response_emoji_file)
                            alt = os.path.join(os.getcwd(), 'static', 'stickers', 'animatedemojies', response_emoji_file)
                            alt2 = os.path.join(os.getcwd(), 'static', 'custom_emoji', response_emoji_file)
                            if os.path.exists(base) or os.path.exists(alt) or os.path.exists(alt2):
                                bot_response.emoji = response_emoji or "⭐"
                                bot_response.emoji_file = response_emoji_file
                                bot_response.emoji_size = response_emoji_size
                                bot_response.emoji_count = response_emoji_count
                            else:
                                bot_response.emoji = "⭐"
                                bot_response.emoji_file = "kiselgram_premium.webp"
                                bot_response.emoji_size = 128
                        elif response_emoji:
                            bot_response.emoji = response_emoji
                            bot_response.emoji_file = response_emoji_file or "kiselgram_premium.webp"

                        db.session.add(bot_response)

                db.session.commit()

            time.sleep(5)

        except Exception as e:
            print(f"Bot simulation error: {e}")
            import traceback; traceback.print_exc()
            time.sleep(10)
