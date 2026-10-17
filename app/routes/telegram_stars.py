# app/routes/telegram_stars.py
# Telegram Stars Premium WebApp + Bot webhook
# Payments via Telegram Stars (currency XTR) through VLESS proxy (127.0.0.1:10808/10809)
# Bot token: from env TELEGRAM_BOT_TOKEN or config/kis.toml [telegram] bot_token
# SECURITY: never commit real token – set via env or kis.toml, file is gitignored via config/
# i18n: all messages in config/locales.toml via app/utils/i18n.py (ru/en)

import os
import re
import uuid
import hmac
import hashlib
import logging
from datetime import datetime, timedelta
from urllib.parse import parse_qsl

from flask import Blueprint, request, jsonify, render_template, current_app

from app import db
from app.models import User, UserPremium
from app.utils.helpers import get_current_user, get_current_user_id
from app.bot.telegram_api import (
    get_bot_token, send_message, send_premium_message, send_invoice, create_invoice_link,
    answer_pre_checkout_query, get_me, check_proxy, get_premium_custom_emoji_id, get_custom_emoji_stickers,
)
from app.utils.i18n import t, get_locales, reload_locales

logger = logging.getLogger(__name__)

telegram_stars_bp = Blueprint('telegram_stars', __name__, url_prefix='/telegram-premium')

# ---- Pricing (Stars) ----
def get_prices():
    try:
        cfg_price_m = current_app.config.get('TELEGRAM_STARS_MONTHLY', int(os.environ.get('TELEGRAM_STARS_MONTHLY', '150')))
        cfg_price_y = current_app.config.get('TELEGRAM_STARS_YEARLY', int(os.environ.get('TELEGRAM_STARS_YEARLY', '1200')))
    except Exception:
        cfg_price_m, cfg_price_y = 150, 1200
    return {'monthly': int(cfg_price_m), 'yearly': int(cfg_price_y)}

def get_price_labels(lang='ru'):
    return {
        'monthly': t('invoice.label_monthly', lang),
        'yearly': t('invoice.label_yearly', lang),
    }

def get_lang_from_request(fallback='ru'):
    # ?lang=en, header, Telegram language_code
    lang = request.args.get('lang') or request.args.get('locale')
    if lang and lang.lower() in ('ru','en'):
        return lang.lower()
    al = request.headers.get('Accept-Language','')
    if al.lower().startswith('en'):
        return 'en'
    return fallback

def get_lang_from_tg_user(from_user):
    if isinstance(from_user, dict):
        lc = (from_user.get('language_code') or '').lower()
        if lc.startswith('en'):
            return 'en'
    return 'ru'

# ---- DB model for payments ----

