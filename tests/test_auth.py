import pytest
from app import db
from app.models import User, EmailVerification
from datetime import datetime
import re


class TestRegistration:
    def test_register_success(self, client, session):
        resp = client.post("/auth/register", data={
            "username": "newuser",
            "email": "new@test.com",
            "password": "strongpass",
            "confirm_password": "strongpass",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"verify" in resp.data.lower() or b"check" in resp.data.lower()
        user = User.query.filter_by(username="newuser").first()
        assert user is not None
        assert user.email_verified is False
        assert user.check_password("strongpass")
        ver = EmailVerification.query.filter_by(user_id=user.id).first()
        assert ver is not None

    def test_register_password_mismatch(self, client, session):
        resp = client.post("/auth/register", data={
            "username": "fail", "email": "fail@test.com",
            "password": "abc123", "confirm_password": "xyz789",
        })
        assert b"do not match" in resp.data.lower()

    def test_register_short_password(self, client, session):
        resp = client.post("/auth/register", data={
            "username": "shortpwd", "email": "short@test.com",
            "password": "ab", "confirm_password": "ab",
        })
        assert b"at least 6" in resp.data.lower() or b"characters" in resp.data.lower()

    def test_register_short_username(self, client, session):
        resp = client.post("/auth/register", data={
            "username": "ab", "email": "ab@test.com",
            "password": "strongpass", "confirm_password": "strongpass",
        })
        assert b"at least 3" in resp.data.lower()

    def test_register_invalid_username_chars(self, client, session):
        resp = client.post("/auth/register", data={
            "username": "user name!", "email": "un@test.com",
            "password": "strongpass", "confirm_password": "strongpass",
        })
        assert b"only contain" in resp.data.lower()

    def test_register_duplicate_username(self, client, user, session):
        resp = client.post("/auth/register", data={
            "username": "testuser", "email": "another@test.com",
            "password": "strongpass", "confirm_password": "strongpass",
        })
        assert b"already taken" in resp.data.lower()

    def test_register_duplicate_email(self, client, user, session):
        resp = client.post("/auth/register", data={
            "username": "newguy", "email": "test@example.com",
            "password": "strongpass", "confirm_password": "strongpass",
        })
        assert b"already registered" in resp.data.lower()

    def test_register_missing_fields(self, client, session):
        resp = client.post("/auth/register", data={
            "username": "", "email": "", "password": "",
        })
        assert b"required" in resp.data.lower()


class TestLogin:
    def test_login_success(self, client, user):
        resp = client.post("/auth/login", data={
            "username": user.username, "password": "testpass",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert "chat_list" in resp.request.url

    def test_login_wrong_password(self, client, user):
        resp = client.post("/auth/login", data={
            "username": user.username, "password": "wrongpass",
        })
        assert b"Invalid" in resp.data

    def test_login_nonexistent_user(self, client, user):
        resp = client.post("/auth/login", data={
            "username": "nobody", "password": "pass123",
        })
        assert b"Invalid" in resp.data

    def test_login_unverified_email(self, client, session):
        u = User(username="unverified", email="un@test.com")
        u.set_password("testpass")
        db.session.add(u)
        db.session.commit()
        resp = client.post("/auth/login", data={
            "username": "unverified", "password": "testpass",
        })
        assert b"verify" in resp.data.lower()

    def test_login_missing_fields(self, client):
        resp = client.post("/auth/login", data={"username": "", "password": ""})
        assert b"required" in resp.data.lower()


class TestLogout:
    def test_logout_clears_session(self, client, user):
        with client.session_transaction() as sess:
            sess["user_id"] = user.id
            sess["username"] = user.username
        client.get("/auth/logout", follow_redirects=True)
        with client.session_transaction() as sess:
            assert "user_id" not in sess

    def test_logout_sets_offline(self, client, user):
        user.is_online = True
        db.session.commit()
        with client.session_transaction() as sess:
            sess["user_id"] = user.id
            sess["username"] = user.username
        client.get("/auth/logout", follow_redirects=True)
        user = User.query.get(user.id)
        assert user.is_online is False


class TestEmailVerification:
    def test_verify_valid_token(self, client, session):
        client.post("/auth/register", data={
            "username": "verifyuser", "email": "verify@test.com",
            "password": "validpass", "confirm_password": "validpass",
        })
        user = User.query.filter_by(username="verifyuser").first()
        assert user is not None
        ver = EmailVerification.query.filter_by(user_id=user.id).first()
        token = ver.token
        resp = client.get(f"/auth/verify/{token}", follow_redirects=True)
        assert resp.status_code == 200
        user = User.query.get(user.id)
        assert user.email_verified is True

    def test_verify_invalid_token(self, client):
        resp = client.get("/auth/verify/invalidtoken123")
        # Should redirect to login (flash message set)
        assert resp.status_code == 302
        assert "/auth/login" in resp.location

    def test_verify_expired_token(self, client, session):
        u = User(username="expired", email="exp@test.com")
        u.set_password("pass123")
        db.session.add(u)
        db.session.commit()
        ver = EmailVerification(
            user_id=u.id, token="expiredtoken",
            expires_at=datetime.utcnow(),
        )
        db.session.add(ver)
        db.session.commit()
        resp = client.get("/auth/verify/expiredtoken")
        # Should redirect to login (flash message set)
        assert resp.status_code == 302
        assert "/auth/login" in resp.location


class TestCompleteRegistration:
    def test_complete_registration_flow(self, client, user):
        with client.session_transaction() as sess:
            sess["user_id"] = user.id
            sess["username"] = user.username
        resp = client.post("/auth/complete-registration", data={
            "username": "testuser_final",
            "display_name": "Test User Final",
            "avatar": "avatar1.jpg",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert "chat_list" in resp.request.url
        updated = User.query.get(user.id)
        assert updated.username == "testuser_final"
        assert updated.display_name == "Test User Final"
        assert "avatar1.jpg" in updated.avatar_url

    def test_complete_registration_short_username(self, client, user):
        with client.session_transaction() as sess:
            sess["user_id"] = user.id
            sess["username"] = user.username
        resp = client.post("/auth/complete-registration", data={
            "username": "ab", "display_name": "Test",
        }, follow_redirects=True)
        assert b"at least" in resp.data.lower() or b"characters" in resp.data.lower()

    def test_complete_registration_requires_login(self, client):
        resp = client.get("/auth/complete-registration", follow_redirects=True)
        assert "login" in resp.request.url


class TestAPIAuth:
    def test_api_login(self, client, user):
        resp = client.post("/auth/api/login", data={
            "username": user.username, "password": "testpass",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_api_login_invalid(self, client, user):
        resp = client.post("/auth/api/login", data={
            "username": user.username, "password": "wrong",
        })
        assert resp.status_code == 401

    def test_api_login_missing(self, client):
        resp = client.post("/auth/api/login", data={})
        assert resp.status_code == 400

    def test_api_check_username(self, logged_in_client, user):
        resp = logged_in_client.post("/auth/api/check_username", json={"username": "newuser"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["available"] is True

    def test_api_check_username_taken(self, logged_in_client, user, user2):
        resp = logged_in_client.post("/auth/api/check_username", json={"username": "friend"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["available"] is False

    def test_api_check_username_short(self, logged_in_client):
        resp = logged_in_client.post("/auth/api/check_username", json={"username": "ab"})
        data = resp.get_json()
        assert data["available"] is False

    def test_api_get_user_id(self, logged_in_client, user):
        resp = logged_in_client.get("/auth/api/get_user_id")
        assert resp.status_code == 204
        assert resp.headers.get("X-User-Id") == str(user.id)

    def test_api_get_user_id_unauthenticated(self, client):
        resp = client.get("/auth/api/get_user_id")
        assert resp.status_code == 401
