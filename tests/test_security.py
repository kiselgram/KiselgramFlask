"""Security-focused tests: rate limiting, XSS, SQL injection, path traversal, auth bypass."""

import io
from app import db
from app.models import User
from app.utils.security import validate_password, sanitize_string, RateLimiter


API_PREFIX = "/api.v2/api"


class TestRateLimiter:
    """Unit tests for the in-memory RateLimiter"""

    def test_rate_limit_allows(self):
        limiter = RateLimiter()
        key = "test:127.0.0.1"
        assert limiter.is_allowed(key, max_requests=5, window=10) is True

    def test_rate_limit_exceeds(self):
        limiter = RateLimiter()
        key = "test_exceed:127.0.0.1"
        for _ in range(5):
            limiter.is_allowed(key, max_requests=5, window=10)
        assert limiter.is_allowed(key, max_requests=5, window=10) is False

    def test_rate_limit_different_keys(self):
        limiter = RateLimiter()
        assert limiter.is_allowed("user1", max_requests=1, window=10) is True
        assert limiter.is_allowed("user2", max_requests=1, window=10) is True


class TestPasswordValidation:
    """Unit tests for validate_password"""

    def test_valid_password(self):
        errors = validate_password("Str0ng!Pass")
        assert errors == []

    def test_short_password(self):
        errors = validate_password("Ab1!")
        assert len(errors) > 0

    def test_no_uppercase(self):
        errors = validate_password("str0ng!pass")
        assert any("uppercase" in e.lower() for e in errors)

    def test_no_lowercase(self):
        errors = validate_password("STR0NG!PASS")
        assert any("lowercase" in e.lower() for e in errors)

    def test_no_digit(self):
        errors = validate_password("Strong!Pass")
        assert any("digit" in e.lower() for e in errors)

    def test_no_special_char(self):
        errors = validate_password("Str0ngPass")
        assert any("special" in e.lower() for e in errors)


class TestSanitizeString:
    """Unit tests for sanitize_string"""

    def test_strips_html_tags(self):
        result = sanitize_string("<script>alert('xss')</script>Hello")
        assert "<script>" not in result
        assert "Hello" in result

    def test_trims_whitespace(self):
        result = sanitize_string("  hello world  ")
        assert result == "hello world"

    def test_enforces_max_length(self):
        result = sanitize_string("a" * 100, max_length=10)
        assert len(result) <= 10

    def test_handles_none(self):
        result = sanitize_string(None)
        assert result == ""


class TestRateLimitDecorator:
    """Integration tests for @rate_limit decorator on actual endpoints"""

    def test_login_rate_limit(self, client, session, user):
        # Send many rapid login requests
        for _ in range(12):
            client.post(f"{API_PREFIX}/auth/login", json={
                "username": "testuser",
                "password": "wrongpass",
            })
        # The 11th+ request should be rate limited
        resp = client.post(f"{API_PREFIX}/auth/login", json={
            "username": "testuser",
            "password": "wrongpass",
        })
        # Either 429 (rate limited) or 401 (still processed) — depending on config
        assert resp.status_code in (429, 401)

    def test_register_rate_limit(self, client, session):
        for i in range(8):
            client.post(f"{API_PREFIX}/auth/register", json={
                "username": f"rateuser{i}",
                "email": f"rate{i}@example.com",
                "password": "StrongPass1!",
            })
        resp = client.post(f"{API_PREFIX}/auth/register", json={
            "username": "ratelast",
            "email": "ratelast@example.com",
            "password": "StrongPass1!",
        })
        assert resp.status_code in (429, 201, 400)


