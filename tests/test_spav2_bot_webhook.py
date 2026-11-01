"""Tests for V2 API bot webhook endpoints under /api.v2/api/bots/*."""

from datetime import datetime
from app import db
from app.models import User, Message


API_PREFIX = "/api"


class TestV2BotIncomingWebhook:
    """POST /api.v2/api/bots/webhook/<token>"""

    def _create_bot(self, owner_id, session):
        bot = User(
            username="webhookbot",
            display_name="Webhook Bot",
            email=None,
            is_bot=True,
            bot_owner_id=owner_id,
            bot_token="test_bot_token_123",
            is_online=False,
        )
        bot.set_password("dummy")
        session.add(bot)
        session.commit()
        return bot

    def test_incoming_message_with_receiver(self, logged_in_client, user, session):
        bot = self._create_bot(user.id, session)
        resp = logged_in_client.post(
            f"{API_PREFIX}/bots/webhook/{bot.bot_token}", json={
                "event": "message",
                "data": {
                    "receiver_id": user.id,
                    "content": "Hello from bot!",
                },
            })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["success"] is True
        assert "message_id" in data["data"]
        msg = Message.query.get(data["data"]["message_id"])
        assert msg is not None
        assert msg.content == "Hello from bot!"
        assert msg.sender_id == bot.id

    def test_incoming_message_invalid_token(self, logged_in_client, user):
        resp = logged_in_client.post(
            f"{API_PREFIX}/bots/webhook/invalid_token", json={
                "event": "message",
                "data": {"receiver_id": user.id, "content": "Hi"},
            })
        assert resp.status_code == 403

    def test_incoming_message_no_content(self, logged_in_client, user, session):
        bot = self._create_bot(user.id, session)
        resp = logged_in_client.post(
            f"{API_PREFIX}/bots/webhook/{bot.bot_token}", json={
                "event": "message",
                "data": {"receiver_id": user.id},
            })
        assert resp.status_code == 400

    def test_incoming_typing_event(self, logged_in_client, user, session):
        bot = self._create_bot(user.id, session)
        resp = logged_in_client.post(
            f"{API_PREFIX}/bots/webhook/{bot.bot_token}", json={
                "event": "typing",
                "data": {"receiver_id": user.id},
            })
        assert resp.status_code == 200

    def test_incoming_callback_query(self, logged_in_client, user, session):
        bot = self._create_bot(user.id, session)
        resp = logged_in_client.post(
            f"{API_PREFIX}/bots/webhook/{bot.bot_token}", json={
                "event": "callback_query",
                "data": {},
            })
        assert resp.status_code == 200

    def test_incoming_unknown_event(self, logged_in_client, user, session):
        bot = self._create_bot(user.id, session)
        resp = logged_in_client.post(
            f"{API_PREFIX}/bots/webhook/{bot.bot_token}", json={
                "event": "unknown_event",
                "data": {},
            })
        assert resp.status_code == 400


class TestV2SetWebhookUrl:
    """PUT /api.v2/api/bots/webhook"""

    def _create_bot(self, owner_id, session):
        bot = User(
            username="setwebhookbot",
            display_name="Set WH Bot",
            email=None,
            is_bot=True,
            bot_owner_id=owner_id,
            bot_token="set_wh_token",
            is_online=False,
        )
        bot.set_password("dummy")
        session.add(bot)
        session.commit()
        return bot

    def test_set_webhook_url(self, logged_in_client, user, session):
        bot = self._create_bot(user.id, session)
        resp = logged_in_client.put(f"{API_PREFIX}/bots/webhook", json={
            "bot_id": bot.id,
            "webhook_url": "https://example.com/bot-webhook",
        })
        assert resp.status_code == 200
        assert db.session.get(User, bot.id).bot_webhook_url == "https://example.com/bot-webhook"

    def test_set_webhook_not_owner(self, logged_in_client, user, user2, session):
        bot = self._create_bot(user2.id, session)
        resp = logged_in_client.put(f"{API_PREFIX}/bots/webhook", json={
            "bot_id": bot.id,
            "webhook_url": "https://evil.com/webhook",
        })
        assert resp.status_code == 403

    def test_set_webhook_no_https(self, logged_in_client, user, session):
        bot = self._create_bot(user.id, session)
        resp = logged_in_client.put(f"{API_PREFIX}/bots/webhook", json={
            "bot_id": bot.id,
            "webhook_url": "http://insecure.com/webhook",
        })
        assert resp.status_code == 400

    def test_set_webhook_missing_bot_id(self, logged_in_client, user):
        resp = logged_in_client.put(f"{API_PREFIX}/bots/webhook", json={
            "webhook_url": "https://example.com/wh",
        })
        assert resp.status_code == 400

    def test_set_webhook_unauthorized(self, client):
        resp = client.put(f"{API_PREFIX}/bots/webhook", json={
            "bot_id": 1,
            "webhook_url": "https://example.com/wh",
        })
        assert resp.status_code == 401
