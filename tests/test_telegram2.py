"""Full coverage wave: telegram gaps + collectible edges."""

from datetime import datetime, timedelta

import pytest

from app import db
from app.models import Chat, ChatMember, ChatSubscriber, Message, Poll, PollVote, User

API = "/api.v2/api/tg"
V2 = "/api.v2/api"


@pytest.fixture(autouse=True)
def _clean_auth_state():
    from app.utils import security
    from app.utils.helpers import _slow_buckets
    security._ACCOUNT_FAILURES.clear()
    _slow_buckets.clear()
    yield
    security._ACCOUNT_FAILURES.clear()
    _slow_buckets.clear()


def _login(app, user):
    c = app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = user.id
    return c


def _group(owner, members=(), name="TG2", public=True, invite=None):
    import secrets
    c = Chat(chat_type="group", name=name, owner_id=owner.id, is_public=public,
             invite_link=invite or f"tg2_{secrets.token_hex(4)}", created_at=datetime.utcnow())
    db.session.add(c)
    db.session.flush()
    db.session.add(ChatMember(user_id=owner.id, chat_id=c.id, role="owner"))
    for m in members:
        db.session.add(ChatMember(user_id=m.id, chat_id=c.id, role="member"))
    db.session.commit()
    return c


class TestTopicEdges:
    def test_rename_close_reopen(self, app, user, user2):
        g = _group(user, members=[user2])
        c1 = _login(app, user)
        tid = c1.post(f"{API}/groups/{g.id}/topics", json={"title": "Old"}).get_json()["data"]["topic_id"]
        assert c1.post(f"{API}/topics/{tid}", json={"title": "New"}).status_code == 200
        assert c1.post(f"{API}/topics/{tid}", json={"is_closed": True}).status_code == 200
        topics = c1.get(f"{API}/groups/{g.id}/topics").get_json()["data"]["topics"]
        assert topics[0]["title"] == "New" and topics[0]["is_closed"] is True
        assert c1.post(f"{API}/topics/{tid}", json={"is_closed": False}).status_code == 200

    def test_rename_empty_rejected(self, app, user):
        g = _group(user)
        c1 = _login(app, user)
        tid = c1.post(f"{API}/groups/{g.id}/topics", json={"title": "T"}).get_json()["data"]["topic_id"]
        assert c1.post(f"{API}/topics/{tid}", json={"title": "  "}).status_code == 400

    def test_delete_keeps_messages(self, app, user, user2):
        g = _group(user, members=[user2])
        c1 = _login(app, user)
        tid = c1.post(f"{API}/groups/{g.id}/topics", json={"title": "Gone"}).get_json()["data"]["topic_id"]
        mid = c1.post(f"{API}/topics/{tid}/send", json={"content": "stay"}).get_json()["data"]["message_id"]
        assert c1.delete(f"{API}/topics/{tid}").status_code == 200
        assert db.session.get(Message, mid).topic_id is None

    def test_outsider_forbidden(self, app, user, user2, user3):
        g = _group(user, members=[user2])
        c3 = _login(app, user3)
        assert c3.post(f"{API}/groups/{g.id}/topics", json={"title": "X"}).status_code == 403
        assert c3.get(f"{API}/groups/{g.id}/topics").status_code == 403

    def test_send_validation(self, app, user):
        g = _group(user)
        c1 = _login(app, user)
        tid = c1.post(f"{API}/groups/{g.id}/topics", json={"title": "V"}).get_json()["data"]["topic_id"]
        assert c1.post(f"{API}/topics/{tid}/send", json={"content": "  "}).status_code == 400
        assert c1.post(f"{API}/topics/999999/send", json={"content": "x"}).status_code == 404

    def test_messages_limit(self, app, user):
        g = _group(user)
        c1 = _login(app, user)
        tid = c1.post(f"{API}/groups/{g.id}/topics", json={"title": "L"}).get_json()["data"]["topic_id"]
        for i in range(3):
            c1.post(f"{API}/topics/{tid}/send", json={"content": f"m{i}"})
        d = c1.get(f"{API}/topics/{tid}/messages", query_string={"limit": 2}).get_json()["data"]
        assert len(d["messages"]) == 2