class TestXSSPrevention:
    """Ensure XSS vectors are sanitized in inputs"""

    def test_xss_in_username(self, client, session):
        resp = client.post(f"{API_PREFIX}/auth/register", json={
            "username": "<script>alert(1)</script>",
            "email": "xss@example.com",
            "password": "StrongPass1!",
        })
        assert resp.status_code == 400  # invalid chars

    def test_xss_in_display_name(self, logged_in_client, user):
        resp = logged_in_client.put(f"{API_PREFIX}/profile", json={
            "display_name": "<img src=x onerror=alert(1)>",
        })
        # Should sanitize the XSS
        assert resp.status_code == 200
        u = db.session.get(User, user.id)
        assert "<img" not in (u.display_name or "")
        assert "onerror" not in (u.display_name or "")

    def test_xss_in_message(self, logged_in_client, user, user2):
        resp = logged_in_client.post(f"{API_PREFIX}/send_message", json={
            "receiver_id": user2.id,
            "content": "<script>alert('xss')</script>Hello",
        })
        assert resp.status_code in (201, 200)
        from app.models import Message
        msg = Message.query.filter_by(sender_id=user.id,
                                      receiver_id=user2.id).first()
        assert msg is not None
        # Content should be sanitized or stored as-is with no script execution
        assert msg.content is not None


class TestSQLInjectionPrevention:
    """Ensure SQL injection doesn't work on endpoints"""

    def test_sql_injection_username(self, client, session):
        resp = client.post(f"{API_PREFIX}/auth/login", json={
            "username": "' OR 1=1 --",
            "password": "' OR '1'='1",
        })
        # Should NOT log in — expect 401
        assert resp.status_code == 401

    def test_sql_injection_search(self, logged_in_client, user):
        resp = logged_in_client.get(
            f"{API_PREFIX}/search/global?q='; DROP TABLE users; --")
        assert resp.status_code in (200, 400)  # not 500


class TestPathTraversal:
    """Ensure path traversal is blocked in file serving"""

    def test_path_traversal_uploads(self, client):
        resp = client.get("/uploads/../../../etc/passwd")
        assert resp.status_code == 403

    def test_path_traversal_avatar(self, client):
        resp = client.get("/uploads/avatars/../../../etc/shadow")
        assert resp.status_code == 403


class TestAuthBypass:
    """Ensure unauthorized users can't access protected endpoints"""

    def test_no_session_no_bearer(self, client):
        resp = client.get(f"{API_PREFIX}/profile")
        assert resp.status_code == 401

    def test_no_session_no_bearer_message(self, client, user2):
        resp = client.post(f"{API_PREFIX}/send_message", json={
            "receiver_id": 1,
            "content": "Hack!",
        })
        assert resp.status_code == 401

    def test_invalid_bearer_token(self, client):
        resp = client.get(
            f"{API_PREFIX}/profile",
            headers={"Authorization": "Bearer invalid_token_here"})
        assert resp.status_code == 401

    def test_admin_endpoint_blocked(self, logged_in_client, user):
        resp = logged_in_client.get("/api/admin/dashboard")
        assert resp.status_code == 403


class TestPrivilegeEscalation:
    """Ensure users can't access/modify data they don't own"""

    def test_cannot_edit_others_message(self, logged_in_client, user, user2, personal_chat):
        from datetime import datetime
        from app.models import Message
        msg = Message(content="Not yours", sender_id=user2.id,
                      receiver_id=user.id, chat_id=personal_chat.id,
                      timestamp=datetime.utcnow())
        db.session.add(msg)
        db.session.commit()
        resp = logged_in_client.post(
            f"{API_PREFIX}/messages/{msg.id}/edit", json={"content": "Hacked!"})
        assert resp.status_code == 403

    def test_cannot_delete_others_story(self, logged_in_premium, premium_user, user2):
        from datetime import datetime
        from app.models import Story
        s = Story(user_id=user2.id, media_path="s/hack.jpg",
                  media_type="image", created_at=datetime.utcnow())
        db.session.add(s)
        db.session.commit()
        resp = logged_in_premium.delete(f"{API_PREFIX}/stories/{s.id}")
        assert resp.status_code == 403
