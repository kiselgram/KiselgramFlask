"""Tests for V2 API chat endpoints under /api.v2/api/.

Covers chat_list, messages (get), bot webapp, bots CRUD.
"""

from datetime import datetime
from app import db
from app.models import Message, User, Chat, ChatMember


API_PREFIX = "/api.v2/api"


class TestV2ChatList:
    """GET /api.v2/api/chat_list"""

    def test_chat_list_empty(self, logged_in_client, user):
        resp = logged_in_client.get(f"{API_PREFIX}/chat_list")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        # Should at least have the Saved Messages chat
        chat_types = [c["chat_type"] for c in data["data"]["chats"]]
        assert "personal" in chat_types

    def test_chat_list_with_messages(self, logged_in_client, user, user2):
        chat = Chat(chat_type="personal")
        db.session.add(chat)
        db.session.flush()
        msg = Message(content="Test from user2", sender_id=user2.id,
                      receiver_id=user.id, chat_id=chat.id, timestamp=datetime.utcnow())
        db.session.add(msg)
        db.session.commit()
        resp = logged_in_client.get(f"{API_PREFIX}/chat_list")
        assert resp.status_code == 200
        data = resp.get_json()
        chats = data["data"]["chats"]
        # Find the personal chat with user2
        peer_chats = [c for c in chats if c["chat_type"] == "personal"
                      and not c.get("is_saved")]
        assert len(peer_chats) >= 1
        assert peer_chats[0]["last_message"]["content"] == "Test from user2"

    def test_chat_list_unauthorized(self, client):
        resp = client.get(f"{API_PREFIX}/chat_list")
        assert resp.status_code == 401

    def test_chat_list_group_chat(self, logged_in_client, user, user2):
        g = Chat(chat_type="group", name="Test Group", owner_id=user.id)
        db.session.add(g)
        db.session.commit()
        db.session.add(ChatMember(user_id=user.id, chat_id=g.id, role="owner"))
        db.session.add(ChatMember(user_id=user2.id, chat_id=g.id, role="member"))
        db.session.add(Message(content="Group msg", sender_id=user.id,
                               chat_id=g.id, receiver_id=user.id,
                               timestamp=datetime.utcnow()))
        db.session.commit()
        resp = logged_in_client.get(f"{API_PREFIX}/chat_list")
        data = resp.get_json()
        group_chats = [c for c in data["data"]["chats"]
                       if c["chat_type"] == "group"]
        assert len(group_chats) >= 1
        assert group_chats[0]["group"]["name"] == "Test Group"