class TelegramStarsPayment(db.Model):
    __tablename__ = 'telegram_stars_payments'
    id = db.Column(db.Integer, primary_key=True)
    payload = db.Column(db.String(128), unique=True, nullable=False, index=True)
    telegram_user_id = db.Column(db.BigInteger, nullable=True)
    telegram_username = db.Column(db.String(80), nullable=True)
    kiselgram_user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True, index=True)
    plan = db.Column(db.String(20), nullable=False, default='monthly')
    amount = db.Column(db.Integer, nullable=False)  # in Stars (XTR)
    currency = db.Column(db.String(10), default='XTR')
    status = db.Column(db.String(20), default='pending')  # pending, paid, cancelled, refunded
    telegram_payment_charge_id = db.Column(db.String(128), nullable=True)
    provider_payment_charge_id = db.Column(db.String(128), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    paid_at = db.Column(db.DateTime, nullable=True)
    invoice_link = db.Column(db.Text, nullable=True)

    kiselgram_user = db.relationship('User', backref='telegram_payments', lazy=True, foreign_keys=[kiselgram_user_id])

    def __repr__(self):
        return f"<TelegramStarsPayment {self.payload} plan={self.plan} status={self.status}>"

# ---- Helpers ----

def _activate_premium(user_id: int, plan: str = 'monthly', payment_method: str = 'telegram_stars', charge_id: str = None):
    """Activate/extend premium for a Kiselgram user. Returns UserPremium."""
    user = User.query.get(user_id)
    if not user:
        raise ValueError(f"User {user_id} not found")
    duration_days = 365 if plan == 'yearly' else 30
    now = datetime.utcnow()
    if not user.premium:
        up = UserPremium(
            user_id=user.id,
            is_premium=True,
            premium_since=now,
            premium_expires_at=now + timedelta(days=duration_days),
            premium_plan=plan,
            premium_auto_renew=False,
            premium_payment_method=payment_method,
        )
        db.session.add(up)
        db.session.flush()
        premium = up
    else:
        base = user.premium.premium_expires_at if user.premium.is_premium and user.premium.premium_expires_at and user.premium.premium_expires_at > now else now
        user.premium.is_premium = True
        if not user.premium.premium_since:
            user.premium.premium_since = now
        user.premium.premium_expires_at = base + timedelta(days=duration_days)
        user.premium.premium_plan = plan
        user.premium.premium_payment_method = payment_method
        premium = user.premium
    if not user.status_emoji:
        user.status_emoji = '⭐'
    db.session.commit()
    logger.info(f"Premium activated for user {user_id} plan {plan} charge {charge_id} expires {premium.premium_expires_at}")
    return premium

def _make_payload(kiselgram_user_id: int, plan: str) -> str:
    nonce = uuid.uuid4().hex[:12]
    return f"kis_premium:{kiselgram_user_id}:{plan}:{nonce}"

def _parse_payload(payload: str):
    try:
        parts = payload.split(':')
        if len(parts) < 4 or parts[0] != 'kis_premium':
            return None
        return {'kiselgram_user_id': int(parts[1]), 'plan': parts[2], 'nonce': parts[3]}
    except Exception:
        return None

def verify_telegram_webapp_init_data(init_data: str, bot_token: str) -> dict | None:
    """Verify Telegram WebApp initData per https://core.telegram.org/bots/web_apps#validating-data-received-via-the-web-app"""
    try:
        parsed = dict(parse_qsl(init_data, strict_parsing=True))
        recv_hash = parsed.pop('hash', None)
        if not recv_hash:
            return None
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc_hash, recv_hash):
            logger.warning("initData hash mismatch")
            return None
        import json
        if 'user' in parsed:
            try:
                parsed['user'] = json.loads(parsed['user'])
            except Exception:
                pass
        return parsed
    except Exception as e:
        logger.warning(f"initData verify error: {e}")
        return None

# ---- Page routes ----

@telegram_stars_bp.route('/', methods=['GET'])
def webapp_page():
    """WebApp page for Telegram. Also accessible as normal web."""
    prices = get_prices()
    lang = get_lang_from_request('ru')
    tr = get_locales().get(lang, get_locales().get('ru', {}))
    webapp_tr = tr.get('webapp', {}) if isinstance(tr, dict) else {}
    premium_cfg = get_locales().get('premium', {})
    custom_emoji_id = premium_cfg.get('custom_emoji_id') or get_premium_custom_emoji_id()
    return render_template('telegram_premium/index.html', prices=prices, lang=lang, tr=webapp_tr, t=t, custom_emoji_id=custom_emoji_id, premium_cfg=premium_cfg)

@telegram_stars_bp.route('/webapp', methods=['GET'])
def webapp_alias():
    return webapp_page()

# ---- API: prices ----

@telegram_stars_bp.route('/api/prices', methods=['GET'])
def api_prices():
    prices = get_prices()
    lang = get_lang_from_request('ru')
    labels = get_price_labels(lang)
    return jsonify({'success': True, 'prices': prices, 'currency': 'XTR', 'labels': labels, 'lang': lang})

@telegram_stars_bp.route('/api/premium-assets', methods=['GET'])
def api_premium_assets():
    """Return premium logo, banners and custom emoji for clients."""
    lang = get_lang_from_request('ru')
    premium_cfg = get_locales().get('premium', {})
    custom_id = premium_cfg.get('custom_emoji_id') or get_premium_custom_emoji_id()
    return jsonify({
        'success': True,
        'custom_emoji_id': custom_id,
        'fallback_emoji': premium_cfg.get('fallback_emoji', '⭐'),
        'logo': premium_cfg.get('logo_path', '/static/img/premium/logo-512.png'),
        'logo_svg': premium_cfg.get('logo_svg', '/static/img/premium/logo.svg'),
        'custom_emoji': premium_cfg.get('custom_emoji_path', '/static/custom_emoji/kiselgram_premium.webp'),
        'banners': {
            'hero': premium_cfg.get('banner_hero', '/static/img/premium/banner-hero.png'),
            'pay': premium_cfg.get('banner_pay', '/static/img/premium/banner-pay.png'),
            'success': premium_cfg.get('banner_success', '/static/img/premium/banner-success.png'),
            'webapp': premium_cfg.get('banner_webapp', '/static/img/premium/banner-webapp.png'),
        },
        'lang': lang,
    })

