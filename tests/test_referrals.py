"""Referrals: join -> inviter earns premium (+30d per referral, stackable)."""

from datetime import datetime, timedelta, timezone

from app import db
from app.models import Referral, User

V2 = "/api.v2/api"


def _login(app, user):
    c = app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = user.id
    return c


def _premium_until(user_id):
    u = db.session.get(User, user_id)
    assert u.premium and u.premium.is_premium
    return u.premium.premium_expires_at


class TestReferralReward:
    def test_use_grants_30_days(self, app, user, user2):
        c = app.test_client()
        before = datetime.now(timezone.utc).replace(tzinfo=None)
        r = c.post(f"{V2}/referrals/use", json={"ref": user.username, "user_id": user2.id})
        assert r.status_code == 200
        d = r.get_json()["data"]
        assert d["premium_granted"] is True and d["days_added"] == 30
        until = _premium_until(user.id)
        assert timedelta(days=29) < until - before < timedelta(days=31)

    def test_stacking(self, app, user, user2, user3):
        c = app.test_client()
        c.post(f"{V2}/referrals/use", json={"ref": user.username, "user_id": user2.id})
        first = _premium_until(user.id)
        c.post(f"{V2}/referrals/use", json={"ref": user.username, "user_id": user3.id})
        second = _premium_until(user.id)
        assert timedelta(days=29) < second - first < timedelta(days=31)

    def test_expired_premium_restarts(self, app, user, user2):
        from app.models import UserPremium
        past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=5)
        db.session.add(UserPremium(user_id=user.id, is_premium=False, premium_expires_at=past))
        db.session.commit()
        c = app.test_client()
        assert c.post(f"{V2}/referrals/use", json={"ref": user.username, "user_id": user2.id}).status_code == 200
        until = _premium_until(user.id)
        assert until > datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=29)

    def test_self_invalid_dup(self, app, user, user2):
        c = app.test_client()
        assert c.post(f"{V2}/referrals/use", json={"ref": user.username, "user_id": user.id}).status_code == 400
        assert c.post(f"{V2}/referrals/use", json={"ref": "ghost_nobody", "user_id": user2.id}).status_code == 404
        assert c.post(f"{V2}/referrals/use", json={}).status_code == 400
        assert c.post(f"{V2}/referrals/use", json={"ref": user.username, "user_id": user2.id}).status_code == 200
        d = c.post(f"{V2}/referrals/use", json={"ref": user.username, "user_id": user2.id}).get_json()["data"]
        assert d.get("already_applied") is True
        assert Referral.query.filter_by(inviter_id=user.id).count() == 1

    def test_user_id_from_session(self, app, user, user2):
        c2 = _login(app, user2)
        r = c2.post(f"{V2}/referrals/use", json={"ref": user.username})
        assert r.status_code == 200
        assert r.get_json()["data"]["inviter_username"] == user.username

    def test_ten_referrals_grant_premium(self, app, user):
        from app.routes.spav2.referrals import REFERRAL_PREMIUM_THRESHOLD
        from app.utils.security import rate_limiter
        c = app.test_client()
        assert REFERRAL_PREMIUM_THRESHOLD == 10
        for i in range(10):
            rate_limiter._store.clear()
            r = c.post("/api.v2/api/auth/register-finish", json={
                "email": f"ref{i}@test.io", "username": f"ref{i}",
                "email_verified": False, "ref": user.username, "friend_verified": True})
            assert r.status_code == 200
        u = db.session.get(User, user.id)
        assert u.premium and u.premium.is_premium

    def test_info(self, logged_in_client, user):
        d = logged_in_client.get(f"{V2}/referrals/info").get_json()["data"]
        assert d["invite_code"] == user.username
        assert "join?ref=" in d["invite_url"]
        assert d["threshold"] == 10
        assert d["premium_days_per_referral"] == 30


class TestFriendCode:
    def test_check(self, client, user):
        d = client.post(f"{V2}/referrals/check", json={"code": user.username}).get_json()
        assert d["success"] is True
        assert d["data"]["username"] == user.username
        assert client.post(f"{V2}/referrals/check", json={"code": "ghost_xyz"}).status_code == 404
        assert client.post(f"{V2}/referrals/check", json={}).status_code == 400

    def test_register_without_verification(self, app, user):
        c = app.test_client()
        r = c.post("/api.v2/api/auth/register-finish", json={
            "email": "friendkid@test.io", "username": "friendkid",
            "email_verified": False, "ref": user.username, "friend_verified": True})
        assert r.status_code == 200, r.get_data(as_text=True)[:200]
        new_id = r.get_json()["data"]["user"]["user_id"]
        assert db.session.query(Referral).filter_by(invited_user_id=new_id).count() == 1
        u = db.session.get(User, user.id)
        assert u.premium and u.premium.is_premium

    def test_register_bad_ref_still_requires_verify(self, app, user):
        c = app.test_client()
        r = c.post("/api.v2/api/auth/register-finish", json={
            "email": "x2@test.io", "username": "xkid2",
            "email_verified": False, "ref": "ghost_xyz", "friend_verified": True})
        assert r.status_code == 400
        assert r.get_json()["error"]["code"] == "VERIFY_REQUIRED"

    def test_register_self_ref_rejected(self, app, user):
        c = app.test_client()
        r = c.post("/api.v2/api/auth/register-finish", json={
            "email": "x3@test.io", "username": user.username,
            "email_verified": False, "ref": user.username, "friend_verified": True})
        assert r.status_code == 400
        assert r.get_json()["error"]["code"] == "VERIFY_REQUIRED"
