import json
import secrets
from datetime import datetime, timedelta
from app import db
from app.models import User, UserPremium, Message


def test_create_bot_requires_auth(client):
    resp = client.post("/premium/api/bot/create", json={})
    assert resp.status_code == 401
    data = resp.get_json()
    assert data["success"] == False
    assert "Not authenticated" in data["error"]


def test_create_bot_requires_premium(logged_in_client, user):
    resp = logged_in_client.post("/premium/api/bot/create", json={
        "name": "TestBot",
        "username": "testbot123"
    })
    assert resp.status_code == 403
    data = resp.get_json()
    assert data["success"] == False
    assert "Premium required" in data["error"]


def test_create_bot_success(logged_in_premium, premium_user):
    resp = logged_in_premium.post("/premium/api/bot/create", json={
        "name": "MyTestBot",
        "username": "mytestbot",
        "description": "A test bot"
    })
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert data["success"] == True
    bot = data["bot"]
    assert bot["name"] == "MyTestBot"
    assert bot["username"] == "mytestbot"
    assert len(bot["token"]) > 20
    assert "api_endpoint" in bot

    bot_user = User.query.filter_by(username="mytestbot").first()
    assert bot_user is not None
    assert bot_user.is_bot == True
    assert bot_user.bot_owner_id == premium_user.id
    assert bot_user.display_name == "MyTestBot"


def test_create_bot_validation(logged_in_premium):
    resp = logged_in_premium.post("/premium/api/bot/create", json={
        "name": "ab",
        "username": "valid123"
    })
    assert resp.status_code == 400
    assert "3 characters" in resp.get_json()["error"]

    resp = logged_in_premium.post("/premium/api/bot/create", json={
        "name": "ValidName",
        "username": "AB"  # uppercase not allowed by regex
    })
    assert resp.status_code == 400

    resp = logged_in_premium.post("/premium/api/bot/create", json={
        "name": "ValidName",
        "username": "ab"  # too short
    })
    assert resp.status_code == 400


def test_create_bot_duplicate_username(logged_in_premium, premium_user):
    logged_in_premium.post("/premium/api/bot/create", json={
        "name": "FirstBot",
        "username": "dupbot"
    })
    resp = logged_in_premium.post("/premium/api/bot/create", json={
        "name": "SecondBot",
        "username": "dupbot"
    })
    assert resp.status_code == 400
    assert "already taken" in resp.get_json()["error"]


def test_list_bots(logged_in_premium, premium_user):
    resp = logged_in_premium.get("/premium/api/bot/list")
    assert resp.status_code == 200
    assert resp.get_json()["bots"] == []

    logged_in_premium.post("/premium/api/bot/create", json={
        "name": "BotOne", "username": "botone"
    })
    logged_in_premium.post("/premium/api/bot/create", json={
        "name": "BotTwo", "username": "bottwo"
    })

    resp = logged_in_premium.get("/premium/api/bot/list")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["bots"]) == 2
    usernames = [b["username"] for b in data["bots"]]
    assert "botone" in usernames
    assert "bottwo" in usernames


def test_list_bots_other_user_not_visible(logged_in_premium, logged_in_user2, premium_user, user2):
    logged_in_premium.post("/premium/api/bot/create", json={
        "name": "PrivateBot", "username": "privatebot"
    })

    resp = logged_in_user2.get("/premium/api/bot/list")
    assert resp.get_json()["bots"] == []


def test_delete_bot(logged_in_premium, premium_user):
    create_resp = logged_in_premium.post("/premium/api/bot/create", json={
        "name": "DeleteMe", "username": "deleteme"
    })
    bot_id = create_resp.get_json()["bot"]["id"]

    resp = logged_in_premium.delete(f"/premium/api/bot/{bot_id}")
    assert resp.status_code == 200
    assert resp.get_json()["success"] == True

    assert User.query.get(bot_id) is None


def test_delete_bot_not_owner(app, logged_in_premium, premium_user, user2):
    from tests.conftest import login_as

    create_resp = logged_in_premium.post("/premium/api/bot/create", json={
        "name": "OthersBot", "username": "othersbot"
    })
    assert create_resp.status_code == 200
    create_data = create_resp.get_json()
    assert create_data["success"] == True
    bot_id = create_data["bot"]["id"]

    other_client = app.test_client()
    login_as(other_client, user2)
    resp = other_client.delete(f"/premium/api/bot/{bot_id}")
    assert resp.status_code == 404
    assert User.query.get(bot_id) is not None


def test_delete_bot_not_found(logged_in_premium):
    resp = logged_in_premium.delete("/premium/api/bot/99999")
    assert resp.status_code == 404


def test_regenerate_token(logged_in_premium, premium_user):
    create_resp = logged_in_premium.post("/premium/api/bot/create", json={
        "name": "TokenBot", "username": "tokenbot"
    })
    bot_id = create_resp.get_json()["bot"]["id"]
    old_token = User.query.get(bot_id).bot_token

    resp = logged_in_premium.post(f"/premium/api/bot/{bot_id}/regenerate-token")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] == True
    assert data["token"] != old_token
    assert data["token"] == User.query.get(bot_id).bot_token


def test_test_connection(logged_in_premium, premium_user):
    create_resp = logged_in_premium.post("/premium/api/bot/create", json={
        "name": "ConnBot", "username": "connbot"
    })
    token = create_resp.get_json()["bot"]["token"]

    resp = logged_in_premium.get(f"/premium/api/bot/{token}/test")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] == True
    assert data["bot_name"] == "ConnBot"
    assert data["bot_username"] == "connbot"