@telegram_stars_bp.route('/api/custom-emoji/<custom_id>', methods=['GET'])
def api_get_custom_emoji(custom_id):
    token = get_bot_token()
    if not token:
        return jsonify({'success': False, 'error': 'Bot token not configured'}), 500
    r = get_custom_emoji_stickers(token, [custom_id])
    return jsonify({'success': r.get('ok', False), 'result': r.get('result'), 'raw': r})

@telegram_stars_bp.route('/api/locales', methods=['GET'])
def api_locales():
    lang = get_lang_from_request('ru')
    locales = get_locales()
    return jsonify({'success': True, 'lang': lang, 'locales': locales})

@telegram_stars_bp.route('/api/reload-locales', methods=['POST'])
def api_reload_locales():
    # admin or local only
    user = get_current_user()
    if not user or not getattr(user, 'is_admin', False):
        # allow if from localhost without auth in debug
        if request.remote_addr not in ('127.0.0.1','::1') and not current_app.config.get('DEBUG'):
            return jsonify({'success': False, 'error': 'Admin only'}), 403
    reload_locales()
    return jsonify({'success': True, 'locales': get_locales()})

# ---- API: diagnostics ----

@telegram_stars_bp.route('/api/diagnostics', methods=['GET'])
def api_diagnostics():
    token = get_bot_token()
    masked = (token[:6] + '…'+ token[-4:]) if token else 'NOT SET'
    has_token = bool(token)
    proxy = check_proxy()
    bot_info = None
    if has_token:
        bot_info = get_me(token)
    premium_cfg = get_locales().get('premium', {})
    return jsonify({
        'success': True,
        'token_masked': masked,
        'has_token': has_token,
        'proxy': proxy,
        'bot_info': bot_info,
        'prices': get_prices(),
        'lang': get_lang_from_request('ru'),
        'custom_emoji_id': premium_cfg.get('custom_emoji_id') or get_premium_custom_emoji_id(),
        'premium_assets': {
            'logo': premium_cfg.get('logo_path', '/static/img/premium/logo-512.png'),
            'custom_emoji': premium_cfg.get('custom_emoji_path', '/static/custom_emoji/kiselgram_premium.webp'),
        },
    })

@telegram_stars_bp.route('/api/check/<int:kiselgram_user_id>', methods=['GET'])
def api_check(kiselgram_user_id):
    user = User.query.get(kiselgram_user_id)
    if not user:
        lang = get_lang_from_request('ru')
        return jsonify({'success': False, 'error': t('api.error_user_not_found', lang)}), 404
    is_premium = user.premium.is_premium if user.premium else False
    expires = user.premium.premium_expires_at if user.premium else None
    if is_premium and expires and datetime.utcnow() > expires:
        user.premium.is_premium = False
        db.session.commit()
        is_premium = False
        expires = None
    return jsonify({
        'success': True,
        'is_premium': is_premium,
        'expires_at': expires.isoformat() if expires else None,
        'kiselgram_user_id': user.id,
        'username': user.username,
    })

# ---- API: create invoice link (WebApp flow) ----

