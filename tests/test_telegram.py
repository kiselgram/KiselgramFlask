"""Telegram parity pack tests."""

from datetime import datetime

from app import db
from app.models import Chat, ChatMember, ChatSubscriber, Message, Poll, User

API = "/api.v2/api/tg"


def _login(app, user):
    c = app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = user.id
    return c


def _group(owner, members=(), name="TG", public=True, invite=None):
    import secrets
    c = Chat(chat_type="group", name=name, owner_id=owner.id, is_public=public,
             invite_link=invite or f"tg_{secrets.token_hex(4)}", created_at=datetime.utcnow())
    db.session.add(c)
    db.session.flush()
    db.session.add(ChatMember(user_id=owner.id, chat_id=c.id, role="owner"))
    for m in members:
        db.session.add(ChatMember(user_id=m.id, chat_id=c.id, role="member"))
    db.session.commit()
    return c


class TestTopicsSlow:
    def test_topic_flow(self, app, user, user2):
        g = _group(user, members=[user2])
        c1, c2 = _login(app, user), _login(app, user2)
        tid = c1.post(f"{API}/groups/{g.id}/topics", json={"title": "News"}).get_json()["data"]["topic_id"]
        assert len(c1.get(f"{API}/groups/{g.id}/topics").get_json()["data"]["topics"]) == 1
        r = c2.post(f"{API}/topics/{tid}/send", json={"content": "hello"})
        assert r.status_code == 201
        msgs = c1.get(f"{API}/topics/{tid}/messages").get_json()["data"]["messages"]
        assert len(msgs) == 1 and msgs[0]["content"] == "hello"
        assert c1.post(f"{API}/topics/{tid}", json={"is_closed": True}).status_code == 200
        assert c2.post(f"{API}/topics/{tid}/send", json={"content": "x"}).status_code == 403

    def test_slowmode(self, app, user, user2):
        g = _group(user, members=[user2])
        c1, c2 = _login(app, user), _login(app, user2)
        assert c1.post(f"{API}/groups/{g.id}/slowmode", json={"seconds": 60}).status_code == 200
        assert c2.post(f"{API}/groups/{g.id}/slowmode", json={"seconds": 0}).status_code == 403
        r1 = c2.post("/api.v2/api/send_group_message", json={"group_id": g.id, "content": "one"})
        assert r1.status_code == 201
        r2 = c2.post("/api.v2/api/send_group_message", json={"group_id": g.id, "content": "two"})
        assert r2.status_code == 429
        assert c1.post(f"{API}/groups/{g.id}/slowmode", json={"seconds": 0}).status_code == 200


class TestQuizDiceGeo:
    def test_quiz(self, app, user, user2):
        p = Poll(question="2+2?", options=["3", "4"], creator_id=user.id)
        db.session.add(p)
        db.session.commit()
        c1 = _login(app, user)
        assert c1.post(f"{API}/polls/{p.id}/quiz", json={"answer": 1, "explanation": "basic"}).status_code == 200
        d = c1.get(f"{API}/polls/{p.id}/answer").get_json()["data"]
        assert d["quiz_answer"] == 1 and d["my_correct"] is None

    def test_dice(self, app, user, user2, personal_chat):
        c1 = _login(app, user)
        r = c1.post(f"{API}/dice", json={"chat_id": personal_chat.id}).get_json()["data"]
        assert 1 <= r["value"] <= 6

    def test_geo(self, app, user, user2, personal_chat):
        c1 = _login(app, user)
        mid = c1.post(f"{API}/geo/share", json={
            "chat_id": personal_chat.id, "lat": 55.7, "lon": 37.6, "live_minutes": 60}).get_json()["data"]["message_id"]
        assert c1.post(f"{API}/geo/{mid}/update", json={"lat": 55.8, "lon": 37.7}).status_code == 200
        assert len(c1.get(f"{API}/geo/live").get_json()["data"]["live"]) == 1
        assert c1.post(f"{API}/geo/{mid}/stop").status_code == 200
        assert c1.get(f"{API}/geo/live").get_json()["data"]["live"] == []


class TestVoiceDiscuss:
    def test_voice(self, app, user, user2):
        g = _group(user, members=[user2])
        c1 = _login(app, user)
        room = c1.post(f"{API}/voice/start", json={"chat_id": g.id}).get_json()["data"]["room_id"]
        assert len(c1.get(f"{API}/voice/active", query_string={"chat_id": g.id}).get_json()["data"]["rooms"]) == 1
        assert c1.post(f"{API}/voice/{room}/end").status_code == 200
        assert c1.get(f"{API}/voice/active", query_string={"chat_id": g.id}).get_json()["data"]["rooms"] == []

    def test_discussion_comments(self, app, user, user2):
        g = _group(user, members=[user2], name="DiscG")
        ch = Chat(chat_type="channel", name="DiscC", owner_id=user.id, is_public=True,
                  invite_link="tg_discc", created_at=datetime.utcnow())
        db.session.add(ch)
        db.session.commit()
        db.session.add(ChatSubscriber(user_id=user2.id, chat_id=ch.id))
        db.session.commit()
        c1, c2 = _login(app, user), _login(app, user2)
        assert c1.post(f"{API}/channels/{ch.id}/link", json={"group_id": g.id}).status_code == 200
        post = Message(content="news", sender_id=user.id, chat_id=ch.id, receiver_id=user.id, timestamp=datetime.utcnow())
        db.session.add(post)
        db.session.commit()
        mid = c2.post(f"{API}/comments", json={"channel_message_id": post.id, "content": "nice"}).get_json()["data"]["message_id"]
        d = c1.get(f"{API}/comments/{post.id}").get_json()["data"]
        assert d["count"] == 1 and d["comments"][0]["message_id"] == mid