def test_test_connection_invalid_token(logged_in_premium):
    resp = logged_in_premium.get("/premium/api/bot/invalidtoken123/test")
    assert resp.status_code == 401


def test_bot_send_message(logged_in_premium, premium_user, user2, session):
    create_resp = logged_in_premium.post("/premium/api/bot/create", json={
        "name": "SendBot", "username": "sendbot"
    })
    data = create_resp.get_json()
    token = data["bot"]["token"]
    bot_id = data["bot"]["id"]

    resp = logged_in_premium.post(f"/premium/api/bot/{token}/send", json={
        "chat_id": user2.id,
        "content": "Hello from bot!"
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] == True
    assert data["message"]["content"] == "Hello from bot!"

    msgs = Message.query.filter_by(sender_id=bot_id, receiver_id=user2.id).all()
    msg = next((m for m in msgs if m.content == "Hello from bot!"), None)
    assert msg is not None
    assert msg.sender_id == bot_id
    assert msg.receiver_id == user2.id


def test_bot_send_message_missing_fields(logged_in_premium, premium_user):
    create_resp = logged_in_premium.post("/premium/api/bot/create", json={
        "name": "ValBot", "username": "valbot"
    })
    token = create_resp.get_json()["bot"]["token"]

    resp = logged_in_premium.post(f"/premium/api/bot/{token}/send", json={
        "chat_id": 1
    })
    assert resp.status_code == 400

    resp = logged_in_premium.post(f"/premium/api/bot/{token}/send", json={
        "content": "no chat id"
    })
    assert resp.status_code == 400


def test_bot_send_message_wrong_token(logged_in_premium):
    resp = logged_in_premium.post("/premium/api/bot/wrongtoken/send", json={
        "chat_id": 1, "content": "test"
    })
    assert resp.status_code == 401


def test_bot_send_message_lost_premium(logged_in_premium, premium_user, session):
    create_resp = logged_in_premium.post("/premium/api/bot/create", json={
        "name": "LostPremBot", "username": "lostprembot"
    })
    token = create_resp.get_json()["bot"]["token"]

    premium_user.premium.is_premium = False
    db.session.commit()

    resp = logged_in_premium.post(f"/premium/api/bot/{token}/send", json={
        "chat_id": 1, "content": "test"
    })
    assert resp.status_code == 403
    assert "no longer has premium" in resp.get_json()["error"]


def test_bot_get_updates(logged_in_premium, premium_user, user2, session):
    from app.models import Chat, ChatMember

    create_resp = logged_in_premium.post("/premium/api/bot/create", json={
        "name": "UpdateBot", "username": "updatebot"
    })
    data = create_resp.get_json()
    token = data["bot"]["token"]
    bot_id = data["bot"]["id"]

    chat = Chat(chat_type='personal')
    session.add(chat)
    session.flush()
    session.add(ChatMember(chat_id=chat.id, user_id=user2.id, role='participant'))
    session.add(ChatMember(chat_id=chat.id, user_id=bot_id, role='participant'))
    session.commit()

    msg = Message(
        content="Hello bot!",
        sender_id=user2.id,
        receiver_id=bot_id,
        chat_id=chat.id,
        timestamp=datetime.utcnow()
    )
    db.session.add(msg)
    db.session.commit()

    resp = logged_in_premium.get(f"/premium/api/bot/{token}/updates?after_id=0&timeout=5")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] == True
    assert len(data["updates"]) == 1
    assert data["updates"][0]["message"]["content"] == "Hello bot!"
    assert data["updates"][0]["message"]["is_bot"] == False


def test_bot_get_updates_empty(logged_in_premium, premium_user):
    create_resp = logged_in_premium.post("/premium/api/bot/create", json={
        "name": "EmptyBot", "username": "emptybot"
    })
    token = create_resp.get_json()["bot"]["token"]

    resp = logged_in_premium.get(f"/premium/api/bot/{token}/updates?after_id=999&timeout=2")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] == True
    assert data["updates"] == []


def test_bot_get_updates_invalid_token(logged_in_premium):
    resp = logged_in_premium.get("/premium/api/bot/badtoken/updates")
    assert resp.status_code == 401


def test_bot_get_updates_requires_auth(client):
    resp = client.get("/premium/api/bot/sometoken/updates")
    assert resp.status_code == 401


def test_full_bot_lifecycle(logged_in_premium, premium_user, user2, session):
    create_resp = logged_in_premium.post("/premium/api/bot/create", json={
        "name": "LifecycleBot",
        "username": "lifecyclebot",
        "description": "Full lifecycle test"
    })
    assert create_resp.status_code == 200
    bot_data = create_resp.get_json()["bot"]
    bot_id = bot_data["id"]
    token = bot_data["token"]

    list_resp = logged_in_premium.get("/premium/api/bot/list")
    assert len(list_resp.get_json()["bots"]) == 1

    test_resp = logged_in_premium.get(f"/premium/api/bot/{token}/test")
    assert test_resp.get_json()["bot_username"] == "lifecyclebot"

    send_resp = logged_in_premium.post(f"/premium/api/bot/{token}/send", json={
        "chat_id": user2.id,
        "content": "Lifecycle test message"
    })
    assert send_resp.status_code == 200
    msg_id = send_resp.get_json()["message"]["id"]

    msg = Message.query.get(msg_id)
    assert msg.content == "Lifecycle test message"

    regen_resp = logged_in_premium.post(f"/premium/api/bot/{bot_id}/regenerate-token")
    assert regen_resp.get_json()["token"] != token

    del_resp = logged_in_premium.delete(f"/premium/api/bot/{bot_id}")
    assert del_resp.status_code == 200

    assert User.query.get(bot_id) is None