@telegram_stars_bp.route('/api/create-invoice-link', methods=['POST'])
def api_create_invoice_link():
    """Create a Telegram Stars invoice link for WebApp.
    Auth: Kiselgram Bearer session OR Telegram WebApp initData + kiselgram user id.
    Body JSON: {plan: monthly|yearly, kiselgram_user_id?:int, initData?:str, lang?:str}
    Returns: {invoice_link, payload}
    """
    data = request.get_json() or {}
    lang = (data.get('lang') or get_lang_from_request('ru'))
    plan = (data.get('plan') or 'monthly').lower()
    if plan not in ('monthly', 'yearly'):
        return jsonify({'success': False, 'error': t('api.error_plan', lang)}), 400

    kiselgram_user_id = None
    cur = get_current_user()
    if cur:
        kiselgram_user_id = cur.id
    else:
        if data.get('kiselgram_user_id'):
            try:
                kiselgram_user_id = int(data.get('kiselgram_user_id'))
            except Exception:
                pass
        init_data = data.get('initData') or request.headers.get('X-Telegram-Init-Data') or ''
        if not kiselgram_user_id and init_data:
            token = get_bot_token()
            if token:
                parsed = verify_telegram_webapp_init_data(init_data, token)
                if parsed and isinstance(parsed.get('user'), dict):
                    tg_id = parsed['user'].get('id')
                    if tg_id:
                        u = User.query.filter_by(telegram_chat_id=str(tg_id)).first()
                        if u:
                            kiselgram_user_id = u.id

    if not kiselgram_user_id:
        return jsonify({'success': False, 'error': t('api.error_not_auth', lang)}), 401

    user = User.query.get(kiselgram_user_id)
    if not user:
        return jsonify({'success': False, 'error': t('api.error_user_not_found', lang)}), 404

    token = get_bot_token()
    if not token:
        return jsonify({'success': False, 'error': t('api.error_token_not_configured', lang)}), 500

    prices_cfg = get_prices()
    amount = prices_cfg[plan]
    payload = _make_payload(kiselgram_user_id, plan)

    payment = TelegramStarsPayment(
        payload=payload,
        kiselgram_user_id=kiselgram_user_id,
        telegram_user_id=None,
        plan=plan,
        amount=amount,
        currency='XTR',
        status='pending',
    )
    db.session.add(payment)
    db.session.commit()

    # Use localized title/desc
    title = t('invoice.title', lang)
    desc = t(f'invoice.desc_{plan}', lang)
    labels = get_price_labels(lang)
    label = labels.get(plan, desc)
    resp = create_invoice_link(
        token,
        title=title,
        description=desc,
        payload_str=payload,
        currency='XTR',
        prices=[{'label': label, 'amount': amount}],
    )
    if not resp.get('ok'):
        payment.status = 'cancelled'
        db.session.commit()
        return jsonify({'success': False, 'error': resp.get('description') or resp.get('error') or t('api.error_invoice_failed', lang), 'raw': resp}), 502

    link = resp.get('result')
    payment.invoice_link = link
    db.session.commit()

    return jsonify({
        'success': True,
        'invoice_link': link,
        'payload': payload,
        'plan': plan,
        'amount': amount,
        'currency': 'XTR',
        'kiselgram_user_id': kiselgram_user_id,
        'lang': lang,
    })

# ---- API: send invoice directly to a Telegram chat (bot chat flow) ----

@telegram_stars_bp.route('/api/send-invoice', methods=['POST'])
def api_send_invoice():
    data = request.get_json() or {}
    lang = (data.get('lang') or get_lang_from_request('ru'))
    plan = (data.get('plan') or 'monthly').lower()
    if plan not in ('monthly', 'yearly'):
        return jsonify({'success': False, 'error': t('api.error_plan', lang)}), 400
    tg_chat_id = data.get('telegram_chat_id') or data.get('chat_id')
    if not tg_chat_id:
        return jsonify({'success': False, 'error': t('api.error_chat_required', lang)}), 400
    try:
        tg_chat_id = int(tg_chat_id)
    except Exception:
        return jsonify({'success': False, 'error': t('api.error_invalid_chat', lang)}), 400

    kiselgram_user_id = None
    cur = get_current_user()
    if cur:
        kiselgram_user_id = cur.id
    if data.get('kiselgram_user_id'):
        try:
            kiselgram_user_id = int(data['kiselgram_user_id'])
        except Exception:
            pass
    if not kiselgram_user_id:
        u = User.query.filter_by(telegram_chat_id=str(tg_chat_id)).first()
        if u:
            kiselgram_user_id = u.id
    if not kiselgram_user_id:
        return jsonify({'success': False, 'error': t('api.error_kisel_required', lang)}), 400

    token = get_bot_token()
    if not token:
        return jsonify({'success': False, 'error': t('api.error_token_not_configured', lang)}), 500

    prices_cfg = get_prices()
    amount = prices_cfg[plan]
    payload = _make_payload(kiselgram_user_id, plan)
    payment = TelegramStarsPayment(
        payload=payload,
        kiselgram_user_id=kiselgram_user_id,
        telegram_user_id=tg_chat_id,
        plan=plan,
        amount=amount,
        currency='XTR',
        status='pending',
    )
    db.session.add(payment)
    db.session.commit()

    title = t('invoice.title', lang)
    desc = t(f'invoice.desc_{plan}', lang)
    label = get_price_labels(lang).get(plan, desc)
    resp = send_invoice(token, tg_chat_id, title, desc, payload, 'XTR', [{'label': label, 'amount': amount}])
    if not resp.get('ok'):
        payment.status = 'cancelled'
        db.session.commit()
        return jsonify({'success': False, 'error': resp.get('description') or resp.get('error'), 'raw': resp}), 502
    return jsonify({'success': True, 'payload': payload, 'telegram_message': resp.get('result')})