class TestV2GetMessages:
    """GET /api.v2/api/messages/<user_id>"""

    def test_get_personal_messages(self, logged_in_client, user, user2):
        chat = Chat(chat_type="personal")
        db.session.add(chat)
        db.session.flush()
        for i in range(3):
            db.session.add(Message(
                content=f"Msg {i}", sender_id=user.id,
                receiver_id=user2.id, chat_id=chat.id, timestamp=datetime.utcnow()))
        db.session.commit()
        resp = logged_in_client.get(f"{API_PREFIX}/messages/{user2.id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["data"]["messages"]) == 3
        assert data["data"]["peer"]["username"] == "friend"

    def test_get_messages_pagination(self, logged_in_client, user, user2):
        chat = Chat(chat_type="personal")
        db.session.add(chat)
        db.session.flush()
        for i in range(5):
            db.session.add(Message(
                content=f"M{i}", sender_id=user.id,
                receiver_id=user2.id, chat_id=chat.id, timestamp=datetime.utcnow()))
        db.session.commit()
        resp = logged_in_client.get(
            f"{API_PREFIX}/messages/{user2.id}?after=2&limit=2")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["data"]["messages"]) == 2
        assert data["data"]["pagination"]["has_more"] is True

    def test_get_messages_blocked(self, logged_in_client, user, user2):
        from app.models import BlockedUser
        db.session.add(BlockedUser(user_id=user2.id, blocked_user_id=user.id))
        db.session.commit()
        resp = logged_in_client.get(f"{API_PREFIX}/messages/{user2.id}")
        assert resp.status_code == 403

    def test_get_messages_saved(self, logged_in_client, user):
        db.session.add(Message(
            content="Saved note", sender_id=user.id,
            receiver_id=user.id, chat_id=1, timestamp=datetime.utcnow()))
        db.session.commit()
        resp = logged_in_client.get(f"{API_PREFIX}/messages/{user.id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["data"]["messages"]) == 1

    def test_get_messages_nonexistent_user(self, logged_in_client, user):
        resp = logged_in_client.get(f"{API_PREFIX}/messages/99999")
        assert resp.status_code == 404

    def test_get_messages_unauthorized(self, client, user2):
        resp = client.get(f"{API_PREFIX}/messages/{user2.id}")
        assert resp.status_code == 401


class TestV2BotWebapp:
    """GET/PUT /api.v2/api/bot/<bot_id>/webapp"""

    def _create_bot(self, owner_id, session):
        bot = User(
            username="testbot",
            display_name="Test Bot",
            email=None,
            is_bot=True,
            bot_owner_id=owner_id,
            bot_token="test_token_123",
            is_online=False,
        )
        bot.set_password("dummy")
        session.add(bot)
        session.commit()
        return bot

    def test_get_bot_webapp(self, logged_in_client, user, session):
        bot = self._create_bot(user.id, session)
        resp = logged_in_client.get(f"{API_PREFIX}/bot/{bot.id}/webapp")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["bot_id"] == bot.id

    def test_get_bot_webapp_not_found(self, logged_in_client, user):
        resp = logged_in_client.get(f"{API_PREFIX}/bot/99999/webapp")
        assert resp.status_code == 404

    def test_update_bot_webapp(self, logged_in_client, user, session):
        bot = self._create_bot(user.id, session)
        resp = logged_in_client.put(f"{API_PREFIX}/bot/{bot.id}/webapp", json={
            "webapp_url": "https://example.com/bot",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["webapp_url"] == "https://example.com/bot"

    def test_update_bot_webapp_not_owner(self, logged_in_client, user, user2, session):
        bot = self._create_bot(user2.id, session)
        resp = logged_in_client.put(f"{API_PREFIX}/bot/{bot.id}/webapp", json={
            "webapp_url": "https://evil.com",
        })
        assert resp.status_code == 403

    def test_update_bot_webapp_no_https(self, logged_in_client, user, session):
        bot = self._create_bot(user.id, session)
        resp = logged_in_client.put(f"{API_PREFIX}/bot/{bot.id}/webapp", json={
            "webapp_url": "http://insecure.com",
        })
        assert resp.status_code == 400


class TestV2Bots:
    """GET/POST /api.v2/api/bots"""

    def test_list_bots_empty(self, logged_in_client, user):
        resp = logged_in_client.get(f"{API_PREFIX}/bots")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["bots"] == []

    def test_create_bot(self, logged_in_client, user):
        resp = logged_in_client.post(f"{API_PREFIX}/bots", json={
            "username": "mynewbot",
            "display_name": "My New Bot",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["data"]["username"] == "mynewbot"
        assert "bot_token" in data["data"]
        bot = User.query.filter_by(username="mynewbot").first()
        assert bot is not None
        assert bot.is_bot is True
        assert bot.bot_owner_id == user.id

    def test_create_bot_duplicate_username(self, logged_in_client, user, session):
        bot = User(username="existingbot", display_name="Existing",
                   is_bot=True, bot_owner_id=user.id, email=None)
        bot.set_password("dummy")
        session.add(bot)
        session.commit()
        resp = logged_in_client.post(f"{API_PREFIX}/bots", json={
            "username": "existingbot",
        })
        assert resp.status_code == 400

    def test_list_bots_after_create(self, logged_in_client, user):
        logged_in_client.post(f"{API_PREFIX}/bots", json={
            "username": "botone",
        })
        logged_in_client.post(f"{API_PREFIX}/bots", json={
            "username": "bottwo",
        })
        resp = logged_in_client.get(f"{API_PREFIX}/bots")
        assert resp.status_code == 200
        assert len(resp.get_json()["data"]["bots"]) == 2

    def test_create_bot_unauthorized(self, client):
        resp = client.post(f"{API_PREFIX}/bots", json={
            "username": "unauthorized_bot",
        })
        assert resp.status_code == 401


class TestV2GetTyping:
    """GET /api.v2/api/typing/<chat_type>/<chat_id>"""

    def test_get_typing_no_one(self, logged_in_client, user, user2):
        resp = logged_in_client.get(
            f"{API_PREFIX}/typing/personal/{user.id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["typing_users"] == []

    def test_get_typing_after_set(self, app, user, user2):
        # user2 starts typing
        c2 = app.test_client()
        with c2.session_transaction() as sess:
            sess['user_id'] = user2.id
            sess['username'] = user2.username
        c2.post(f"{API_PREFIX}/typing/personal/{user.id}")
        # user checks
        c1 = app.test_client()
        with c1.session_transaction() as sess:
            sess['user_id'] = user.id
            sess['username'] = user.username
        resp = c1.get(f"{API_PREFIX}/typing/personal/{user.id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["data"]["typing_users"]) >= 1
        assert data["data"]["typing_users"][0]["username"] == "friend"
