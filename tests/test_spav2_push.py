"""Tests for V2 API push notification endpoints under /api.v2/api/push/*."""

from app import db
from app.models import PushSubscription


API_PREFIX = "/api"


class TestV2Push:
    """Subscription and VAPID key endpoints"""

    def test_subscribe(self, logged_in_client, user):
        resp = logged_in_client.post(f"{API_PREFIX}/push/subscribe", json={
            "endpoint": "https://push.example.com/abc",
            "keys": {
                "p256dh": "test_p256dh_key",
                "auth": "test_auth_key",
            },
        })
        assert resp.status_code == 200
        sub = PushSubscription.query.filter_by(endpoint="https://push.example.com/abc").first()
        assert sub is not None
        assert sub.user_id == user.id

    def test_subscribe_missing_fields(self, logged_in_client, user):
        resp = logged_in_client.post(f"{API_PREFIX}/push/subscribe", json={
            "endpoint": "https://push.example.com/abc",
        })
        assert resp.status_code == 400

    def test_subscribe_update_existing(self, logged_in_client, user):
        db.session.add(PushSubscription(
            user_id=user.id, endpoint="https://push.example.com/abc",
            p256dh="old_key", auth="old_auth"))
        db.session.commit()
        resp = logged_in_client.post(f"{API_PREFIX}/push/subscribe", json={
            "endpoint": "https://push.example.com/abc",
            "keys": {"p256dh": "new_key", "auth": "new_auth"},
        })
        assert resp.status_code == 200
        sub = PushSubscription.query.filter_by(endpoint="https://push.example.com/abc").first()
        assert sub.p256dh == "new_key"

    def test_unsubscribe_by_endpoint(self, logged_in_client, user):
        db.session.add(PushSubscription(
            user_id=user.id, endpoint="https://push.example.com/del",
            p256dh="key", auth="auth"))
        db.session.commit()
        resp = logged_in_client.post(f"{API_PREFIX}/push/unsubscribe", json={
            "endpoint": "https://push.example.com/del",
        })
        assert resp.status_code == 200
        sub = PushSubscription.query.filter_by(endpoint="https://push.example.com/del").first()
        assert sub is None

    def test_unsubscribe_all(self, logged_in_client, user):
        for i in range(3):
            db.session.add(PushSubscription(
                user_id=user.id, endpoint=f"https://push.example.com/{i}",
                p256dh="key", auth="auth"))
        db.session.commit()
        resp = logged_in_client.post(f"{API_PREFIX}/push/unsubscribe", json={})
        assert resp.status_code == 200
        count = PushSubscription.query.filter_by(user_id=user.id).count()
        assert count == 0

    def test_vapid_key(self, logged_in_client, user):
        resp = logged_in_client.get(f"{API_PREFIX}/push/vapid-public-key")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "public_key" in data["data"]

    def test_push_unauthorized(self, client):
        resp = client.post(f"{API_PREFIX}/push/subscribe", json={
            "endpoint": "https://push.example.com/abc",
            "keys": {"p256dh": "k", "auth": "a"},
        })
        assert resp.status_code == 401