# ---- Webhook: Telegram updates ----

def _handle_successful_payment(payment_payload: str, from_user: dict, charge: dict):
    info = _parse_payload(payment_payload)
    if not info:
        logger.warning(f"Unknown payload {payment_payload}")
        return False
    kiselgram_user_id = info['kiselgram_user_id']
    plan = info['plan']
    telegram_user_id = from_user.get('id') if from_user else None
    charge_id = charge.get('telegram_payment_charge_id') or charge.get('provider_payment_charge_id') or ''
    lang = get_lang_from_tg_user(from_user)

    payment = TelegramStarsPayment.query.filter_by(payload=payment_payload).first()
    if not payment:
        prices_cfg = get_prices()
        payment = TelegramStarsPayment(
            payload=payment_payload,
            kiselgram_user_id=kiselgram_user_id,
            telegram_user_id=telegram_user_id,
            plan=plan,
            amount=charge.get('total_amount') or prices_cfg.get(plan, 0),
            currency=charge.get('currency') or 'XTR',
            status='paid',
            telegram_payment_charge_id=charge_id,
            paid_at=datetime.utcnow(),
        )
        db.session.add(payment)
    else:
        payment.status = 'paid'
        payment.telegram_user_id = telegram_user_id
        payment.telegram_username = from_user.get('username') if from_user else None
        payment.telegram_payment_charge_id = charge.get('telegram_payment_charge_id')
        payment.provider_payment_charge_id = charge.get('provider_payment_charge_id')
        payment.paid_at = datetime.utcnow()

    user = User.query.get(kiselgram_user_id)
    if user and telegram_user_id and not user.telegram_chat_id:
        user.telegram_chat_id = str(telegram_user_id)
        if from_user.get('username') and not user.telegram_username:
            user.telegram_username = from_user.get('username')

    db.session.commit()

    try:
        _activate_premium(kiselgram_user_id, plan, payment_method='telegram_stars', charge_id=charge_id)
    except Exception as e:
        logger.exception(f"Premium activation failed for {kiselgram_user_id}: {e}")
        return False
    return True