class TestSlowQuizEdges:
    def test_slow_get_and_validation(self, app, user, user2, user3):
        g = _group(user, members=[user2])
        c1, c2, c3 = _login(app, user), _login(app, user2), _login(app, user3)
        assert c1.get(f"{API}/groups/{g.id}/slowmode").get_json()["data"]["slow_mode"] == 0
        assert c1.post(f"{API}/groups/{g.id}/slowmode", json={"seconds": -1}).status_code == 400
        assert c1.post(f"{API}/groups/{g.id}/slowmode", json={"seconds": 999}).status_code == 400
        assert c2.get(f"{API}/groups/{g.id}/slowmode").status_code == 200
        assert c3.get(f"{API}/groups/{g.id}/slowmode").status_code == 403

    def test_quiz_correctness(self, app, user, user2):
        p = Poll(question="Q", options=["a", "b"], creator_id=user.id)
        db.session.add(p)
        db.session.commit()
        c1, c2 = _login(app, user), _login(app, user2)
        c1.post(f"{API}/polls/{p.id}/quiz", json={"answer": 0})
        db.session.add(PollVote(poll_id=p.id, user_id=user2.id, option_index=0))
        db.session.commit()
        d = c2.get(f"{API}/polls/{p.id}/answer").get_json()["data"]
        assert d["my_correct"] is True and d["counts"] == [1, 0]
        assert c2.post(f"{API}/polls/{p.id}/quiz", json={"answer": 1}).status_code == 403
        assert c1.post(f"{API}/polls/{p.id}/quiz", json={"answer": 9}).status_code == 400
        assert c1.get(f"{API}/polls/999999/answer").status_code == 404

    def test_plain_poll_answer(self, app, user):
        p = Poll(question="Q", options=["x"], creator_id=user.id)
        db.session.add(p)
        db.session.commit()
        d = _login(app, user).get(f"{API}/polls/{p.id}/answer").get_json()["data"]
        assert "quiz_answer" not in d and d["total"] == 0


class TestGeoVoiceEdges:
    def test_geo_validation(self, app, user, user2, personal_chat):
        c1 = _login(app, user)
        assert c1.post(f"{API}/geo/share", json={"chat_id": personal_chat.id, "lat": 91, "lon": 0}).status_code == 400
        assert c1.post(f"{API}/geo/share", json={"chat_id": personal_chat.id, "lat": 1, "lon": 1, "live_minutes": 999}).status_code == 400
        assert c1.post(f"{API}/geo/share", json={"chat_id": personal_chat.id}).status_code == 400

    def test_geo_expired_and_missing(self, app, user, personal_chat):
        from app.models import TgLiveLocation
        c1 = _login(app, user)
        m = Message(content="0,0", sender_id=user.id, chat_id=personal_chat.id, file_type="geo", timestamp=datetime.utcnow())
        db.session.add(m)
        db.session.flush()
        db.session.add(TgLiveLocation(message_id=m.id, user_id=user.id, chat_id=personal_chat.id,
                                      lat=0, lon=0, until=datetime.utcnow() - timedelta(minutes=1)))
        db.session.commit()
        assert c1.post(f"{API}/geo/{m.id}/update", json={"lat": 1, "lon": 1}).status_code == 404
        assert c1.post(f"{API}/geo/999999/stop").status_code == 404

    def test_geo_group_share(self, app, user, user2):
        g = _group(user, members=[user2])
        c1 = _login(app, user)
        r = c1.post(f"{API}/geo/share", json={"chat_id": g.id, "lat": 10, "lon": 20}).get_json()["data"]
        assert r["live"] is False

    def test_voice_edges(self, app, user, user2, user3):
        g = _group(user, members=[user2])
        c1, c2, c3 = _login(app, user), _login(app, user2), _login(app, user3)
        room = c1.post(f"{API}/voice/start", json={"chat_id": g.id}).get_json()["data"]["room_id"]
        again = c1.post(f"{API}/voice/start", json={"chat_id": g.id}).get_json()["data"]
        assert again.get("resumed") is True and again["room_id"] == room
        assert c2.post(f"{API}/voice/{room}/end").status_code == 403
        assert c3.post(f"{API}/voice/start", json={"chat_id": g.id}).status_code == 403
        assert c1.post(f"{API}/voice/nope/end").status_code == 404
        assert len(c1.get(f"{API}/voice/active").get_json()["data"]["rooms"]) == 1


