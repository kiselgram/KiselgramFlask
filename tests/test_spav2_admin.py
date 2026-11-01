from unittest.mock import patch, MagicMock
"""Tests for V2 API admin endpoints under /api.v2/api/admin/*."""

from datetime import datetime, timezone, timedelta
from app import db
from app.models import User, Report, LoginOtp, Chat, ChatMember, Message


API_PREFIX = "/api"


class TestV2AdminDashboard:
    """GET /api.v2/api/admin/dashboard"""

    def test_dashboard(self, logged_in_admin, admin_user):
        resp = logged_in_admin.get(f"{API_PREFIX}/admin/dashboard")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "total_users" in data["data"]
        assert "total_reports" in data["data"]

    def test_dashboard_forbidden(self, logged_in_client, user):
        resp = logged_in_client.get(f"{API_PREFIX}/admin/dashboard")
        assert resp.status_code == 403


class TestV2AdminReports:
    """GET /api.v2/api/admin/reports"""

    def test_list_reports(self, logged_in_admin, admin_user, user):
        r = Report(reporter_id=user.id, reason="Spam", status="pending",
                   created_at=datetime.utcnow())
        db.session.add(r)
        db.session.commit()
        resp = logged_in_admin.get(f"{API_PREFIX}/admin/reports?status=pending")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["data"]["reports"]) == 1
        assert data["data"]["reports"][0]["reason"] == "Spam"

    def test_resolve_report(self, logged_in_admin, admin_user, user):
        r = Report(reporter_id=user.id, reason="Test", status="pending",
                   created_at=datetime.utcnow())
        db.session.add(r)
        db.session.commit()
        resp = logged_in_admin.post(
            f"{API_PREFIX}/admin/reports/{r.id}/resolve")
        assert resp.status_code == 200
        assert db.session.get(Report, r.id).status == "resolved"

    def test_dismiss_report(self, logged_in_admin, admin_user, user):
        r = Report(reporter_id=user.id, reason="Test", status="pending",
                   created_at=datetime.utcnow())
        db.session.add(r)
        db.session.commit()
        resp = logged_in_admin.post(
            f"{API_PREFIX}/admin/reports/{r.id}/dismiss")
        assert resp.status_code == 200
        assert db.session.get(Report, r.id).status == "dismissed"

    def test_reports_forbidden(self, logged_in_client, user):
        resp = logged_in_client.get(f"{API_PREFIX}/admin/reports")
        assert resp.status_code == 403


class TestV2AdminUsers:
    """GET /api.v2/api/admin/users, user management"""

    def test_list_users(self, logged_in_admin, admin_user, user):
        resp = logged_in_admin.get(f"{API_PREFIX}/admin/users")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["data"]["users"]) >= 2

    def test_toggle_admin(self, logged_in_admin, admin_user, user):
        assert user.is_admin is False
        resp = logged_in_admin.post(
            f"{API_PREFIX}/admin/users/{user.id}/toggle-admin")
        assert resp.status_code == 200
        assert db.session.get(User, user.id).is_admin is True

    def test_delete_user(self, logged_in_admin, admin_user, user):
        resp = logged_in_admin.post(
            f"{API_PREFIX}/admin/users/{user.id}/delete")
        assert resp.status_code == 200
        assert db.session.get(User, user.id).is_deleted is True

    def test_delete_self_forbidden(self, logged_in_admin, admin_user):
        resp = logged_in_admin.post(
            f"{API_PREFIX}/admin/users/{admin_user.id}/delete")
        assert resp.status_code == 403

    def test_update_user(self, logged_in_admin, admin_user, user):
        resp = logged_in_admin.post(
            f"{API_PREFIX}/admin/users/{user.id}/update", json={
                "display_name": "Admin Updated",
            })
        assert resp.status_code == 200
        assert db.session.get(User, user.id).display_name == "Admin Updated"

    def test_set_password(self, logged_in_admin, admin_user, user):
        resp = logged_in_admin.post(
            f"{API_PREFIX}/admin/users/{user.id}/set-password", json={
                "password": "NewStr0ng!",
            })
        assert resp.status_code == 200

    def test_create_user(self, logged_in_admin, admin_user):
        resp = logged_in_admin.post(f"{API_PREFIX}/admin/users/create", json={
            "username": "newadminuser",
            "email": "newadmin@example.com",
            "password": "str0ngPass!",
            "is_admin": True,
        })
        assert resp.status_code == 200
        u = User.query.filter_by(username="newadminuser").first()
        assert u is not None
        assert u.is_admin is True

    def test_create_user_short_password(self, logged_in_admin, admin_user):
        resp = logged_in_admin.post(f"{API_PREFIX}/admin/users/create", json={
            "username": "shortpw",
            "password": "ab",
        })
        assert resp.status_code == 400

    def test_admin_users_forbidden(self, logged_in_client, user):
        resp = logged_in_client.get(f"{API_PREFIX}/admin/users")
        assert resp.status_code == 403


