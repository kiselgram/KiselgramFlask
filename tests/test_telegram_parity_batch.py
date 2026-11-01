"""Tests for Telegram-parity batch endpoints (silent, contact share, reminders, etc.)."""

from datetime import datetime, timedelta
from app import db
from app.models import Message, User, Chat, ChatMember, ChatSubscriber

API = "/api.v2/api"


def _login(app, user):
    c = app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = user.id
    return c


def _personal_chat(user, user2):
    a, b = sorted([user.id, user2.id])
    chat = Chat(chat_type='personal', user1_id=a, user2_id=b)
    db.session.add(chat)
    db.session.flush()
    db.session.add(ChatMember(chat_id=chat.id, user_id=user.id, role='participant'))
    db.session.add(ChatMember(chat_id=chat.id, user_id=user2.id, role='participant'))
    db.session.commit()
    return chat


def _group(owner, members=(), name="TG"):
    import secrets
    c = Chat(chat_type="group", name=name, owner_id=owner.id, is_public=True,
             invite_link=f"grp_{secrets.token_hex(4)}", created_at=datetime.utcnow())
    db.session.add(c)
    db.session.flush()
    db.session.add(ChatMember(user_id=owner.id, chat_id=c.id, role="owner"))
    for m in members:
        db.session.add(ChatMember(user_id=m.id, chat_id=c.id, role="member"))
    db.session.commit()
    return c


def _channel(owner, name="CH"):
    import secrets
    c = Chat(chat_type="channel", name=name, owner_id=owner.id, is_public=True,
             invite_link=f"ch_{secrets.token_hex(4)}", created_at=datetime.utcnow())
    db.session.add(c)
    db.session.flush()
    db.session.add(ChatSubscriber(user_id=owner.id, chat_id=c.id))
    db.session.commit()
    return c


class TestSilentMessages:
    def test_send_silent(self, app, user, user2):
        c = _login(app, user)
        r = c.post(f"{API}/send_message", json={"receiver_id": user2.id, "content": "shh", "silent": True})
        assert r.status_code == 201
        assert r.get_json()["data"]["message"]["silent"] is True

    def test_send_normal_not_silent(self, app, user, user2):
        c = _login(app, user)
        r = c.post(f"{API}/send_message", json={"receiver_id": user2.id, "content": "hi"})
        assert r.status_code == 201
        assert r.get_json()["data"]["message"]["silent"] is False

    def test_unauth(self, client):
        r = client.post(f"{API}/send_message", json={"receiver_id": 1, "content": "x", "silent": True})
        assert r.status_code == 401


class TestContactShare:
    def test_share_contact(self, app, user, user2):
        c = _login(app, user)
        r = c.post(f"{API}/share_contact", json={"receiver_id": user2.id, "contact_name": "Alice", "contact_phone": "+123"})
        assert r.status_code == 201
        d = r.get_json()["data"]["message"]
        assert d["contact_name"] == "Alice"
        assert d["contact_phone"] == "+123"

    def test_share_contact_by_user(self, app, user, user2):
        c = _login(app, user)
        r = c.post(f"{API}/share_contact", json={"receiver_id": user2.id, "user_id": user2.id})
        assert r.status_code == 201
        assert r.get_json()["data"]["message"]["contact_name"] is not None

    def test_missing_fields(self, app, user, user2):
        c = _login(app, user)
        r = c.post(f"{API}/share_contact", json={"receiver_id": user2.id})
        assert r.status_code == 400

    def test_unauth(self, client):
        r = client.post(f"{API}/share_contact", json={"receiver_id": 1, "contact_name": "A", "contact_phone": "1"})
        assert r.status_code == 401