class TestDiscussProtectEdges:
    def test_link_forbidden(self, app, user, user2):
        g = _group(user, members=[user2])
        ch = Chat(chat_type="channel", name="LC", owner_id=user.id, is_public=True,
                  invite_link="tg2_lc", created_at=datetime.utcnow())
        db.session.add(ch)
        db.session.commit()
        c2 = _login(app, user2)
        assert c2.post(f"{API}/channels/{ch.id}/link", json={"group_id": g.id}).status_code == 403

    def test_unlink(self, app, user):
        g = _group(user, name="UG")
        ch = Chat(chat_type="channel", name="UC", owner_id=user.id, is_public=True,
                  invite_link="tg2_uc", created_at=datetime.utcnow())
        db.session.add(ch)
        db.session.commit()
        c1 = _login(app, user)
        c1.post(f"{API}/channels/{ch.id}/link", json={"group_id": g.id})
        assert c1.delete(f"{API}/channels/{ch.id}/link").status_code == 200
        assert db.session.get(Chat, ch.id).linked_chat_id is None

    def test_comment_edges(self, app, user, user2):
        ch = Chat(chat_type="channel", name="CE", owner_id=user.id, is_public=True,
                  invite_link="tg2_ce", created_at=datetime.utcnow())
        db.session.add(ch)
        db.session.flush()
        post = Message(content="p", sender_id=user.id, chat_id=ch.id, receiver_id=user.id, timestamp=datetime.utcnow())
        db.session.add(post)
        db.session.commit()
        c2 = _login(app, user2)
        assert c2.post(f"{API}/comments", json={"channel_message_id": post.id, "content": "hi"}).status_code == 400
        d = c2.get(f"{API}/comments/{post.id}").get_json()["data"]
        assert d["count"] == 0

    def test_protect_edges(self, app, user, user2):
        g = _group(user, members=[user2])
        c2 = _login(app, user2)
        assert c2.post(f"{API}/chats/{g.id}/protect", json={"no_forwards": True}).status_code == 403
        c1 = _login(app, user)
        assert c1.post(f"{API}/chats/{g.id}/protect", json={"no_forwards": False}).status_code == 200
        assert c1.post(f"{API}/chats/999999/protect", json={}).status_code == 404

    def test_forward_still_works_unprotected(self, app, user, personal_chat):
        c1 = _login(app, user)
        m = Message(content="fwd ok", sender_id=user.id, chat_id=personal_chat.id, timestamp=datetime.utcnow())
        db.session.add(m)
        db.session.commit()
        r = c1.post(f"{V2}/messages/forward", json={"message_id": m.id, "target_chat_id": personal_chat.id})
        assert r.status_code == 200


