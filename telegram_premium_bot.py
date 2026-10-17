#!/usr/bin/env python3
"""
Telegram Premium Bot — polling via VLESS proxy
Uses SOCKS5 127.0.0.1:10808 / HTTP 127.0.0.1:10809 from config/vless.json

Bot token: env TELEGRAM_BOT_TOKEN or config/kis.toml [telegram] bot_token
  e.g. YOUR_BOT_TOKEN_HERE  (set via env, do NOT commit)

Usage:
  # 1) Start VLESS (Xray):
  #    xray run -c config/vless.json
  #    # or: ./xray -config config/vless.json  (darwin binary from https://github.com/XTLS/Xray-core)
  # 2) Run bot:
  #    TELEGRAM_BOT_TOKEN='853862...' python telegram_premium_bot.py
  #    # or with Flask context (activates premium in DB):
  #    python telegram_premium_bot.py --with-flask
  # 3) Or set token in config/kis.toml:
  #    [telegram]
  #    bot_token = "YOUR_BOT_TOKEN_HERE"

Polling handles:
  /start, /premium, /status, /help
  inline keyboard -> sendInvoice (Stars XTR)
  pre_checkout_query -> answer ok
  successful_payment -> activate UserPremium + link telegram_chat_id

For production webhook mode, use /telegram-premium/webhook/<token> route instead (no polling).
"""

import os
import sys
import time
import re
import argparse
import logging
from datetime import datetime, timedelta

# Ensure project root on path when run as script
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("premium_bot")

os.environ.setdefault("TELEGRAM_FORCE_PROXY", "1")  # force VLESS by default

# Lazy import so --help works even without Flask installed
def get_token_and_prices(with_flask=False):
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("BOT_TOKEN")
    if not token and with_flask:
        try:
            from app import create_app
            app = create_app()
            with app.app_context():
                from app.bot.telegram_api import get_bot_token
                token = get_bot_token(app)
        except Exception as e:
            log.warning(f"Flask token resolve failed: {e}")
    if not token:
        try:
            import tomli
            cfg = os.path.join(ROOT, "config", "kis.toml")
            if os.path.exists(cfg):
                with open(cfg, "rb") as f:
                    data = tomli.load(f)
                    t = data.get("telegram", {}).get("bot_token", "")
                    if t and t != "YOUR_BOT_TOKEN_HERE":
                        token = t
        except Exception:
            pass
    prices = {"monthly": 150, "yearly": 1200}
    if with_flask:
        try:
            from app import create_app
            app = create_app()
            with app.app_context():
                from app.routes.telegram_stars import get_prices
                prices = get_prices()
        except Exception:
            pass
    else:
        prices["monthly"] = int(os.environ.get("TELEGRAM_STARS_MONTHLY", "150"))
        prices["yearly"] = int(os.environ.get("TELEGRAM_STARS_YEARLY", "1200"))
    return token, prices

