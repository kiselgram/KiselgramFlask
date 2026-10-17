"""Sputnik ideas pack wave-2 tests: polls close/results, drafts, banner,
profile media, discover, join requests, member perms, restrict, story
share/replace, data export."""

from datetime import datetime

from app import db
from app.models import Chat, ChatMember, Message, Poll, PollVote, Story, User

API = "/api.v2/api/sputnik"


def _group(owner, members=(), name="SG", public=False, invite="sg_invite"):
    c = Chat(chat_type="group", name=name, owner_id=owner.id, is_public=public,
             invite_link=invite, created_at=datetime.utcnow())
    db.session.add(c)
    db.session.flush()
    db.session.add(ChatMember(user_id=owner.id, chat_id=c.id, role="owner"))
    for m in members:
        db.session.add(ChatMember(user_id=m.id, chat_id=c.id, role="member"))
    db.session.commit()
    return c


def _login(app, user):
    c = app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = user.id
    return c


class TestPollCloseResults:
    def test_close_and_results(self, app, user, user2):
        p = Poll(question="Q?", options=["a", "b"], creator_id=user.id)
        db.session.add(p)
        db.session.commit()
        db.session.add(PollVote(poll_id=p.id, user_id=user2.id, option_index=1))
        db.session.commit()
        c2 = _login(app, user2)
        assert c2.post(f"{API}/polls/{p.id}/close").status_code == 403
        c1 = _login(app, user)
        assert c1.post(f"{API}/polls/{p.id}/close").status_code == 200
        r = c1.get(f"{API}/polls/{p.id}/results").get_json()["data"]
        assert r["closed"] is True
        assert r["counts"] == [0, 1]
        assert r["total"] == 1


class TestDraftsBanner:
    def test_draft_save_list_clear(self, logged_in_client, personal_chat):
        assert logged_in_client.post(f"{API}/drafts/save", json={
            "chat_type": "personal", "chat_id": personal_chat.id, "text": "half"}).status_code == 200
        drafts = logged_in_client.get(f"{API}/drafts").get_json()["data"]["drafts"]
        assert any(d["text"] == "half" for d in drafts)
        assert logged_in_client.post(f"{API}/drafts/save", json={
            "chat_type": "personal", "chat_id": personal_chat.id, "text": ""}).status_code == 200
        drafts = logged_in_client.get(f"{API}/drafts").get_json()["data"]["drafts"]
        assert all(d["text"] != "half" for d in drafts)

    def test_banner_roundtrip(self, logged_in_client, user2):
        assert logged_in_client.post(f"{API}/profile/banner", json={
            "banner_color": "#ff0000"}).status_code == 200
        d = logged_in_client.get(f"{API}/profile/banner").get_json()["data"]
        assert d["banner_color"] == "#ff0000"
        d = logged_in_client.get(f"{API}/profile/banner",
                                 query_string={"user_id": user2.id}).get_json()["data"]
        assert d["banner_color"] == "#2b8d8d"


class TestProfileMediaDiscover:
    def test_media_counts_and_filter(self, logged_in_client, user, user2, personal_chat):
        m = Message(content="pic", sender_id=user.id, receiver_id=user2.id,
                    chat_id=personal_chat.id, timestamp=datetime.utcnow(),
                    file_type="photo", file_path="photos/a.jpg")
        db.session.add(m)
        db.session.commit()
        d = logged_in_client.get(f"{API}/users/{user.id}/media").get_json()["data"]
        assert d["counts"]["photo"] >= 1
        d = logged_in_client.get(f"{API}/users/{user.id}/media",
                                 query_string={"filter": "video"}).get_json()["data"]
        assert d["items"] == []

    def test_discover_lists_public(self, logged_in_client, user):
        _group(user, name="Public One", public=True, invite="sg_pub_1")
        chats = logged_in_client.get(f"{API}/discover").get_json()["data"]["chats"]
        assert any(c["name"] == "Public One" and c["joined"] for c in chats)