class TestProtectSavedMembers:
    def test_no_forwards(self, app, user, user2):
        g = _group(user, members=[user2])
        c1 = _login(app, user)
        assert c1.post(f"{API}/chats/{g.id}/protect", json={"no_forwards": True}).status_code == 200
        m = Message(content="secret", sender_id=user.id, chat_id=g.id, receiver_id=user.id, timestamp=datetime.utcnow())
        db.session.add(m)
        db.session.commit()
        r = c1.post("/api.v2/api/messages/forward", json={"message_id": m.id, "target_chat_id": g.id})
        assert r.status_code == 403

    def test_saved_tags(self, logged_in_client, user, personal_chat):
        m = Message(content="keep", sender_id=user.id, chat_id=personal_chat.id, timestamp=datetime.utcnow())
        db.session.add(m)
        db.session.commit()
        assert logged_in_client.post(f"{API}/saved/tag", json={"message_id": m.id, "tag": "work"}).status_code == 200
        d = logged_in_client.get(f"{API}/saved", query_string={"tag": "work"}).get_json()["data"]
        assert len(d["saved"]) == 1
        tags = logged_in_client.get(f"{API}/saved/tags").get_json()["data"]["tags"]
        assert any(t["tag"] == "work" for t in tags)

    def test_hidden_members(self, app, user, user2):
        g = _group(user, members=[user2])
        c1, c2 = _login(app, user), _login(app, user2)
        assert c1.post(f"{API}/groups/{g.id}/visibility", json={"hide_members": True}).status_code == 200
        d = c2.get(f"{API}/groups/{g.id}/members").get_json()["data"]
        assert d["hidden"] is True and d["members"] == [] and d["count"] == 2
        d = c1.get(f"{API}/groups/{g.id}/members").get_json()["data"]
        assert d["hidden"] is False and len(d["members"]) == 2


class TestBotsDeepPrune:
    def test_bot_commands(self, app, user):
        user.is_bot = True
        db.session.commit()
        c1 = _login(app, user)
        assert c1.post(f"{API}/bots/commands", json={"command": "start", "description": "Start"}).status_code == 200
        cmds = c1.get(f"{API}/bots/{user.id}/commands").get_json()["data"]["commands"]
        assert any(c["command"] == "start" for c in cmds)

    def test_deep_link_and_prune(self, app, user, admin_user):
        g = _group(user, name="PubLink")
        m = Message(content="hello link", sender_id=user.id, chat_id=g.id, receiver_id=user.id, timestamp=datetime.utcnow())
        db.session.add(m)
        db.session.commit()
        c = _login(app, user)
        r = c.get(f"/m/{g.id}/{m.id}")
        assert r.status_code == 200 and "hello link" in r.get_data(as_text=True)
        ca = _login(app, admin_user)
        assert ca.post(f"{API}/maintenance/prune").status_code == 200


class TestCollectiblesRound:
    def test_claim_transfer_wear(self, app, user, user2):
        c1, c2 = _login(app, user), _login(app, user2)
        assert c1.post(f"{API}/collectibles/claim", json={"username": "star_name"}).status_code == 201
        assert c1.post(f"{API}/collectibles/claim", json={"username": user2.username}).status_code == 400
        assert c1.post(f"{API}/collectibles/transfer", json={"username": "star_name", "to": user2.username}).status_code == 200
        mine = c2.get(f"{API}/collectibles/mine").get_json()["data"]
        assert any(c["username"] == "star_name" for c in mine["collectibles"])
        assert c2.post(f"{API}/collectibles/wear", json={"username": "star_name"}).status_code == 200
        assert db.session.get(User, user2.id).username == "star_name"
        back = c2.get(f"{API}/collectibles/mine").get_json()["data"]
        assert any(c["username"] == "friend" for c in back["collectibles"])

    def test_sell_buy(self, app, user, user2):
        c1, c2 = _login(app, user), _login(app, user2)
        c1.post(f"{API}/collectibles/claim", json={"username": "rare_one"})
        assert c1.post(f"{API}/collectibles/sell", json={"username": "rare_one", "price": 500}).status_code == 200
        shop = c2.get(f"{API}/collectibles/showcase").get_json()["data"]["for_sale"]
        assert any(s["username"] == "rare_one" for s in shop)
        assert c2.post(f"{API}/collectibles/buy", json={"username": "rare_one"}).status_code == 200
        mine = c2.get(f"{API}/collectibles/mine").get_json()["data"]["collectibles"]
        assert any(c["username"] == "rare_one" and c["last_sale_price"] == 500 for c in mine)

    def test_round_upload_validation(self, app, user):
        import io
        c1 = _login(app, user)
        bad = {"file": (io.BytesIO(b"x"), "a.png")}
        assert c1.post(f"{API}/round/upload", data=bad, content_type="multipart/form-data").status_code == 400
        good = {"file": (io.BytesIO(b"\x00" * 100), "r.webm")}
        r = c1.post(f"{API}/round/upload", data=good, content_type="multipart/form-data")
        assert r.status_code == 200
        fp = r.get_json()["data"]["file_path"]
        assert fp.startswith("circles/")
        import os
        from app.routes.files import get_uploads_dir
        os.remove(os.path.join(get_uploads_dir(), fp))