def main():
    parser = argparse.ArgumentParser(description="Kiselgram Premium Telegram Stars bot (polling via VLESS)")
    parser.add_argument("--with-flask", action="store_true", help="Use Flask DB to activate premium (required for payments)")
    parser.add_argument("--no-proxy", action="store_true", help="Disable VLESS proxy (direct)")
    args = parser.parse_args()

    if args.no_proxy:
        os.environ["TELEGRAM_FORCE_PROXY"] = "0"

    token, prices = get_token_and_prices(args.with_flask)
    if not token:
        log.error("TELEGRAM_BOT_TOKEN not set. Set env or config/kis.toml [telegram] bot_token")
        log.error("Example: TELEGRAM_BOT_TOKEN='YOUR_BOT_TOKEN_HERE' python telegram_premium_bot.py --with-flask")
        sys.exit(1)

    masked = token[:6] + "…" + token[-4:]
    log.info(f"Token: {masked}  Prices: {prices}  Proxy: {'VLESS' if os.environ.get('TELEGRAM_FORCE_PROXY')=='1' else 'direct'}")
    log.info(f"VLESS config: {os.path.join(ROOT,'config','vless.json')}  (run: xray run -c config/vless.json)")

    # Imports after token check
    from app.bot.telegram_api import (
        get_me, send_message, send_invoice, answer_pre_checkout_query,
        get_updates, check_proxy
    )

    log.info(f"Proxy check: {check_proxy()}")

    # Optional Flask for DB
    flask_app = None
    if args.with_flask:
        from app import create_app
        flask_app = create_app()
        log.info("Flask DB enabled – payments will activate premium")
    else:
        log.warning("Running WITHOUT Flask DB – payments will be acknowledged but NOT activated. Use --with-flask")

    # getMe
    me = get_me(token)
    if not me.get("ok"):
        log.error(f"getMe failed: {me}  – check token and VLESS (is xray running?)")
        if "Unauthorized" in str(me):
            sys.exit(1)
    else:
        log.info(f"Bot: @{me['result'].get('username')}  id={me['result'].get('id')}")

    # helpers that need flask_app
    def activate(user_id, plan, charge_id=None):
        if not flask_app:
            log.info(f"[DRY] Would activate premium user={user_id} plan={plan}")
            return
        with flask_app.app_context():
            from app.routes.telegram_stars import _activate_premium, TelegramStarsPayment
            from app.models import User
            try:
                u = User.query.get(user_id)
                if not u:
                    log.warning(f"User {user_id} not found – cannot activate")
                    return
                _activate_premium(user_id, plan, payment_method="telegram_stars", charge_id=charge_id)
                log.info(f"Activated premium for {user_id} plan {plan}")
            except Exception as e:
                log.exception(f"Activate failed: {e}")

    def make_payload(kisel_id, plan):
        import uuid
        return f"kis_premium:{kisel_id}:{plan}:{uuid.uuid4().hex[:12]}"

    def parse_payload(p):
        parts = p.split(":")
        if len(parts) < 4 or parts[0] != "kis_premium":
            return None
        return {"kiselgram_user_id": int(parts[1]), "plan": parts[2], "nonce": parts[3]}

    offset = 0
    log.info("Polling getUpdates…  Ctrl+C to stop")
    while True:
        try:
            data = get_updates(token, offset=offset, timeout=30)
            if not data.get("ok"):
                # 409 = another getUpdates running, 401 = bad token
                log.warning(f"getUpdates: {data}")
                time.sleep(5)
                continue
            for upd in data.get("result", []):
                offset = max(offset, upd.get("update_id", 0) + 1)

                # pre_checkout_query
                if "pre_checkout_query" in upd:
                    pcq = upd["pre_checkout_query"]
                    qid = pcq["id"]
                    payload = pcq.get("invoice_payload", "")
                    info = parse_payload(payload)
                    if not info:
                        answer_pre_checkout_query(token, qid, ok=False, error_message="Bad payload")
                        continue
                    # verify price
                    exp = prices.get(info["plan"])
                    if exp and pcq.get("total_amount") != exp:
                        answer_pre_checkout_query(token, qid, ok=False, error_message=f"Price changed {exp}")
                        continue
                    if flask_app:
                        # verify user exists
                        with flask_app.app_context():
                            from app.models import User
                            if not User.query.get(info["kiselgram_user_id"]):
                                answer_pre_checkout_query(token, qid, ok=False, error_message="User not found")
                                continue
                    answer_pre_checkout_query(token, qid, ok=True)
                    log.info(f"pre_checkout ok {payload}")
                    continue

                msg = upd.get("message") or upd.get("edited_message")
                if msg and "successful_payment" in msg:
                    sp = msg["successful_payment"]
                    payload = sp.get("invoice_payload", "")
                    info = parse_payload(payload)
                    chat_id = msg.get("chat", {}).get("id")
                    frm = msg.get("from", {})
                    log.info(f"Payment success payload={payload} from={frm.get('id')} amount={sp.get('total_amount')}")
                    if info:
                        # record + activate
                        if flask_app:
                            with flask_app.app_context():
                                from app.routes.telegram_stars import TelegramStarsPayment
                                from app.models import User
                                pay = TelegramStarsPayment.query.filter_by(payload=payload).first()
                                if not pay:
                                    pay = TelegramStarsPayment(
                                        payload=payload,
                                        kiselgram_user_id=info["kiselgram_user_id"],
                                        telegram_user_id=frm.get("id"),
                                        telegram_username=frm.get("username"),
                                        plan=info["plan"],
                                        amount=sp.get("total_amount"),
                                        currency=sp.get("currency"),
                                        status="paid",
                                        telegram_payment_charge_id=sp.get("telegram_payment_charge_id"),
                                        provider_payment_charge_id=sp.get("provider_payment_charge_id"),
                                        paid_at=datetime.utcnow(),
                                    )
                                    flask_app.extensions['sqlalchemy'].db.session.add(pay)
                                else:
                                    pay.status = "paid"
                                    pay.telegram_user_id = frm.get("id")
                                    pay.paid_at = datetime.utcnow()
                                    pay.telegram_payment_charge_id = sp.get("telegram_payment_charge_id")
                                # link telegram_chat_id
                                u = User.query.get(info["kiselgram_user_id"])
                                if u and frm.get("id") and not u.telegram_chat_id:
                                    u.telegram_chat_id = str(frm["id"])
                                    if frm.get("username"):
                                        u.telegram_username = frm["username"]
                                flask_app.extensions['sqlalchemy'].db.session.commit()
                        activate(info["kiselgram_user_id"], info["plan"], sp.get("telegram_payment_charge_id"))
                        if chat_id:
                            days = 365 if info["plan"] == "yearly" else 30
                            send_message(token, chat_id, f"✅ <b>Оплата получена!</b>\nPremium на <b>{days} дней</b> ({info['plan']}) активирован ✨", parse_mode="HTML")
                    else:
                        if chat_id:
                            send_message(token, chat_id, "✅ Payment received (unknown payload) – contact support")
                    continue

                if msg and "text" in msg:
                    text = (msg["text"] or "").strip()
                    chat_id = msg["chat"]["id"]
                    frm = msg.get("from", {})
                    if text.startswith("/start"):
                        parts = text.split(maxsplit=1)
                        param = parts[1] if len(parts) > 1 else ""
                        if param and re.search(r"\d+", param):
                            m = re.search(r"(\d+)", param)
                            kg_id = int(m.group(1))
                            if flask_app:
                                with flask_app.app_context():
                                    from app.models import User
                                    u = User.query.get(kg_id)
                                    if u:
                                        if frm.get("id"):
                                            ex = User.query.filter_by(telegram_chat_id=str(frm["id"])).first()
                                            if not ex or ex.id == u.id:
                                                u.telegram_chat_id = str(frm["id"])
                                                if frm.get("username"):
                                                    u.telegram_username = frm["username"]
                                                from app import db as _db
                                                _db.session.commit()
                                        kb = {"inline_keyboard": [[{"text": f"⭐ {prices['monthly']} — 1 мес", "callback_data": f"buy_monthly_{kg_id}"}], [{"text": f"⭐ {prices['yearly']} — 12 мес", "callback_data": f"buy_yearly_{kg_id}"}]]}
                                        send_message(token, chat_id, f"👋 Привет, <b>{u.display_name or u.username}</b>! Telegram привязан. /premium — оплатить ⭐", parse_mode="HTML", reply_markup=kb)
                                        continue
                        send_message(token, chat_id, "👋 <b>Kiselgram Premium Bot</b>\n/premium — купить ⭐\n/status — статус\n/help — помощь", parse_mode="HTML")
                    elif text.startswith("/premium"):
                        linked = None
                        if flask_app:
                            with flask_app.app_context():
                                from app.models import User
                                linked = User.query.filter_by(telegram_chat_id=str(frm.get("id"))).first() if frm.get("id") else None
                                if linked:
                                    kb = {"inline_keyboard": [[{"text": f"⭐ {prices['monthly']} — 1 мес", "callback_data": f"buy_monthly_{linked.id}"}], [{"text": f"⭐ {prices['yearly']} — 12 мес", "callback_data": f"buy_yearly_{linked.id}"}]]}
                                    send_message(token, chat_id, f"💎 <b>Kiselgram Premium</b> ⭐\nВыбери тариф:", parse_mode="HTML", reply_markup=kb)
                                    continue
                        send_message(token, chat_id, "🔗 Привяжи Telegram: открой Kiselgram → Premium → Оплатить звёздами")
                    elif text.startswith("/status"):
                        if flask_app and frm.get("id"):
                            with flask_app.app_context():
                                from app.models import User
                                linked = User.query.filter_by(telegram_chat_id=str(frm["id"])).first()
                                if linked and linked.premium and linked.premium.is_premium:
                                    exp = linked.premium.premium_expires_at
                                    send_message(token, chat_id, f"⭐ Premium до {exp.strftime('%d.%m.%Y') if exp else '?'}")
                                else:
                                    send_message(token, chat_id, "Нет Premium. /premium — купить ⭐")
                        else:
                            send_message(token, chat_id, "Нет данных")
                    elif text.startswith("/help"):
                        send_message(token, chat_id, "ℹ️ /premium — купить ⭐\n/status — статус\nWebApp: Kiselgram → Premium → Оплатить звёздами")

                if "callback_query" in upd:
                    cq = upd["callback_query"]
                    cq_id = cq["id"]
                    frm = cq.get("from", {})
                    msg_cq = cq.get("message", {})
                    chat_id = msg_cq.get("chat", {}).get("id")
                    data_cb = cq.get("data", "")
                    # answer
                    try:
                        from app.bot.telegram_api import api_call
                        api_call(token, "answerCallbackQuery", {"callback_query_id": cq_id})
                    except Exception:
                        pass
                    if data_cb.startswith("buy_monthly_") or data_cb.startswith("buy_yearly_"):
                        plan = "monthly" if "monthly" in data_cb else "yearly"
                        m = re.search(r"(\d+)", data_cb)
                        kg_id = int(m.group(1)) if m else None
                        if not kg_id and frm.get("id") and flask_app:
                            with flask_app.app_context():
                                from app.models import User
                                u = User.query.filter_by(telegram_chat_id=str(frm["id"])).first()
                                if u:
                                    kg_id = u.id
                        if kg_id and chat_id:
                            payload = make_payload(kg_id, plan)
                            if flask_app:
                                with flask_app.app_context():
                                    from app.routes.telegram_stars import TelegramStarsPayment
                                    from app import db as _db
                                    p = TelegramStarsPayment(payload=payload, kiselgram_user_id=kg_id, telegram_user_id=frm.get("id"), plan=plan, amount=prices[plan], currency="XTR", status="pending")
                                    _db.session.add(p)
                                    _db.session.commit()
                            desc = "Kiselgram Premium — 1 мес" if plan == "monthly" else "Kiselgram Premium — 12 мес"
                            send_invoice(token, chat_id, "Kiselgram Premium", desc, payload, "XTR", [{"label": desc, "amount": prices[plan]}])
                            log.info(f"Sent invoice {plan} to {chat_id} payload {payload}")

        except KeyboardInterrupt:
            log.info("Stopped")
            break
        except Exception as e:
            log.exception(f"Loop error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
