"""Sputnik 'do all' wave: security fixes + wave-3 endpoints."""

import io
from datetime import datetime

from app import db
from app.models import Chat, ChatMember, Message, User

V2 = "/api.v2/api"
SP = "/api.v2/api/sputnik"


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


class TestPinAccess:
    def test_outsider_cannot_pin(self, app, user, user2, user3, personal_chat):
        m = Message(content="hi", sender_id=user.id, receiver_id=user2.id,
                    chat_id=personal_chat.id, timestamp=datetime.utcnow())
        db.session.add(m)
        db.session.commit()
        c3 = _login(app, user3)
        r = c3.post(f"{V2}/messages/pin", json={"message_id": m.id, "chat_id": personal_chat.id})
        assert r.status_code == 403
        c1 = _login(app, user)
        assert c1.post(f"{V2}/messages/pin", json={"message_id": m.id, "chat_id": personal_chat.id}).status_code == 200

    def test_pinned_endpoints_require_auth(self, client, personal_chat):
        assert client.get(f"{V2}/messages/pinned", query_string={"chat_id": personal_chat.id}).status_code == 401
        assert client.post(f"{V2}/messages/pinned/dismiss", json={"chat_id": personal_chat.id}).status_code == 401

    def test_forward_requires_target_access(self, app, user, user2, personal_chat):
        m = Message(content="fwd", sender_id=user.id, receiver_id=user2.id,
                    chat_id=personal_chat.id, timestamp=datetime.utcnow())
        db.session.add(m)
        db.session.commit()
        g = Chat(chat_type="group", name="Nope", owner_id=user2.id, is_public=False,
                 invite_link="sp3_nope", created_at=datetime.utcnow())
        db.session.add(g)
        db.session.flush()
        db.session.add(ChatMember(user_id=user2.id, chat_id=g.id, role="owner"))
        db.session.commit()
        c1 = _login(app, user)
        r = c1.post(f"{V2}/messages/forward", json={"message_id": m.id, "target_chat_id": g.id})
        assert r.status_code == 403


class TestPresencePrivacy:
    def test_nobody_hides_presence(self, logged_in_client, user, user2):
        user2.privacy_last_seen = "nobody"
        db.session.commit()
        d = logged_in_client.get(f"{V2}/users/{user2.id}").get_json()["data"]
        assert d["last_seen"] is None
        assert d["is_online"] is False

    def test_username_lookup_requires_auth(self, client, user):
        assert client.get(f"{V2}/u/{user.username}").status_code == 401

    def test_contacts_respect_privacy(self, logged_in_client, user, user2):
        from app.models import Contact
        user2.privacy_last_seen = "nobody"
        if not Contact.query.filter_by(user_id=user.id, contact_id=user2.id).first():
            db.session.add(Contact(user_id=user.id, contact_id=user2.id))
        db.session.commit()
        items = logged_in_client.get(f"{V2}/contacts").get_json()["data"]["contacts"]
        row = next(i for i in items if i["user_id"] == user2.id)
        assert row["last_seen"] is None


class TestTraversalAndLockout:
    def test_safe_path_blocks_escape(self):
        from app.routes.files import safe_path_in_uploads
        assert safe_path_in_uploads("..", "secret") is None
        assert safe_path_in_uploads("../uploads_evil/x") is None
        assert safe_path_in_uploads("images", "..", "..", "x") is None
        assert safe_path_in_uploads("images", "a.jpg") is not None

    def test_login_lockout(self, client, user):
        for _ in range(5):
            r = client.post("/api.v2/api/auth/login", json={"username": user.username, "password": "wrong"})
            assert r.status_code == 401
        r = client.post("/api.v2/api/auth/login", json={"username": user.username, "password": "wrong"})
        assert r.status_code == 429
        assert r.get_json()["error"]["code"] == "ACCOUNT_LOCKED"