class TestV2Admin2FA:
    """GET /api.v2/api/admin/2fa/*"""

    def test_twofa_overview(self, logged_in_admin, admin_user):
        resp = logged_in_admin.get(f"{API_PREFIX}/admin/2fa/overview")
        assert resp.status_code == 200
        assert "total" in resp.get_json()["data"]

    def test_twofa_cleanup(self, logged_in_admin, admin_user):
        resp = logged_in_admin.post(f"{API_PREFIX}/admin/2fa/cleanup")
        assert resp.status_code == 200


class TestV2AdminChats:
    """GET /api.v2/api/admin/chats"""

    def test_list_chats(self, logged_in_admin, admin_user, user):
        resp = logged_in_admin.get(f"{API_PREFIX}/admin/chats")
        assert resp.status_code == 200

    def test_chat_detail(self, logged_in_admin, admin_user, user, user2):
        from app.models import Chat
        c = Chat(chat_type="personal", user1_id=user.id, user2_id=user2.id)
        db.session.add(c)
        db.session.commit()
        resp = logged_in_admin.get(f"{API_PREFIX}/admin/chats/{c.id}")
        assert resp.status_code == 200
        assert resp.get_json()["data"]["chat_type"] == "personal"

    def test_chat_messages(self, logged_in_admin, admin_user, user, user2):
        c = Chat(chat_type="personal", user1_id=user.id, user2_id=user2.id)
        db.session.add(c)
        db.session.flush()
        db.session.add(Message(content="Admin view", sender_id=user.id,
                               receiver_id=user2.id, chat_id=c.id,
                               timestamp=datetime.utcnow()))
        db.session.commit()
        resp = logged_in_admin.get(
            f"{API_PREFIX}/admin/chats/{c.id}/messages")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["data"]["messages"]) >= 1

    def test_admin_delete_message(self, logged_in_admin, admin_user, user, user2):
        c = Chat(chat_type="personal", user1_id=user.id, user2_id=user2.id)
        db.session.add(c)
        db.session.flush()
        msg = Message(content="Delete from admin", sender_id=user.id,
                      receiver_id=user2.id, chat_id=c.id, timestamp=datetime.utcnow())
        db.session.add(msg)
        db.session.flush()
        resp = logged_in_admin.post(
            f"{API_PREFIX}/admin/chats/{c.id}/messages/{msg.id}/delete")
        assert resp.status_code == 200

    def test_admin_restore_message(self, logged_in_admin, admin_user, user, user2):
        c = Chat(chat_type="personal", user1_id=user.id, user2_id=user2.id)
        db.session.add(c)
        db.session.flush()
        msg = Message(content="Restore me", sender_id=user.id,
                      receiver_id=user2.id, chat_id=c.id, is_deleted=True,
                      timestamp=datetime.utcnow())
        db.session.add(msg)
        db.session.commit()
        resp = logged_in_admin.post(
            f"{API_PREFIX}/admin/chats/{c.id}/messages/{msg.id}/restore")
        assert resp.status_code == 200
        assert db.session.get(Message, msg.id).is_deleted is False


class TestV2AdminChannels:
    """POST /api.v2/api/admin/channels/create"""

    def test_create_channel(self, logged_in_admin, admin_user):
        resp = logged_in_admin.post(f"{API_PREFIX}/admin/channels/create", json={
            "name": "Admin Channel",
            "description": "Created by admin",
        })
        assert resp.status_code == 200
        c = Chat.query.filter_by(name="Admin Channel").first()
        assert c is not None


class TestV2AdminPostToChat:
    """POST /api.v2/api/admin/chats/<id>/post"""

    def test_post_to_chat(self, logged_in_admin, admin_user, user, user2):
        c = Chat(chat_type="personal", user1_id=user.id, user2_id=user2.id)
        db.session.add(c)
        db.session.commit()
        resp = logged_in_admin.post(
            f"{API_PREFIX}/admin/chats/{c.id}/post", json={
                "content": "Admin post",
            })
        assert resp.status_code == 200
        msg = Message.query.filter_by(chat_id=c.id).first()
        assert msg is not None


class TestV2AdminMail:
    """GET/POST/DELETE /api.v2/api/admin/mail/accounts"""

    @patch("app.routes.spav2.admin._mailadmin_call")
    def test_list_mail_accounts(self, mock_mail, logged_in_admin, admin_user):
        mock_mail.return_value = {"success": True, "accounts": []}
        resp = logged_in_admin.get(f"{API_PREFIX}/admin/mail/accounts")
        assert resp.status_code == 200


class TestV2AdminPromo:
    """GET/POST /api.v2/api/admin/promo/*"""

    def test_promo_list(self, logged_in_admin, admin_user):
        resp = logged_in_admin.get(f"{API_PREFIX}/admin/promo/list")
        assert resp.status_code == 200
        assert "promo_codes" in resp.get_json()

    def test_promo_generate(self, logged_in_admin, admin_user):
        resp = logged_in_admin.post(f"{API_PREFIX}/admin/promo/generate", json={
            "duration_days": 30,
            "max_uses": 5,
        })
        assert resp.status_code == 200
        assert "code" in resp.get_json()["data"]
