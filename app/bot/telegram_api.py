# app/bot/telegram_api.py
# Telegram Bot API wrapper routing via VLESS socks/http proxy (127.0.0.1:10808/10809)
# Uses requests with proxy fallbacks; works even without VLESS (direct).

import os
import re
import logging
import requests
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"

# VLESS proxies (from config/vless.json inbounds)
SOCKS_PROXY = os.environ.get("TELEGRAM_PROXY_SOCKS", "socks5h://127.0.0.1:10808")
HTTP_PROXY = os.environ.get("TELEGRAM_PROXY_HTTP", "http://127.0.0.1:10809")

# Whether to force proxy – set TELEGRAM_FORCE_PROXY=1 to always use proxy
FORCE_PROXY = os.environ.get("TELEGRAM_FORCE_PROXY", "0") == "1"

def get_bot_token(app=None) -> str:
    """Resolve bot token from env / flask config / kis.toml."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("BOT_TOKEN")
    if token:
        return token.strip()
    # Try flask app config
    if app is not None:
        try:
            t = app.config.get("TELEGRAM_BOT_TOKEN", "")
            if t and t != "YOUR_BOT_TOKEN_HERE":
                return t.strip()
        except Exception:
            pass
    # Fallback import
    try:
        from flask import current_app
        if current_app:
            t = current_app.config.get("TELEGRAM_BOT_TOKEN", "")
            if t and t != "YOUR_BOT_TOKEN_HERE":
                return t.strip()
    except Exception:
        pass
    # Last resort: read config/kis.toml directly
    try:
        import tomli
        cfg = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config", "kis.toml")
        if os.path.exists(cfg):
            with open(cfg, "rb") as f:
                data = tomli.load(f)
                t = data.get("telegram", {}).get("bot_token", "")
                if t and t != "YOUR_BOT_TOKEN_HERE":
                    return t.strip()
    except Exception:
        pass
    return ""

def _proxy_dict(use_proxy: Optional[bool] = None) -> Optional[Dict[str, str]]:
    """Return proxies dict if proxy reachable, else None (direct)."""
    if use_proxy is False:
        return None
    # If FORCE_PROXY, always return socks
    if FORCE_PROXY or use_proxy is True:
        return {"http": SOCKS_PROXY, "https": SOCKS_PROXY}
    # Auto-detect: try to see if socks port is listening, otherwise direct
    # We attempt proxy first, fallback to direct on failure in caller.
    return {"http": SOCKS_PROXY, "https": SOCKS_PROXY}

def _request(method: str, token: str, api_method: str, proxies: Optional[Dict[str, str]], **kwargs) -> Dict[str, Any]:
    url = f"{TELEGRAM_API_BASE}/bot{token}/{api_method}"
    # kwargs may contain json or data
    try:
        resp = requests.request(method, url, proxies=proxies, timeout=kwargs.pop("timeout", 15), **kwargs)
        try:
            data = resp.json()
        except Exception:
            return {"ok": False, "error": f"non-json {resp.status_code}: {resp.text[:500]}", "status_code": resp.status_code}
        return data
    except requests.exceptions.ProxyError as e:
        logger.warning(f"Proxy error for {api_method}: {e} – retry direct")
        if proxies:
            # retry direct
            try:
                resp = requests.request(method, url, proxies=None, timeout=kwargs.pop("timeout", 15), **kwargs)
                return resp.json()
            except Exception as e2:
                return {"ok": False, "error": str(e2)}
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def api_call(token: str, method: str, payload: Dict[str, Any], use_proxy: Optional[bool] = None) -> Dict[str, Any]:
    proxies = _proxy_dict(use_proxy)
    # Try proxy, on proxy failure retry direct
    data = _request("POST", token, method, proxies, json=payload)
    if not data.get("ok") and proxies and "ProxyError" in str(data.get("error", "")):
        data = _request("POST", token, method, None, json=payload)
    # Also fallback to http proxy if socks fails
    if not data.get("ok") and proxies and SOCKS_PROXY in str(proxies):
        alt = {"http": HTTP_PROXY, "https": HTTP_PROXY}
        alt_data = _request("POST", token, method, alt, json=payload)
        if alt_data.get("ok"):
            return alt_data
    return data

# ---- High-level helpers ----

def get_me(token: str, use_proxy: Optional[bool] = None) -> Dict[str, Any]:
    return api_call(token, "getMe", {}, use_proxy)

def send_message(token: str, chat_id: int, text: str, parse_mode: Optional[str] = "HTML", reply_markup: Optional[Dict]=None, use_proxy=None, entities: Optional[list]=None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup
    if entities:
        payload["entities"] = entities
    return api_call(token, "sendMessage", payload, use_proxy)

HERO_BANNER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", "img", "premium", "banner-hero.png")
HERO_BANNER_URL = os.environ.get("PREMIUM_HERO_BANNER_URL", "https://web.kiselgram.ru/static/img/premium/banner-hero.png")

def _resolve_banner_file(photo: str) -> Optional[str]:
    """If photo is the hero banner URL, resolve to local file for upload."""
    if photo == HERO_BANNER_URL or "banner-hero.png" in photo:
        # Try local file first
        if os.path.exists(HERO_BANNER_PATH):
            return HERO_BANNER_PATH
        # Fallback to URL
        return None
    if photo.startswith("/") and os.path.exists(photo):
        return photo
    return None

def send_photo(token: str, chat_id: int, photo: str, caption: Optional[str] = None, parse_mode: Optional[str] = "HTML", reply_markup: Optional[Dict]=None, use_proxy=None, caption_entities: Optional[list]=None) -> Dict[str, Any]:
    # If photo is a local file (hero banner), upload via multipart
    local_file = _resolve_banner_file(photo)
    if local_file and os.path.exists(local_file):
        # Use multipart upload
        proxies = _proxy_dict(use_proxy)
        url = f"{TELEGRAM_API_BASE}/bot{token}/sendPhoto"
        data = {"chat_id": str(chat_id)}
        if caption:
            data["caption"] = caption
            if parse_mode:
                data["parse_mode"] = parse_mode
            if caption_entities:
                import json as _json
                data["caption_entities"] = _json.dumps(caption_entities)
        if reply_markup:
            import json as _json
            data["reply_markup"] = _json.dumps(reply_markup)
        try:
            with open(local_file, "rb") as f:
                files = {"photo": (os.path.basename(local_file), f, "image/png")}
                resp = requests.post(url, data=data, files=files, proxies=proxies, timeout=15)
                try:
                    return resp.json()
                except Exception:
                    return {"ok": False, "error": f"non-json {resp.status_code}: {resp.text[:500]}"}
        except Exception as e:
            logger.warning(f"sendPhoto file upload failed {e}, fallback to URL")
            # fallback to URL
            pass

    payload: Dict[str, Any] = {"chat_id": chat_id, "photo": photo}
    if caption:
        payload["caption"] = caption
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if caption_entities:
            payload["caption_entities"] = caption_entities
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return api_call(token, "sendPhoto", payload, use_proxy)

def get_premium_custom_emoji_id() -> str:
    """Get premium custom emoji ID from locales.toml [premium] or env."""
    env_id = os.environ.get("PREMIUM_CUSTOM_EMOJI_ID") or os.environ.get("KISELGRAM_PREMIUM_EMOJI_ID")
    if env_id:
        return env_id.strip()
    try:
        import tomli
        cfg = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config", "locales.toml")
        if os.path.exists(cfg):
            with open(cfg, "rb") as f:
                data = tomli.load(f)
                pid = data.get("premium", {}).get("custom_emoji_id")
                if pid:
                    return str(pid).strip()
    except Exception:
        pass
    return "5285476321705633458"

def with_premium_emoji(text: str, custom_id: Optional[str]=None) -> tuple[str, Optional[list]]:
    """If text contains ⭐ or ✨, attach custom_emoji entity for Telegram.
    Returns (text, entities) where entities is None if no emoji."""
    if not text or "⭐" not in text and "✨" not in text:
        return text, None
    cid = custom_id or get_premium_custom_emoji_id()
    if not cid:
        return text, None
    entities = []
    for m in re.finditer("⭐", text):
        off = _utf16_len(text[:m.start()])
        entities.append({"type": "custom_emoji", "offset": off, "length": 1, "custom_emoji_id": cid})
    for m in re.finditer("✨", text):
        off = _utf16_len(text[:m.start()])
        entities.append({"type": "custom_emoji", "offset": off, "length": 1, "custom_emoji_id": cid})
    return text, entities if entities else None

def _utf16_len(s: str) -> int:
    return len(s.encode('utf-16-le')) // 2

def _html_to_entities(html: str) -> tuple[str, list]:
    """Convert simple HTML (<b>, <i>, <code>, <a href>, <u>, <s>, <br>) to plain text + entities.
    Returns (plain, entities) where entities use UTF-16 offsets as Telegram requires."""
    entities = []
    import html as html_lib
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    tag_re = re.compile(r"<(/?)(\w+)(?:\s+href=[\"']([^\"']+)[\"'])?[^>]*>", re.IGNORECASE)
    stack = []  # list of (tag, start_utf16, href, start_py)
    out_parts = []
    plain_py = ""  # plain built so far (Python string)
    last = 0
    for m in tag_re.finditer(html):
        text_before = html_lib.unescape(html[last:m.start()])
        out_parts.append(text_before)
        plain_py += text_before
        tag_close = m.group(1) == "/"
        tag_name = m.group(2).lower()
        href = m.group(3)
        if not tag_close:
            if tag_name in ("b", "strong"):
                stack.append(("bold", _utf16_len(plain_py), None))
            elif tag_name in ("i", "em"):
                stack.append(("italic", _utf16_len(plain_py), None))
            elif tag_name in ("u",):
                stack.append(("underline", _utf16_len(plain_py), None))
            elif tag_name in ("s", "strike", "del"):
                stack.append(("strikethrough", _utf16_len(plain_py), None))
            elif tag_name in ("code",):
                stack.append(("code", _utf16_len(plain_py), None))
            elif tag_name in ("pre",):
                stack.append(("pre", _utf16_len(plain_py), None))
            elif tag_name == "a" and href:
                stack.append(("text_link", _utf16_len(plain_py), href))
        else:
            for idx in range(len(stack)-1, -1, -1):
                if stack[idx][0] == ("bold" if tag_name in ("b","strong") else
                                     "italic" if tag_name in ("i","em") else
                                     "underline" if tag_name=="u" else
                                     "strikethrough" if tag_name in ("s","strike","del") else
                                     "code" if tag_name=="code" else
                                     "pre" if tag_name=="pre" else
                                     "text_link" if tag_name=="a" else None):
                    typ, start_utf16, extra = stack.pop(idx)
                    length = _utf16_len(plain_py) - start_utf16
                    if length > 0:
                        ent = {"type": typ, "offset": start_utf16, "length": length}
                        if typ == "text_link":
                            ent["url"] = extra
                        entities.append(ent)
                    break
        last = m.end()
    tail = html_lib.unescape(html[last:])
    out_parts.append(tail)
    plain = "".join(out_parts)
    entities.sort(key=lambda e: e["offset"])
    return plain, entities

def send_premium_message(token: str, chat_id: int, text: str, parse_mode: str = "HTML", reply_markup: Optional[Dict]=None, use_proxy=None, lang: str = "ru", with_banner: bool = True) -> Dict[str, Any]:
    """Send message with premium custom emoji and hero banner on every message.
    If custom emoji is needed, converts HTML to entities and sends with custom_emoji.
    If with_banner True, sends hero.png as photo with caption."""
    custom_id = get_premium_custom_emoji_id()
    has_star = "⭐" in text or "✨" in text
    # Prepare caption/text and entities
    if has_star and custom_id:
        plain, html_entities = _html_to_entities(text)
        custom_entities = []
        for m in re.finditer("⭐", plain):
            off = _utf16_len(plain[:m.start()])
            custom_entities.append({"type": "custom_emoji", "offset": off, "length": 1, "custom_emoji_id": custom_id})
        for m in re.finditer("✨", plain):
            off = _utf16_len(plain[:m.start()])
            custom_entities.append({"type": "custom_emoji", "offset": off, "length": 1, "custom_emoji_id": custom_id})
        all_entities = html_entities + custom_entities
        all_entities.sort(key=lambda e: e["offset"])
        caption = plain
        caption_entities = all_entities if all_entities else None
        parse_mode_caption = None
    else:
        # No custom emoji, keep HTML parsing for caption/text
        # If with_banner, we need to convert HTML to plain for caption if we want to support it, but for non-custom we can keep HTML
        # For photo caption with HTML, we can use parse_mode
        caption = text
        caption_entities = None
        parse_mode_caption = parse_mode

    if with_banner and HERO_BANNER_URL:
        # Send hero banner as photo with caption (every message)
        # For custom emoji case, caption_entities already prepared, else use parse_mode
        if has_star and custom_id:
            return send_photo(token, chat_id, HERO_BANNER_URL, caption=caption, parse_mode=parse_mode_caption, reply_markup=reply_markup, use_proxy=use_proxy, caption_entities=caption_entities)
        else:
            return send_photo(token, chat_id, HERO_BANNER_URL, caption=caption, parse_mode=parse_mode_caption, reply_markup=reply_markup, use_proxy=use_proxy, caption_entities=caption_entities)
    else:
        if has_star and custom_id:
            return send_message(token, chat_id, plain, parse_mode=None, reply_markup=reply_markup, use_proxy=use_proxy, entities=all_entities if all_entities else None)
        else:
            return send_message(token, chat_id, text, parse_mode=parse_mode, reply_markup=reply_markup, use_proxy=use_proxy, entities=None)

def get_custom_emoji_stickers(token: str, custom_emoji_ids: list, use_proxy=None) -> Dict[str, Any]:
    return api_call(token, "getCustomEmojiStickers", {"custom_emoji_ids": custom_emoji_ids}, use_proxy)

def send_invoice(token: str, chat_id: int, title: str, description: str, payload_str: str, currency: str, prices: list, use_proxy=None, **kwargs) -> Dict[str, Any]:
    """Send Telegram Stars invoice (currency XTR, provider_token must be empty)."""
    p: Dict[str, Any] = {
        "chat_id": chat_id,
        "title": title,
        "description": description,
        "payload": payload_str,
        "currency": currency,
        "prices": prices,
        "provider_token": "",  # mandatory empty for Stars
    }
    p.update(kwargs)
    return api_call(token, "sendInvoice", p, use_proxy)

def create_invoice_link(token: str, title: str, description: str, payload_str: str, currency: str, prices: list, use_proxy=None, **kwargs) -> Dict[str, Any]:
    p: Dict[str, Any] = {
        "title": title,
        "description": description,
        "payload": payload_str,
        "currency": currency,
        "prices": prices,
        "provider_token": "",
    }
    p.update(kwargs)
    return api_call(token, "createInvoiceLink", p, use_proxy)

def answer_pre_checkout_query(token: str, query_id: str, ok: bool = True, error_message: Optional[str] = None, use_proxy=None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"pre_checkout_query_id": query_id, "ok": ok}
    if error_message:
        payload["error_message"] = error_message
    return api_call(token, "answerPreCheckoutQuery", payload, use_proxy)

def answer_shipping_query(token: str, query_id: str, ok: bool, use_proxy=None, **kwargs) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"shipping_query_id": query_id, "ok": ok}
    payload.update(kwargs)
    return api_call(token, "answerShippingQuery", payload, use_proxy)

def set_webhook(token: str, url: str, secret_token: Optional[str]=None, use_proxy=None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"url": url}
    if secret_token:
        payload["secret_token"] = secret_token
    return api_call(token, "setWebhook", payload, use_proxy)

def delete_webhook(token: str, use_proxy=None) -> Dict[str, Any]:
    return api_call(token, "deleteWebhook", {}, use_proxy)

def get_webhook_info(token: str, use_proxy=None) -> Dict[str, Any]:
    return api_call(token, "getWebhookInfo", {}, use_proxy)

def get_updates(token: str, offset: int = 0, timeout: int = 30, use_proxy=None) -> Dict[str, Any]:
    proxies = _proxy_dict(use_proxy)
    url = f"{TELEGRAM_API_BASE}/bot{token}/getUpdates"
    params = {"offset": offset, "timeout": timeout}
    try:
        resp = requests.get(url, params=params, proxies=proxies, timeout=timeout+5)
        return resp.json()
    except requests.exceptions.ProxyError:
        if proxies:
            resp = requests.get(url, params=params, proxies=None, timeout=timeout+5)
            return resp.json()
        raise
    except Exception as e:
        return {"ok": False, "error": str(e)}

def check_proxy() -> Dict[str, Any]:
    """Diagnostic: check if VLESS proxy is reachable."""
    import socket
    results = {}
    for name, host, port in [("socks", "127.0.0.1", 10808), ("http", "127.0.0.1", 10809)]:
        try:
            s = socket.socket()
            s.settimeout(2)
            s.connect((host, port))
            s.close()
            results[name] = "open"
        except Exception as e:
            results[name] = f"closed: {e}"
    return results