@telegram_stars_bp.route('/webhook', methods=['POST'])
@telegram_stars_bp.route('/webhook/<path:token>', methods=['POST'])
def telegram_webhook(token=None):
    expected_token = get_bot_token()
    if not expected_token:
        return jsonify({'success': False, 'error': 'bot token not configured'}), 500

    if token:
        if token != expected_token:
            return jsonify({'success': False, 'error': 'invalid webhook token'}), 403
    else:
        secret = request.headers.get('X-Telegram-Bot-Api-Secret-Token')
        webhook_secret = os.environ.get('TELEGRAM_WEBHOOK_SECRET') or current_app.config.get('TELEGRAM_WEBHOOK_SECRET')
        if webhook_secret and secret != webhook_secret:
            return jsonify({'success': False, 'error': 'invalid secret'}), 403
        logger.info("Webhook called without token in URL – ensure you set webhook to /webhook/<token>")

    update = request.get_json(silent=True) or {}
    logger.info(f"Webhook update: {str(update)[:2000]}")

    if 'pre_checkout_query' in update:
        pcq = update['pre_checkout_query']
        qid = pcq.get('id')
        payload = pcq.get('invoice_payload', '')
        info = _parse_payload(payload)
        lang = get_lang_from_tg_user(pcq.get('from', {}))
        if not info:
            answer_pre_checkout_query(expected_token, qid, ok=False, error_message=t('bot.error_invalid_payload', lang))
            return jsonify({'ok': True})
        user = User.query.get(info['kiselgram_user_id'])
        if not user:
            answer_pre_checkout_query(expected_token, qid, ok=False, error_message=t('bot.error_user_not_found', lang))
            return jsonify({'ok': True})
        expected_amount = get_prices().get(info['plan'])
        if expected_amount and pcq.get('total_amount') != expected_amount:
            answer_pre_checkout_query(expected_token, qid, ok=False, error_message=t('bot.error_price_changed', lang, amount=expected_amount))
            return jsonify({'ok': True})
        payment = TelegramStarsPayment.query.filter_by(payload=payload).first()
        if payment and pcq.get('from'):
            payment.telegram_user_id = pcq['from'].get('id')
            payment.telegram_username = pcq['from'].get('username')
            db.session.commit()
        answer_pre_checkout_query(expected_token, qid, ok=True)
        return jsonify({'ok': True})

    msg = update.get('message') or update.get('edited_message')
    if msg and 'successful_payment' in msg:
        sp = msg['successful_payment']
        payload = sp.get('invoice_payload', '')
        from_user = msg.get('from') or {}
        lang = get_lang_from_tg_user(from_user)
        ok = _handle_successful_payment(payload, from_user, sp)
        if ok:
            info = _parse_payload(payload)
            if info:
                chat_id = msg.get('chat', {}).get('id') or from_user.get('id')
                if chat_id:
                    plan = info['plan']
                    days = 365 if plan == 'yearly' else 30
                    try:
                        send_premium_message(expected_token, chat_id,
                            t('bot.payment_success', lang, days=days, plan=plan),
                            parse_mode="HTML")
                    except Exception as e:
                        logger.warning(f"Failed to send success message: {e}")
        return jsonify({'ok': True})

    if msg and 'text' in msg:
        text = (msg.get('text') or '').strip()
        chat_id = msg.get('chat', {}).get('id')
        from_user = msg.get('from') or {}
        lang = get_lang_from_tg_user(from_user)
        if not chat_id:
            return jsonify({'ok': True})

        if text.startswith('/start'):
            parts = text.split(maxsplit=1)
            param = parts[1] if len(parts) > 1 else ''
            if param.startswith('premium_') or param.startswith('kis_') or param.startswith('kisel_'):
                m = re.search(r'(\d+)', param)
                if m:
                    try:
                        kg_id = int(m.group(1))
                        u = User.query.get(kg_id)
                        if u:
                            if from_user.get('id'):
                                existing = User.query.filter_by(telegram_chat_id=str(from_user['id'])).first()
                                if not existing or existing.id == u.id:
                                    u.telegram_chat_id = str(from_user['id'])
                                    if from_user.get('username'):
                                        u.telegram_username = from_user['username']
                                    db.session.commit()
                            send_premium_message(expected_token, chat_id,
                                t('bot.linked', lang, name=u.display_name or u.username),
                                parse_mode="HTML")
                            prices = get_prices()
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": t('bot.inline_monthly', lang, amount=prices['monthly']), "callback_data": f"buy_monthly_{kg_id}"}],
                                    [{"text": t('bot.inline_yearly', lang, amount=prices['yearly']), "callback_data": f"buy_yearly_{kg_id}"}],
                                    [{"text": t('bot.inline_open_webapp', lang), "web_app": {"url": request.host_url.rstrip('/') + "/telegram-premium/?uid=" + str(kg_id) + "&lang=" + lang}}]
                                ]
                            }
                            send_premium_message(expected_token, chat_id, t('bot.choose_tariff', lang), reply_markup=keyboard)
                            return jsonify({'ok': True})
                    except Exception as e:
                        logger.warning(f"/start param error {e}")

            send_premium_message(expected_token, chat_id,
                t('bot.welcome', lang),
                parse_mode="HTML")
            return jsonify({'ok': True})

        if text.startswith('/premium'):
            linked = User.query.filter_by(telegram_chat_id=str(from_user.get('id'))).first() if from_user.get('id') else None
            if not linked:
                send_premium_message(expected_token, chat_id,
                    t('bot.not_linked', lang),
                    parse_mode="HTML")
                return jsonify({'ok': True})
            prices = get_prices()
            keyboard = {
                "inline_keyboard": [
                    [{"text": t('bot.inline_monthly', lang, amount=prices['monthly']), "callback_data": f"buy_monthly_{linked.id}"}],
                    [{"text": t('bot.inline_yearly', lang, amount=prices['yearly']), "callback_data": f"buy_yearly_{linked.id}"}],
                ]
            }
            send_premium_message(expected_token, chat_id,
                t('bot.premium_desc', lang),
                parse_mode="HTML", reply_markup=keyboard)
            return jsonify({'ok': True})

        if text.startswith('/status'):
            linked = User.query.filter_by(telegram_chat_id=str(from_user.get('id'))).first() if from_user.get('id') else None
            if not linked:
                send_premium_message(expected_token, chat_id, t('bot.not_linked_status', lang))
                return jsonify({'ok': True})
            is_p = linked.premium.is_premium if linked.premium else False
            exp = linked.premium.premium_expires_at if linked.premium else None
            if is_p and exp:
                send_premium_message(expected_token, chat_id, t('bot.premium_active', lang, date=exp.strftime('%d.%m.%Y')), parse_mode="HTML")
            else:
                send_premium_message(expected_token, chat_id, t('bot.premium_inactive', lang))
            return jsonify({'ok': True})

        if text.startswith('/help'):
            send_premium_message(expected_token, chat_id,
                t('bot.help', lang),
                parse_mode="HTML")
            return jsonify({'ok': True})

    if 'callback_query' in update:
        cq = update['callback_query']
        data = cq.get('data', '')
        cq_id = cq.get('id')
        from_user = cq.get('from') or {}
        lang = get_lang_from_tg_user(from_user)
        chat_id = cq.get('message', {}).get('chat', {}).get('id')
        try:
            from app.bot.telegram_api import api_call
            api_call(expected_token, "answerCallbackQuery", {"callback_query_id": cq_id})
        except Exception:
            pass
        if data.startswith('buy_monthly_') or data.startswith('buy_yearly_'):
            plan = 'monthly' if 'monthly' in data else 'yearly'
            m = re.search(r'(\d+)', data)
            kg_id = int(m.group(1)) if m else None
            if not kg_id:
                linked = User.query.filter_by(telegram_chat_id=str(from_user.get('id'))).first() if from_user.get('id') else None
                kg_id = linked.id if linked else None
            if not kg_id or not chat_id:
                return jsonify({'ok': True})
            prices_cfg = get_prices()
            amount = prices_cfg[plan]
            payload = _make_payload(kg_id, plan)
            payment = TelegramStarsPayment(payload=payload, kiselgram_user_id=kg_id, telegram_user_id=from_user.get('id'), plan=plan, amount=amount, currency='XTR', status='pending')
            db.session.add(payment)
            db.session.commit()
            title = t('invoice.title', lang)
            desc = t(f'invoice.desc_{plan}', lang)
            label = get_price_labels(lang).get(plan, desc)
            send_invoice(expected_token, chat_id, title, desc, payload, 'XTR', [{'label': label, 'amount': amount}])
            return jsonify({'ok': True})

    return jsonify({'ok': True})