class TestSavedMembersBotsEdges:
    def test_saved_unlist_and_empty(self, logged_in_client):
        d = logged_in_client.get(f"{API}/saved").get_json()["data"]
        assert d["saved"] == []
        assert logged_in_client.get(f"{API}/saved/tags").get_json()["data"]["tags"] == []

    def test_members_edges(self, app, user, user2, user3):
        g = _group(user, members=[user2])
        c3 = _login(app, user3)
        assert c3.get(f"{API}/groups/{g.id}/members").status_code == 403
        assert _login(app, user).get(f"{API}/groups/999999/members").status_code == 404

    def test_bot_edges(self, app, user, user2):
        c1, c2 = _login(app, user), _login(app, user2)
        assert c1.post(f"{API}/bots/commands", json={"command": "hi"}).status_code == 403
        user.is_bot = True
        db.session.commit()
        assert c1.post(f"{API}/bots/commands", json={"command": "BAD CMD!"}).status_code == 400
        cid = c1.post(f"{API}/bots/commands", json={"command": "go"}).get_json()
        assert c1.delete(f"{API}/bots/commands/999999").status_code == 404
        row = c1.get(f"{API}/bots/{user.id}/commands").get_json()["data"]["commands"]
        assert any(c["command"] == "go" for c in row)
        from app.models import TgBotCommand
        real_id = TgBotCommand.query.filter_by(bot_id=user.id, command="go").first().id
        assert c2.delete(f"{API}/bots/commands/{real_id}").status_code == 403
        assert c1.delete(f"{API}/bots/commands/{real_id}").status_code == 200

    def test_story_archive_empty(self, logged_in_client):
        assert logged_in_client.get(f"{API}/stories/archive").get_json()["data"]["stories"] == []

    def test_story_archive_with_old(self, app, user, admin_user):
        from app.models import Story
        s = Story(user_id=user.id, media_path="stories/old.jpg", media_type="image",
                  created_at=datetime.utcnow() - timedelta(hours=25))
        db.session.add(s)
        db.session.commit()
        import app.routes.spav2.telegram as tg
        tg._prune_at = 0
        assert _login(app, admin_user).post(f"{API}/maintenance/prune").status_code == 200
        rows = _login(app, user).get(f"{API}/stories/archive").get_json()["data"]["stories"]
        assert any(r["story_id"] == s.id for r in rows)

    def test_deep_link_private(self, app, user, user2):
        g = _group(user, members=[user2], public=False, name="PrivDL")
        m = Message(content="priv", sender_id=user.id, chat_id=g.id, receiver_id=user.id, timestamp=datetime.utcnow())
        db.session.add(m)
        db.session.commit()
        c = _login(app, user)
        assert c.get(f"/m/{g.id}/{m.id}").status_code == 404
        assert c.get(f"/m/{g.id}/999999").status_code == 404


class TestCollectibleEdges:
    def test_bad_names(self, logged_in_client, user):
        assert logged_in_client.post(f"{API}/collectibles/claim", json={"username": "ab"}).status_code == 400
        assert logged_in_client.post(f"{API}/collectibles/claim", json={"username": "bad-name!"}).status_code == 400
        assert logged_in_client.post(f"{API}/collectibles/claim", json={"username": user.username}).status_code == 400

    def test_dup_claim(self, logged_in_client):
        assert logged_in_client.post(f"{API}/collectibles/claim", json={"username": "dup_name"}).status_code == 201
        assert logged_in_client.post(f"{API}/collectibles/claim", json={"username": "dup_name"}).status_code in (400, 409)

    def test_transfer_edges(self, app, user, user2):
        c1 = _login(app, user)
        c1.post(f"{API}/collectibles/claim", json={"username": "move_me"})
        assert c1.post(f"{API}/collectibles/transfer", json={"username": "move_me", "to": user.id}).status_code == 404
        assert c1.post(f"{API}/collectibles/transfer", json={"username": "ghost_name", "to": user2.id}).status_code == 404

    def test_buy_sell_edges(self, app, user, user2):
        c1, c2 = _login(app, user), _login(app, user2)
        c1.post(f"{API}/collectibles/claim", json={"username": "edge_sale"})
        assert c1.post(f"{API}/collectibles/sell", json={"username": "edge_sale", "price": -5}).status_code == 400
        assert c2.post(f"{API}/collectibles/buy", json={"username": "edge_sale"}).status_code == 404
        assert c1.post(f"{API}/collectibles/sell", json={"username": "edge_sale"}).status_code == 200

    def test_wear_not_owned(self, logged_in_client):
        assert logged_in_client.post(f"{API}/collectibles/wear", json={"username": "nope_nothing"}).status_code == 404

    def test_dice_peer_and_round_bad(self, app, user, user2):
        c1 = _login(app, user)
        r = c1.post(f"{API}/dice", json={"chat_type": "personal", "peer_id": user2.id}).get_json()["data"]
        assert 1 <= r["value"] <= 6
        m = db.session.get(Message, r["message_id"])
        assert m.file_type == "dice" and m.receiver_id == user2.id