class TestReminders:
    def test_remind(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        msg = Message(content="remind me", sender_id=user.id, receiver_id=user2.id, chat_id=chat.id, timestamp=datetime.utcnow())
        db.session.add(msg); db.session.commit()
        r = c.post(f"{API}/messages/{msg.id}/remind", json={"when": "2030-01-01T10:00:00"})
        assert r.status_code == 200
        assert "reminder_at" in r.get_json()["data"]

    def test_remind_default(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        msg = Message(content="r", sender_id=user.id, receiver_id=user2.id, chat_id=chat.id, timestamp=datetime.utcnow())
        db.session.add(msg); db.session.commit()
        r = c.post(f"{API}/messages/{msg.id}/remind", json={})
        assert r.status_code == 200

    def test_remind_not_found(self, app, user):
        c = _login(app, user)
        r = c.post(f"{API}/messages/99999/remind", json={})
        assert r.status_code == 404

    def test_remind_unauth(self, client):
        r = client.post(f"{API}/messages/1/remind", json={})
        assert r.status_code == 401

    def test_remind_invalid_when(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        msg = Message(content="r", sender_id=user.id, receiver_id=user2.id, chat_id=chat.id, timestamp=datetime.utcnow())
        db.session.add(msg); db.session.commit()
        r = c.post(f"{API}/messages/{msg.id}/remind", json={"when": "not-a-date"})
        assert r.status_code == 400


class TestSendWhenOnline:
    def test_send_when_online(self, app, user, user2):
        c = _login(app, user)
        r = c.post(f"{API}/send_message", json={"receiver_id": user2.id, "content": "later", "send_when_online": True})
        assert r.status_code == 201
        assert r.get_json()["data"]["message"]["send_when_online"] is True


class TestForwardMulti:
    def test_forward_multi(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        msg = Message(content="fwd", sender_id=user.id, receiver_id=user2.id, chat_id=chat.id, timestamp=datetime.utcnow())
        db.session.add(msg); db.session.commit()
        g = _group(user2, name="G2")
        r = c.post(f"{API}/messages/forward_multi", json={"message_id": msg.id, "target_chat_ids": [g.id]})
        assert r.status_code == 200
        assert r.get_json()["data"]["count"] >= 0

    def test_forward_multi_no_targets(self, app, user):
        c = _login(app, user)
        r = c.post(f"{API}/messages/forward_multi", json={"message_id": 1, "target_chat_ids": []})
        assert r.status_code == 400

    def test_forward_multi_unauth(self, client):
        r = client.post(f"{API}/messages/forward_multi", json={"message_id": 1, "target_chat_ids": [1]})
        assert r.status_code == 401


class TestChatExport:
    def test_export(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        Message(content="hi", sender_id=user.id, receiver_id=user2.id, chat_id=chat.id, timestamp=datetime.utcnow()).save() if False else None
        m = Message(content="hi", sender_id=user.id, receiver_id=user2.id, chat_id=chat.id, timestamp=datetime.utcnow())
        db.session.add(m); db.session.commit()
        r = c.get(f"{API}/chats/{chat.id}/export")
        assert r.status_code == 200
        assert r.get_json()["data"]["count"] >= 1

    def test_export_forbidden(self, app, user, user2):
        c = _login(app, user2)
        chat = _personal_chat(user, user2)
        # user2 is in chat, so allowed; test non-member
        u3 = User(username="u3", email="u3@x.com", email_verified=True)
        u3.set_password("p"); db.session.add(u3); db.session.commit()
        c3 = _login(app, u3)
        r = c3.get(f"{API}/chats/{chat.id}/export")
        assert r.status_code == 403

    def test_export_unauth(self, client):
        r = client.get(f"{API}/chats/1/export")
        assert r.status_code == 401


class TestDeleteAccount:
    def test_delete_account(self, app, user):
        c = _login(app, user)
        r = c.post(f"{API}/account/delete", json={"password": "testpass"})
        assert r.status_code == 200
        assert r.get_json()["success"] is True

    def test_delete_account_wrong_pw(self, app, user):
        c = _login(app, user)
        r = c.post(f"{API}/account/delete", json={"password": "wrong"})
        assert r.status_code == 403

    def test_delete_account_unauth(self, client):
        r = client.post(f"{API}/account/delete", json={})
        assert r.status_code == 401


class TestSelfDestruct:
    def test_set(self, app, user):
        c = _login(app, user)
        r = c.post(f"{API}/account/self_destruct", json={"days": 30})
        assert r.status_code == 200
        assert r.get_json()["data"]["days"] == 30

    def test_invalid_days(self, app, user):
        c = _login(app, user)
        r = c.post(f"{API}/account/self_destruct", json={"days": 5})
        assert r.status_code == 400

    def test_get(self, app, user):
        c = _login(app, user)
        r = c.get(f"{API}/account/self_destruct")
        assert r.status_code == 200

    def test_unauth(self, client):
        r = client.get(f"{API}/account/self_destruct")
        assert r.status_code == 401


class TestRecentActions:
    def test_recent(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        Message(content="act", sender_id=user.id, receiver_id=user2.id, chat_id=chat.id, timestamp=datetime.utcnow()).save() if False else None
        m = Message(content="act", sender_id=user.id, receiver_id=user2.id, chat_id=chat.id, timestamp=datetime.utcnow())
        db.session.add(m); db.session.commit()
        r = c.get(f"{API}/account/recent_actions")
        assert r.status_code == 200
        assert r.get_json()["data"]["count"] >= 1

    def test_unauth(self, client):
        r = client.get(f"{API}/account/recent_actions")
        assert r.status_code == 401


class TestImportHistory:
    def test_import(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        r = c.post(f"{API}/chats/{chat.id}/import_history", json={"messages": ["a", "b"]})
        assert r.status_code == 200
        assert r.get_json()["data"]["imported"] == 2

    def test_import_empty(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        r = c.post(f"{API}/chats/{chat.id}/import_history", json={"messages": []})
        assert r.status_code == 400

    def test_import_unauth(self, client):
        r = client.post(f"{API}/chats/1/import_history", json={"messages": ["a"]})
        assert r.status_code == 401

    def test_import_forbidden(self, app, user, user2):
        c = _login(app, user2)
        chat = _personal_chat(user, user2)
        u3 = User(username="u3x", email="u3x@x.com", email_verified=True)
        u3.set_password("p"); db.session.add(u3); db.session.commit()
        c3 = _login(app, u3)
        r = c3.post(f"{API}/chats/{chat.id}/import_history", json={"messages": ["a"]})
        assert r.status_code == 403


class TestGifSend:
    def test_send_gif_no_url(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        r = c.post(f"{API}/send_gif", json={"chat_id": chat.id})
        assert r.status_code == 400

    def test_send_gif(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        r = c.post(f"{API}/send_gif", json={"chat_id": chat.id, "gif_url": "http://x.com/a.gif"})
        assert r.status_code == 201
        assert r.get_json()["data"]["message"]["file_type"] == "gif"

    def test_send_gif_unauth(self, client):
        r = client.post(f"{API}/send_gif", json={"chat_id": 1, "gif_url": "u"})
        assert r.status_code == 401


class TestVoiceSend:
    def test_send_voice_no_url(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        r = c.post(f"{API}/send_voice", json={"chat_id": chat.id})
        assert r.status_code == 400

    def test_send_voice(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        r = c.post(f"{API}/send_voice", json={"chat_id": chat.id, "file_url": "http://x.com/a.ogg", "waveform": [1, 2, 3]})
        assert r.status_code == 201
        d = r.get_json()["data"]["message"]
        assert d["file_type"] == "voice"
        assert d["waveform"] == [1, 2, 3]

    def test_send_voice_unauth(self, client):
        r = client.post(f"{API}/send_voice", json={"chat_id": 1, "file_url": "u"})
        assert r.status_code == 401


class TestChangePassword:
    def test_change_password(self, app, user):
        c = _login(app, user)
        r = c.post(f"{API}/profile/change_password", json={"old_password": "testpass", "new_password": "newpass123"})
        assert r.status_code == 200

    def test_change_password_wrong_old(self, app, user):
        c = _login(app, user)
        r = c.post(f"{API}/profile/change_password", json={"old_password": "wrong", "new_password": "newpass123"})
        assert r.status_code == 403

    def test_change_password_short(self, app, user):
        c = _login(app, user)
        r = c.post(f"{API}/profile/change_password", json={"old_password": "testpass", "new_password": "short"})
        assert r.status_code == 400

    def test_change_password_unauth(self, client):
        r = client.post(f"{API}/profile/change_password", json={"new_password": "newpass123"})
        assert r.status_code == 401


class TestChangeEmail:
    def test_change_email(self, app, user):
        c = _login(app, user)
        r = c.post(f"{API}/profile/change_email", json={"email": "newemail@x.com"})
        assert r.status_code == 200
        assert r.get_json()["data"]["email"] == "newemail@x.com"

    def test_change_email_invalid(self, app, user):
        c = _login(app, user)
        r = c.post(f"{API}/profile/change_email", json={"email": "notanemail"})
        assert r.status_code == 400

    def test_change_email_unauth(self, client):
        r = client.post(f"{API}/profile/change_email", json={"email": "x@y.com"})
        assert r.status_code == 401


class TestChangeUsername:
    def test_change_username(self, app, user):
        c = _login(app, user)
        r = c.post(f"{API}/profile/change_username", json={"username": "newname"})
        assert r.status_code == 200
        assert r.get_json()["data"]["username"] == "newname"

    def test_change_username_short(self, app, user):
        c = _login(app, user)
        r = c.post(f"{API}/profile/change_username", json={"username": "ab"})
        assert r.status_code == 400

    def test_change_username_unauth(self, client):
        r = client.post(f"{API}/profile/change_username", json={"username": "x"})
        assert r.status_code == 401


class TestChangePhone:
    def test_change_phone(self, app, user):
        c = _login(app, user)
        r = c.post(f"{API}/profile/change_phone", json={"phone": "+1234567890"})
        assert r.status_code == 200

    def test_change_phone_invalid(self, app, user):
        c = _login(app, user)
        r = c.post(f"{API}/profile/change_phone", json={"phone": "1"})
        assert r.status_code == 400

    def test_change_phone_unauth(self, client):
        r = client.post(f"{API}/profile/change_phone", json={"phone": "+1234567890"})
        assert r.status_code == 401


class TestRevokeAllSessions:
    def test_revoke_all(self, app, user):
        c = _login(app, user)
        r = c.post(f"{API}/profile/revoke_all_sessions", json={})
        assert r.status_code == 200

    def test_unauth(self, client):
        r = client.post(f"{API}/profile/revoke_all_sessions", json={})
        assert r.status_code == 401


class TestAccountInfo:
    def test_account_info(self, app, user):
        c = _login(app, user)
        r = c.get(f"{API}/profile/account_info" if False else f"{API}/account/info")
        assert r.status_code == 200
        assert "id" in r.get_json()["data"]

    def test_unauth(self, client):
        r = client.get(f"{API}/account/info")
        assert r.status_code == 401


class TestMarkAllRead:
    def test_mark_all_read(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        m = Message(content="unread", sender_id=user2.id, receiver_id=user.id, chat_id=chat.id, timestamp=datetime.utcnow(), is_read=False)
        db.session.add(m); db.session.commit()
        r = c.post(f"{API}/chats/mark_all_read")
        assert r.status_code == 200

    def test_unauth(self, client):
        r = client.post(f"{API}/chats/mark_all_read")
        assert r.status_code == 401


class TestClearChat:
    def test_clear(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        m = Message(content="x", sender_id=user.id, receiver_id=user2.id, chat_id=chat.id, timestamp=datetime.utcnow())
        db.session.add(m); db.session.commit()
        r = c.post(f"{API}/chats/{chat.id}/clear")
        assert r.status_code == 200

    def test_clear_forbidden(self, app, user, user2):
        c = _login(app, user2)
        chat = _personal_chat(user, user2)
        u3 = User(username="u3y", email="u3y@x.com", email_verified=True)
        u3.set_password("p"); db.session.add(u3); db.session.commit()
        c3 = _login(app, u3)
        r = c3.post(f"{API}/chats/{chat.id}/clear")
        assert r.status_code == 403

    def test_clear_unauth(self, client):
        r = client.post(f"{API}/chats/1/clear")
        assert r.status_code == 401


class TestDeleteChat:
    def test_delete_chat(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        r = c.post(f"{API}/chats/{chat.id}/delete")
        assert r.status_code == 200

    def test_delete_unauth(self, client):
        r = client.post(f"{API}/chats/1/delete")
        assert r.status_code == 401


class TestUpdatePrivacy:
    def test_update_privacy(self, app, user):
        c = _login(app, user)
        r = c.put(f"{API}/profile/privacy", json={"privacy_last_seen": "nobody"})
        assert r.status_code == 200

    def test_update_privacy_unauth(self, client):
        r = client.put(f"{API}/profile/privacy", json={"privacy_last_seen": "nobody"})
        assert r.status_code == 401


class TestUpdateSettings:
    def test_update_settings(self, app, user):
        c = _login(app, user)
        r = c.post(f"{API}/profile/settings", json={"theme": "dark", "font_size": 16})
        assert r.status_code == 200

    def test_update_settings_unauth(self, client):
        r = client.post(f"{API}/profile/settings", json={"theme": "dark"})
        assert r.status_code == 401


class TestSessionsList:
    def test_list_sessions(self, app, user):
        c = _login(app, user)
        r = c.get(f"{API}/profile/sessions")
        assert r.status_code == 200
        assert "sessions" in r.get_json()["data"]

    def test_list_sessions_unauth(self, client):
        r = client.get(f"{API}/profile/sessions")
        assert r.status_code == 401


class TestRevokeSession:
    def test_revoke_session_not_found(self, app, user):
        c = _login(app, user)
        r = c.post(f"{API}/profile/sessions/99999/revoke")
        assert r.status_code == 404

    def test_revoke_session_unauth(self, client):
        r = client.post(f"{API}/profile/sessions/1/revoke")
        assert r.status_code == 401


class TestStarMessage:
    def test_star(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        m = Message(content="star me", sender_id=user.id, receiver_id=user2.id, chat_id=chat.id, timestamp=datetime.utcnow())
        db.session.add(m); db.session.commit()
        r = c.post(f"{API}/messages/{m.id}/star")
        assert r.status_code == 200
        assert r.get_json()["data"]["starred"] is True

    def test_unstar(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        m = Message(content="star", sender_id=user.id, receiver_id=user2.id, chat_id=chat.id, timestamp=datetime.utcnow(), is_saved=True)
        db.session.add(m); db.session.commit()
        r = c.post(f"{API}/messages/{m.id}/unstar")
        assert r.status_code == 200
        assert r.get_json()["data"]["starred"] is False

    def test_starred_list(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        m = Message(content="saved", sender_id=user.id, receiver_id=user2.id, chat_id=chat.id, timestamp=datetime.utcnow(), is_saved=True)
        db.session.add(m); db.session.commit()
        r = c.get(f"{API}/messages/starred")
        assert r.status_code == 200
        assert r.get_json()["data"]["count"] >= 1

    def test_star_not_found(self, app, user):
        c = _login(app, user)
        r = c.post(f"{API}/messages/99999/star")
        assert r.status_code == 404

    def test_star_unauth(self, client):
        r = client.post(f"{API}/messages/1/star")
        assert r.status_code == 401


class TestOnlineUsers:
    def test_online_users(self, app, user):
        c = _login(app, user)
        r = c.get(f"{API}/users/online")
        assert r.status_code == 200
        assert "users" in r.get_json()["data"]

    def test_online_users_unauth(self, client):
        r = client.get(f"{API}/users/online")
        assert r.status_code == 401


class TestChatInfo:
    def test_chat_info(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        r = c.get(f"{API}/chats/{chat.id}/info")
        assert r.status_code == 200
        assert r.get_json()["data"]["id"] == chat.id

    def test_chat_info_forbidden(self, app, user, user2):
        c = _login(app, user2)
        chat = _personal_chat(user, user2)
        u3 = User(username="u3z", email="u3z@x.com", email_verified=True)
        u3.set_password("p"); db.session.add(u3); db.session.commit()
        c3 = _login(app, u3)
        r = c3.get(f"{API}/chats/{chat.id}/info")
        assert r.status_code == 403

    def test_chat_info_unauth(self, client):
        r = client.get(f"{API}/chats/1/info")
        assert r.status_code == 401


class TestLeaveJoinChat:
    def test_leave_personal_not_allowed(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        r = c.post(f"{API}/chats/{chat.id}/leave")
        assert r.status_code == 400

    def test_join_group(self, app, user, user2):
        c = _login(app, user2)
        g = _group(user)
        r = c.post(f"{API}/chats/{g.id}/join")
        assert r.status_code == 200

    def test_leave_unauth(self, client):
        r = client.post(f"{API}/chats/1/leave")
        assert r.status_code == 401


class TestGroupChannelMute:
    def test_mute_group(self, app, user):
        c = _login(app, user)
        g = _group(user)
        r = c.post(f"{API}/groups/{g.id}/mute", json={})
        assert r.status_code == 200
        assert r.get_json()["data"]["muted"] is True

    def test_unmute_group(self, app, user):
        c = _login(app, user)
        g = _group(user)
        c.post(f"{API}/groups/{g.id}/mute", json={})
        r = c.post(f"{API}/groups/{g.id}/unmute")
        assert r.status_code == 200
        assert r.get_json()["data"]["muted"] is False

    def test_mute_channel(self, app, user):
        c = _login(app, user)
        ch = _channel(user)
        r = c.post(f"{API}/channels/{ch.id}/mute", json={})
        assert r.status_code == 200

    def test_unmute_channel(self, app, user):
        c = _login(app, user)
        ch = _channel(user)
        c.post(f"{API}/channels/{ch.id}/mute", json={})
        r = c.post(f"{API}/channels/{ch.id}/unmute")
        assert r.status_code == 200

    def test_mute_group_unauth(self, client):
        r = client.post(f"{API}/groups/1/mute", json={})
        assert r.status_code == 401


class TestChannelAdmins:
    def test_get_channel_admins(self, app, user):
        c = _login(app, user)
        ch = _channel(user)
        r = c.get(f"{API}/channels/{ch.id}/admins")
        assert r.status_code == 200
        assert "admins" in r.get_json()["data"]

    def test_remove_channel_admin(self, app, user, user2):
        c = _login(app, user)
        ch = _channel(user)
        r = c.post(f"{API}/channels/{ch.id}/remove_admin", json={"user_id": user2.id})
        assert r.status_code == 200

    def test_channel_admins_unauth(self, client):
        r = client.get(f"{API}/channels/1/admins")
        assert r.status_code == 401


class TestReportMessage:
    def test_report_message(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        m = Message(content="bad", sender_id=user2.id, receiver_id=user.id, chat_id=chat.id, timestamp=datetime.utcnow())
        db.session.add(m); db.session.commit()
        r = c.post(f"{API}/messages/{m.id}/report", json={"reason": "spam"})
        assert r.status_code == 200

    def test_report_not_found(self, app, user):
        c = _login(app, user)
        r = c.post(f"{API}/messages/99999/report", json={"reason": "spam"})
        assert r.status_code == 404

    def test_report_unauth(self, client):
        r = client.post(f"{API}/messages/1/report", json={"reason": "spam"})
        assert r.status_code == 401


class TestSetChatTheme:
    def test_set_theme(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        r = c.post(f"{API}/chats/{chat.id}/theme", json={"theme_color": "#ff0000", "wallpaper": "wp.jpg"})
        assert r.status_code == 200

    def test_set_theme_forbidden(self, app, user, user2):
        c = _login(app, user2)
        chat = _personal_chat(user, user2)
        u3 = User(username="u3w", email="u3w@x.com", email_verified=True)
        u3.set_password("p"); db.session.add(u3); db.session.commit()
        c3 = _login(app, u3)
        r = c3.post(f"{API}/chats/{chat.id}/theme", json={"theme_color": "#000"})
        assert r.status_code == 403

    def test_set_theme_unauth(self, client):
        r = client.post(f"{API}/chats/1/theme", json={"theme_color": "#000"})
        assert r.status_code == 401


class TestChatMembersCount:
    def test_members_count(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        r = c.get(f"{API}/chats/{chat.id}/members_count")
        assert r.status_code == 200
        assert r.get_json()["data"]["count"] >= 2

    def test_members_count_unauth(self, client):
        r = client.get(f"{API}/chats/1/members_count")
        assert r.status_code == 401


class TestPinChat:
    def test_pin_chat(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        r = c.post(f"{API}/chats/{chat.id}/pin")
        assert r.status_code == 200
        assert r.get_json()["data"]["pinned"] is True

    def test_unpin_chat(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        c.post(f"{API}/chats/{chat.id}/pin")
        r = c.post(f"{API}/chats/{chat.id}/unpin")
        assert r.status_code == 200
        assert r.get_json()["data"]["pinned"] is False

    def test_pinned_chats(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        c.post(f"{API}/chats/{chat.id}/pin")
        r = c.get(f"{API}/chats/pinned")
        assert r.status_code == 200
        assert r.get_json()["data"]["count"] >= 1

    def test_pin_chat_unauth(self, client):
        r = client.post(f"{API}/chats/1/pin")
        assert r.status_code == 401


class TestArchivedChats:
    def test_archive_unarchive(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        r = c.post(f"{API}/chats/{chat.id}/archive")
        assert r.status_code == 200
        r = c.post(f"{API}/chats/{chat.id}/unarchive")
        assert r.status_code == 200
        assert r.get_json()["data"]["archived"] is False

    def test_archived_list(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        c.post(f"{API}/chats/{chat.id}/archive")
        r = c.get(f"{API}/chats/archived")
        assert r.status_code == 200

    def test_archive_unauth(self, client):
        r = client.post(f"{API}/chats/1/archive")
        assert r.status_code == 401


class TestChatWallpaper:
    def test_set_wallpaper(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        r = c.post(f"{API}/chats/{chat.id}/wallpaper", json={"wallpaper": "wp.jpg"})
        assert r.status_code == 200

    def test_get_wallpaper(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        c.post(f"{API}/chats/{chat.id}/wallpaper", json={"wallpaper": "wp.jpg"})
        r = c.get(f"{API}/chats/{chat.id}/wallpaper")
        assert r.status_code == 200
        assert r.get_json()["data"]["wallpaper"] == "wp.jpg"

    def test_wallpaper_forbidden(self, app, user, user2):
        c = _login(app, user2)
        chat = _personal_chat(user, user2)
        u3 = User(username="u3v", email="u3v@x.com", email_verified=True)
        u3.set_password("p"); db.session.add(u3); db.session.commit()
        c3 = _login(app, u3)
        r = c3.post(f"{API}/chats/{chat.id}/wallpaper", json={"wallpaper": "x.jpg"})
        assert r.status_code == 403

    def test_wallpaper_unauth(self, client):
        r = c.get(f"{API}/chats/1/wallpaper") if False else client.get(f"{API}/chats/1/wallpaper")
        assert r.status_code == 401


class TestChatMembers:
    def test_chat_members(self, app, user, user2):
        c = _login(app, user)
        chat = _personal_chat(user, user2)
        r = c.get(f"{API}/chats/{chat.id}/members")
        assert r.status_code == 200
        assert r.get_json()["data"]["count"] >= 2

    def test_chat_members_unauth(self, client):
        r = client.get(f"{API}/chats/1/members")
        assert r.status_code == 401
