"""Full coverage wave: security units, sputnik gaps, OTP backend."""

from datetime import datetime, timedelta

from app import db
from app.models import Chat, ChatMember, Contact, Message, User

SP = "/api.v2/api/sputnik"
V2 = "/api.v2/api"


import pytest


@pytest.fixture(autouse=True)
def _clean_auth_state():
    from app.utils import security
    from app.utils.helpers import _slow_buckets
    security._ACCOUNT_FAILURES.clear()
    _slow_buckets.clear()
    yield
    security._ACCOUNT_FAILURES.clear()
    _slow_buckets.clear()


def _login(app, user):
    c = app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = user.id
    return c


class TestPresenceUnits:
    def test_self_always(self, user):
        from app.utils.helpers import presence_visible
        assert presence_visible(user.id, user) is True

    def test_none_target(self, user):
        from app.utils.helpers import presence_visible
        assert presence_visible(user.id, None) is False

    def test_everyone(self, session, user, user2):
        from app.utils.helpers import presence_visible
        user2.privacy_last_seen = "everyone"
        session.commit()
        assert presence_visible(user.id, user2) is True

    def test_nobody(self, session, user, user2):
        from app.utils.helpers import presence_visible
        user2.privacy_last_seen = "nobody"
        session.commit()
        assert presence_visible(user.id, user2) is False

    def test_contacts_member(self, session, user, user2):
        from app.utils.helpers import presence_visible
        user2.privacy_last_seen = "contacts"
        session.add(Contact(user_id=user2.id, contact_id=user.id))
        session.commit()
        assert presence_visible(user.id, user2) is True

    def test_contacts_stranger(self, session, user, user2, user3):
        from app.utils.helpers import presence_visible
        user2.privacy_last_seen = "contacts"
        session.add(Contact(user_id=user2.id, contact_id=user3.id))
        session.commit()
        assert presence_visible(user.id, user2) is False


class TestChatAccessUnits:
    def test_member_ok(self, user, personal_chat):
        from app.routes.spav2.features import _chat_access
        assert _chat_access(user.id, personal_chat.id) is not None

    def test_outsider_none(self, app, user, user2, user3):
        from app.routes.spav2.features import _chat_access
        c = Chat(chat_type="personal", user1_id=user.id, user2_id=user2.id)
        db.session.add(c)
        db.session.commit()
        assert _chat_access(user3.id, c.id) is None

    def test_missing_chat(self, user):
        from app.routes.spav2.features import _chat_access
        assert _chat_access(user.id, 999999) is None

    def test_channel_subscriber(self, session, user, user2):
        from app.models import ChatSubscriber
        from app.routes.spav2.features import _chat_access
        ch = Chat(chat_type="channel", name="C", owner_id=user2.id, is_public=True,
                  invite_link="sp4_chan", created_at=datetime.utcnow())
        session.add(ch)
        session.flush()
        session.add(ChatSubscriber(user_id=user.id, chat_id=ch.id))
        session.commit()
        assert _chat_access(user.id, ch.id) is not None


class TestSlowModeUnits:
    def test_no_slowmode(self, user, personal_chat):
        from app.utils.helpers import slow_mode_ok
        assert slow_mode_ok(user.id, personal_chat.id) == (True, 0)

    def test_throttle_and_admin_bypass(self, session, user, user2):
        from app.utils.helpers import slow_mode_ok, _slow_buckets
        g = Chat(chat_type="group", name="Slow", owner_id=user.id, is_public=False,
                 invite_link="sp4_slow", created_at=datetime.utcnow())
        session.add(g)
        session.flush()
        session.add(ChatMember(user_id=user.id, chat_id=g.id, role="owner"))
        session.add(ChatMember(user_id=user2.id, chat_id=g.id, role="member"))
        session.commit()
        g.slow_mode = 60
        session.commit()
        assert slow_mode_ok(user.id, g.id) == (True, 0)
        assert slow_mode_ok(user2.id, g.id)[0] is True
        ok, retry = slow_mode_ok(user2.id, g.id)
        assert ok is False and retry > 0
        _slow_buckets.pop((g.id, user2.id), None)


class TestAccountLockoutUnits:
    def test_flow(self):
        from app.utils.security import account_locked, note_account_failure, clear_account_failures
        key = "sp4_unit_test_key"
        clear_account_failures(key)
        assert account_locked(key) is False
        for _ in range(5):
            note_account_failure(key)
        assert account_locked(key) is True
        clear_account_failures(key)
        assert account_locked(key) is False

    def test_empty_key_safe(self):
        from app.utils.security import account_locked, note_account_failure
        assert account_locked("") is False
        assert account_locked(None) is False
        note_account_failure("")


class TestOtpLockoutApi:
    def test_verify_otp_lockout(self, client, session, user):
        from app.models import LoginOtp
        for _ in range(5):
            r = client.post("/api.v2/api/auth/verify-otp", json={"email": user.email, "code": "00000"})
            assert r.status_code == 400
        r = client.post("/api.v2/api/auth/verify-otp", json={"email": user.email, "code": "00000"})
        assert r.status_code == 429

    def test_applock_lockout(self, logged_in_client):
        assert logged_in_client.post(f"{SP}/applock/set", json={"pin": "9999"}).status_code == 200
        for _ in range(5):
            assert logged_in_client.post(f"{SP}/applock/verify", json={"pin": "0000"}).status_code == 403
        assert logged_in_client.post(f"{SP}/applock/verify", json={"pin": "0000"}).status_code == 429