class TestJoinRequests:
    def test_request_approve_flow(self, app, user, user2, user3):
        g = _group(user, name="Private", public=False, invite="sg_priv_1")
        c2 = _login(app, user2)
        assert c2.post(f"{API}/groups/{g.id}/request").status_code == 200
        c1 = _login(app, user)
        reqs = c1.get(f"{API}/groups/{g.id}/requests").get_json()["data"]["requests"]
        assert any(r["user_id"] == user2.id for r in reqs)
        assert c1.post(f"{API}/groups/{g.id}/approve", json={"user_id": user2.id}).status_code == 200
        assert ChatMember.query.filter_by(chat_id=g.id, user_id=user2.id).first() is not None
        # third user requests, gets rejected
        c3 = _login(app, user3)
        c3.post(f"{API}/groups/{g.id}/request")
        assert c1.post(f"{API}/groups/{g.id}/reject", json={"user_id": user3.id}).status_code == 200
        assert ChatMember.query.filter_by(chat_id=g.id, user_id=user3.id).first() is None

    def test_non_admin_cannot_list(self, app, user, user2):
        g = _group(user, name="Priv2", public=False, invite="sg_priv_2")
        c2 = _login(app, user2)
        assert c2.get(f"{API}/groups/{g.id}/requests").status_code == 403


class TestMemberPermsRestrict:
    def test_perms_set_get_reset(self, app, user, user2):
        g = _group(user, members=[user2], name="PermG", invite="sg_perm_1")
        c1 = _login(app, user)
        assert c1.post(f"{API}/groups/{g.id}/members/{user2.id}/perms",
                       json={"perms": {"can_pin_messages": True}}).status_code == 200
        d = c1.get(f"{API}/groups/{g.id}/members/{user2.id}/perms").get_json()["data"]
        assert d["perms"] == {"can_pin_messages": True}
        assert c1.delete(f"{API}/groups/{g.id}/members/{user2.id}/perms").status_code == 200
        d = c1.get(f"{API}/groups/{g.id}/members/{user2.id}/perms").get_json()["data"]
        assert d["perms"] == {}

    def test_restrict_flow(self, app, user, user2):
        g = _group(user, members=[user2], name="BanG", invite="sg_ban_1")
        c1 = _login(app, user)
        assert c1.post(f"{API}/groups/{g.id}/restrict", json={
            "kind": "ban", "user_id": user2.id, "reason": "spam"}).status_code == 200
        rows = c1.get(f"{API}/groups/{g.id}/restricted").get_json()["data"]["restricted"]
        assert any(r["user_id"] == user2.id and r["kind"] == "ban" for r in rows)
        assert c1.post(f"{API}/groups/{g.id}/unrestrict", json={
            "kind": "ban", "user_id": user2.id}).status_code == 200


class TestStoryShareReplaceExport:
    def test_share_and_replace(self, logged_in_client, user, user2):
        s = Story(user_id=user2.id, media_path="stories/o.jpg", media_type="image", caption="hi")
        db.session.add(s)
        db.session.commit()
        r = logged_in_client.post(f"{API}/stories/{s.id}/share")
        assert r.status_code == 200
        new_id = r.get_json()["data"]["story_id"]
        assert new_id != s.id
        assert logged_in_client.post(f"{API}/stories/{new_id}/replace", json={
            "caption": "mine now"}).status_code == 200
        assert db.session.get(Story, new_id).caption == "mine now"

    def test_export(self, logged_in_client, user):
        r = logged_in_client.post(f"{API}/export")
        assert r.status_code == 200
        d = r.get_json()["data"]
        assert d["user"]["username"] == user.username
        assert "messages" in d and "exported_at" in d

    def test_member_cannot_restrict(self, app, user, user2):
        g = _group(user, members=[user2], name="BanG2", invite="sg_ban_2")
        c2 = _login(app, user2)
        assert c2.post(f"{API}/groups/{g.id}/restrict", json={
            "kind": "mute", "user_id": user.id}).status_code == 403