# ---- Admin: set / delete webhook helpers ----

@telegram_stars_bp.route('/api/webhook/set', methods=['POST'])
def api_set_webhook():
    user = get_current_user()
    if not user or not getattr(user, 'is_admin', False):
        return jsonify({'success': False, 'error': 'Admin only'}), 403
    data = request.get_json() or {}
    base_url = data.get('base_url') or request.host_url.rstrip('/')
    if not base_url.startswith('https://'):
        return jsonify({'success': False, 'error': 'base_url must be https://'}), 400
    token = get_bot_token()
    if not token:
        return jsonify({'success': False, 'error': 'Bot token not set'}), 500
    url = f"{base_url}/telegram-premium/webhook/{token}"
    secret = data.get('secret_token')
    from app.bot.telegram_api import set_webhook as _set
    resp = _set(token, url, secret)
    return jsonify({'success': resp.get('ok', False), 'raw': resp, 'webhook_url': url})

@telegram_stars_bp.route('/api/webhook/delete', methods=['POST'])
def api_delete_webhook():
    user = get_current_user()
    if not user or not getattr(user, 'is_admin', False):
        return jsonify({'success': False, 'error': 'Admin only'}), 403
    token = get_bot_token()
    if not token:
        return jsonify({'success': False, 'error': 'Bot token not set'}), 500
    from app.bot.telegram_api import delete_webhook as _del
    resp = _del(token)
    return jsonify({'success': resp.get('ok', False), 'raw': resp})

@telegram_stars_bp.route('/api/webhook/info', methods=['GET'])
def api_webhook_info():
    token = get_bot_token()
    if not token:
        return jsonify({'success': False, 'error': 'Bot token not set'}), 500
    from app.bot.telegram_api import get_webhook_info as _info
    resp = _info(token)
    return jsonify({'success': True, 'raw': resp})
