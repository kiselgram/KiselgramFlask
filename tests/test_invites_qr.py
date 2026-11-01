"""Regression: group invites end-to-end + QR login flows."""

from datetime import datetime

from app import db
from app.models import Chat, ChatMember

V2 = "/api.v2/api"


def _login(app, user):
    c = app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = user.id
    return c


class TestInviteFlow:
    def test_create_and_join(self, app, user, user2):
        c1 = _login(app, user)
        g = c1.post(f"{V2}/groups/create", json={"name": "InvG"}).get_json()["data"]["group"]
        gid = g["group_id"]
        inv = c1.post(f"{V2}/groups/{gid}/invites/create", json={}).get_json()["data"]
        assert inv.get("code") or inv.get("link")
        code = inv.get("code") or inv["link"].rsplit("/", 1)[-1]
        c2 = _login(app, user2)
        r = c2.get(f"{V2}/join_group/{code}")
        assert r.status_code == 200, r.get_data(as_text=True)[:200]
        assert ChatMember.query.filter_by(chat_id=gid, user_id=user2.id).first() is not None

    def test_join_bad_code(self, app, user2):
        c2 = _login(app, user2)
        assert c2.get(f"{V2}/join_group/nope_nothing").status_code == 404


class TestQrFlow:
    def test_mode_a_generate_then_login(self, app, user):
        c1 = _login(app, user)
        token = c1.post("/api.v2/api/auth/qr/generate", json={}).get_json()["data"]["token"]
        anon = app.test_client()
        r = anon.post("/api.v2/api/auth/qr/login", json={"token": token})
        assert r.status_code == 200, r.get_data(as_text=True)[:200]
        assert r.get_json()["data"]["user"]["user_id"] == user.id

    def test_mode_b_request_authorize_login(self, app, user):
        anon = app.test_client()
        token = anon.post("/api.v2/api/auth/qr/request", json={}).get_json()["data"]["token"]
        st = anon.get(f"/api.v2/api/auth/qr/status/{token}").get_json()["data"]
        assert st["authorized"] is False
        c1 = _login(app, user)
        assert c1.post("/api.v2/api/auth/qr/authorize", json={"token": token}).status_code == 200
        st = anon.get(f"/api.v2/api/auth/qr/status/{token}").get_json()["data"]
        assert st["authorized"] is True and st["consumed"] is False
        r = anon.post("/api.v2/api/auth/qr/login", json={"token": token})
        assert r.status_code == 200
        assert r.get_json()["data"]["user"]["user_id"] == user.id
        # token is single-use
        assert anon.post("/api.v2/api/auth/qr/login", json={"token": token}).status_code == 400