class TestOtpBackend:
    def test_code_format(self):
        from app.routes.spav2.login_v3 import _new_otp_code
        for _ in range(20):
            c = _new_otp_code()
            assert len(c) == 5 and c.isdigit() and 10000 <= int(c) <= 99999

    def test_no_smtp_config(self, app):
        from app.routes.spav2.login_v3 import _mail_configured
        with app.app_context():
            assert isinstance(_mail_configured(), bool)

    def test_register_debug_fallback(self, app, client):
        import app.routes.spav2.login_v3 as lv3
        orig_send = lv3._send_mail_fast
        orig_cfg = lv3._mail_configured
        lv3._send_mail_fast = lambda msg: (_ for _ in ()).throw(RuntimeError("no smtp"))
        lv3._mail_configured = lambda: True
        app.config["DEBUG"] = True
        try:
            r = client.post("/api.v2/api/auth/register-send-code", json={"email": "sp4new@test.io"})
            assert r.status_code == 200
            assert len(r.get_json()["data"]["debug_code"]) == 5
        finally:
            lv3._send_mail_fast = orig_send
            lv3._mail_configured = orig_cfg
            app.config["DEBUG"] = False


class TestSputnikGaps:
    def test_sticker_from_message(self, logged_in_client, user, user2, personal_chat):
        m = Message(content="img", sender_id=user.id, receiver_id=user2.id, chat_id=personal_chat.id,
                    file_type="photo", file_path="photos/x.jpg", timestamp=datetime.utcnow())
        db.session.add(m)
        db.session.commit()
        r = logged_in_client.post(f"{SP}/stickers/from_message", json={"message_id": m.id})
        assert r.status_code == 200
        m2 = Message(content="noimg", sender_id=user.id, chat_id=personal_chat.id, timestamp=datetime.utcnow())
        db.session.add(m2)
        db.session.commit()
        assert logged_in_client.post(f"{SP}/stickers/from_message", json={"message_id": m2.id}).status_code == 400

    def test_scheduled_delete(self, logged_in_client, user, personal_chat):
        future = datetime.utcnow() + timedelta(hours=2)
        m = Message(content="todel", sender_id=user.id, chat_id=personal_chat.id,
                    scheduled_at=future, timestamp=datetime.utcnow())
        db.session.add(m)
        db.session.commit()
        assert logged_in_client.delete(f"{SP}/scheduled/{m.id}").status_code == 200
        assert db.session.get(Message, m.id) is None

    def test_secrets_off(self, logged_in_client):
        logged_in_client.post(f"{SP}/applock/set", json={"pin": "1234"})
        assert logged_in_client.post(f"{SP}/secrets/off", json={"kind": "applock"}).status_code == 200
        assert logged_in_client.post(f"{SP}/applock/verify", json={"pin": "1234"}).status_code == 403
        assert logged_in_client.post(f"{SP}/secrets/off", json={"kind": "nope"}).status_code == 400

    def test_folder_validation(self, logged_in_client):
        assert logged_in_client.post(f"{SP}/folders/create", json={"name": ""}).status_code == 400
        fid = logged_in_client.post(f"{SP}/folders/create", json={"name": "F"}).get_json()["data"]["folder_id"]
        r = logged_in_client.post(f"{SP}/folders/{fid}/chats", json={
            "chats": [{"chat_type": "personal", "chat_id": 5}, {"chat_type": "x", "chat_id": "bad"}]})
        assert r.status_code == 200
        assert logged_in_client.delete(f"{SP}/folders/999999").status_code == 404

    def test_cloud_setup_short(self, logged_in_client):
        assert logged_in_client.post(f"{SP}/cloud/setup", json={"password": "ab"}).status_code == 400
        assert logged_in_client.post(f"{SP}/applock/set", json={"pin": "12ab"}).status_code == 400

    def test_draft_reply_roundtrip(self, logged_in_client, user, personal_chat):
        m = Message(content="orig", sender_id=user.id, chat_id=personal_chat.id, timestamp=datetime.utcnow())
        db.session.add(m)
        db.session.commit()
        logged_in_client.post(f"{SP}/drafts/save", json={
            "chat_type": "personal", "chat_id": personal_chat.id, "text": "reply draft", "reply_to_id": m.id})
        drafts = logged_in_client.get(f"{SP}/drafts").get_json()["data"]["drafts"]
        row = next(d for d in drafts if d["text"] == "reply draft")
        assert row["reply_to_id"] == m.id

    def test_export_contents(self, logged_in_client, user):
        logged_in_client.post(f"{SP}/folders/create", json={"name": "EF"})
        logged_in_client.post(f"{SP}/stickers/upload", json={"file_path": "stickers/e.png"})
        d = logged_in_client.post(f"{SP}/export").get_json()["data"]
        assert any(f["name"] == "EF" for f in d["folders"])
        assert any(s["file_path"] == "stickers/e.png" for s in d["stickers"])

    def test_link_preview_private_blocked(self, logged_in_client, monkeypatch):
        import socket as _socket
        import app.routes.spav2.sputnik as sp
        monkeypatch.setattr(_socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 0))])
        with pytest.raises(ValueError, match="Private"):
            sp._preview_fetch("http://example.com/")