class TestWave3:
    def test_album_lookup(self, logged_in_client, user, personal_chat):
        from app.models import Message
        ids = []
        for i in range(2):
            m = Message(content=f"a{i}", sender_id=user.id, chat_id=personal_chat.id,
                        timestamp=datetime.utcnow())
            db.session.add(m)
            db.session.commit()
            ids.append(m.id)
        r = logged_in_client.post(f"{SP}/albums/create", json={"message_ids": ids})
        aid = r.get_json()["data"]["album_id"]
        d = logged_in_client.post(f"{SP}/albums/lookup", json={"message_ids": ids + [999999]}).get_json()["data"]
        assert str(ids[0]) in d["albums"] or ids[0] in d["albums"]
        entry = d["albums"].get(str(ids[0]), d["albums"].get(ids[0]))
        assert entry["album_id"] == aid
        assert entry["members"] == ids

    def test_sticker_send_to_peer(self, logged_in_client, user, user2):
        sid = logged_in_client.post(f"{SP}/stickers/upload", json={"file_path": "stickers/p.png"}).get_json()["data"]["sticker_id"]
        r = logged_in_client.post(f"{SP}/stickers/send", json={
            "sticker_id": sid, "chat_type": "personal", "peer_id": user2.id})
        assert r.status_code == 200
        mid = r.get_json()["data"]["message_id"]
        m = db.session.get(Message, mid)
        assert m.receiver_id == user2.id

    def test_round_send_to_peer(self, logged_in_client, user, user2):
        r = logged_in_client.post(f"{SP}/round/send", json={
            "chat_type": "personal", "peer_id": user2.id,
            "file_path": "circles/b.mp4", "duration": 5})
        assert r.status_code == 200
        m = db.session.get(Message, r.get_json()["data"]["message_id"])
        assert m.file_type == "round" and m.receiver_id == user2.id

    def test_backup_admin_only(self, app, user, admin_user):
        cu, ca = _login(app, user), _login(app, admin_user)
        assert cu.get(f"{SP}/db/backup").status_code == 403
        r = ca.get(f"{SP}/db/backup")
        assert r.status_code == 200
        assert "attachment" in r.headers.get("Content-Disposition", "")

    def test_cloud_recover(self, logged_in_client, user):
        logged_in_client.post(f"{SP}/cloud/setup", json={"password": "old1", "email": "me@x.io"})
        r = logged_in_client.post(f"{SP}/cloud/recover", json={"email": "nope@x.io", "new_password": "new1"})
        assert r.status_code == 403
        assert logged_in_client.post(f"{SP}/cloud/recover", json={"email": "me@x.io", "new_password": "new1"}).status_code == 200
        assert logged_in_client.post(f"{SP}/cloud/verify", json={"password": "new1"}).status_code == 200

    def test_invite_pages(self, client, user):
        g = Chat(chat_type="group", name="Landing G", owner_id=user.id, is_public=True,
                 invite_link="sp3_land_g", created_at=datetime.utcnow())
        db.session.add(g)
        db.session.commit()
        r = client.get("/join/sp3_land_g")
        assert r.status_code == 200
        assert "Landing G" in r.get_data(as_text=True)
        assert client.get("/join/nope_nothing").status_code == 404
        ch = Chat(chat_type="channel", name="Landing C", owner_id=user.id, is_public=True,
                  invite_link="sp3_land_c", created_at=datetime.utcnow())
        db.session.add(ch)
        db.session.commit()
        assert client.get("/c/sp3_land_c").status_code == 200

    def test_join_direct(self, app, user, user2):
        pub = Chat(chat_type="group", name="Pub3", owner_id=user.id, is_public=True,
                   invite_link="sp3_pub", created_at=datetime.utcnow())
        db.session.add(pub)
        db.session.flush()
        db.session.add(ChatMember(user_id=user.id, chat_id=pub.id, role="owner"))
        priv = Chat(chat_type="group", name="Priv3", owner_id=user.id, is_public=False,
                    invite_link="sp3_priv", created_at=datetime.utcnow())
        db.session.add(priv)
        db.session.flush()
        db.session.add(ChatMember(user_id=user.id, chat_id=priv.id, role="owner"))
        db.session.commit()
        c2 = _login(app, user2)
        d = c2.post(f"{SP}/groups/{pub.id}/join").get_json()["data"]
        assert d.get("joined") is True
        d = c2.post(f"{SP}/groups/{priv.id}/join").get_json()["data"]
        assert d.get("requested") is True

    def test_upload_and_notify(self, app, user, user2):
        c2 = _login(app, user2)
        data = {"file": (io.BytesIO(b"\x89PNG\r\n\x1a\nfakepng"), "s.png")}
        r = c2.post(f"{SP}/upload", data=data, content_type="multipart/form-data")
        assert r.status_code == 200
        assert r.get_json()["data"]["file_path"].startswith("stickers/")
        # system notification on approve
        kg = User(username="kiselgram", email="kg@local", email_verified=True, display_name="Kiselgram", is_bot=True)
        db.session.add(kg)
        db.session.commit()
        g = Chat(chat_type="group", name="NotifyG", owner_id=user.id, is_public=False,
                 invite_link="sp3_notify", created_at=datetime.utcnow())
        db.session.add(g)
        db.session.flush()
        db.session.add(ChatMember(user_id=user.id, chat_id=g.id, role="owner"))
        db.session.commit()
        c2.post(f"{SP}/groups/{g.id}/request")
        c1 = _login(app, user)
        assert c1.post(f"{SP}/groups/{g.id}/approve", json={"user_id": user2.id}).status_code == 200
        note = Message.query.filter_by(sender_id=kg.id, receiver_id=user2.id).order_by(Message.id.desc()).first()
        assert note is not None and "NotifyG" in (note.content or "")
