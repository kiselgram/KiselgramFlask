import io, json
from datetime import datetime
from app import db
from app.models import User, Chat, ChatMember, ChatSubscriber, Message, Call, VideoCall, VideoCallParticipant, RecentSearch


class TestProfile:
    """Tests for /api/profile endpoints"""

    def test_get_profile(self, logged_in_client, user):
        resp = logged_in_client.get("/api/profile")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        profile = data["user"]
        assert profile["username"] == user.username
        assert profile["display_name"] == user.display_name

    def test_get_profile_requires_auth(self, client):
        resp = client.get("/api/profile")
        assert resp.status_code == 401

    def test_update_profile_display_name(self, logged_in_client, user):
        resp = logged_in_client.put("/api/profile/update", json={"display_name": "New Name"})
        assert resp.status_code == 200
        assert db.session.get(User, user.id).display_name == "New Name"

    def test_update_profile_bio(self, logged_in_client, user):
        resp = logged_in_client.put("/api/profile/update", json={"bio": "Hello world"})
        assert resp.status_code == 200
        assert db.session.get(User, user.id).bio == "Hello world"

    def test_update_profile_bio_truncate(self, logged_in_client, user):
        long_bio = "X" * 600
        resp = logged_in_client.put("/api/profile/update", json={"bio": long_bio})
        assert resp.status_code == 200
        assert len(db.session.get(User, user.id).bio) == 500

    def test_update_profile_username(self, logged_in_client, user):
        resp = logged_in_client.put("/api/profile/update", json={"username": "newusername"})
        assert resp.status_code == 200
        assert db.session.get(User, user.id).username == "newusername"

    def test_update_profile_username_taken(self, logged_in_client, user, user2):
        resp = logged_in_client.put("/api/profile/update", json={"username": "friend"})
        assert resp.status_code == 400

    def test_update_profile_username_invalid(self, logged_in_client, user):
        resp = logged_in_client.put("/api/profile/update", json={"username": "bad user!"})
        assert resp.status_code == 400

    def test_upload_avatar(self, logged_in_client, user):
        data = {"avatar": (io.BytesIO(b"fake-png-data"), "avatar.png")}
        resp = logged_in_client.post("/api/profile/avatar", data=data,
                                     content_type="multipart/form-data")
        assert resp.status_code == 200
        result = resp.get_json()
        assert result["success"] is True
        assert "/uploads/avatars/" in result["avatar_url"]

    def test_upload_avatar_no_file(self, logged_in_client):
        resp = logged_in_client.post("/api/profile/avatar", data={})
        assert resp.status_code == 400

    def test_upload_avatar_invalid_format(self, logged_in_client):
        data = {"avatar": (io.BytesIO(b"data"), "avatar.exe")}
        resp = logged_in_client.post("/api/profile/avatar", data=data,
                                     content_type="multipart/form-data")
        assert resp.status_code == 400

    def test_get_settings(self, logged_in_client, user):
        resp = logged_in_client.get("/api/profile/settings")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "theme" in data["settings"]
        assert data["settings"]["font_size"] == 14

    def test_update_settings(self, logged_in_client, user):
        resp = logged_in_client.put("/api/profile/settings", json={
            "theme": "dark", "font_size": 16, "font_family": "'Roboto', sans-serif",
        })
        assert resp.status_code == 200
        u = db.session.get(User, user.id)
        assert u.theme == "dark"
        assert u.font_size == 16

    def test_get_privacy(self, logged_in_client, user):
        resp = logged_in_client.get("/api/profile/privacy")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["privacy"]["last_seen"] == "everyone"

    def test_update_privacy(self, logged_in_client, user):
        resp = logged_in_client.put("/api/profile/privacy", json={
            "last_seen": "contacts", "profile_photo": "nobody",
        })
        assert resp.status_code == 200
        u = db.session.get(User, user.id)
        assert u.privacy_last_seen == "contacts"
        assert u.privacy_photo == "nobody"


class TestCallsVideo:
    """Tests for /api/calls and /api/video endpoints"""

    def test_call_history_empty(self, logged_in_client):
        resp = logged_in_client.get("/api/calls/history")
        assert resp.status_code == 200
        assert resp.get_json()["calls"] == []

    def test_make_call(self, logged_in_client, user, user2):
        resp = logged_in_client.post("/api/calls/make", json={
            "receiver_id": user2.id, "call_type": "audio",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["call_id"] is not None
        call = db.session.get(Call, data["call_id"])
        assert call.status == "ringing"
        assert call.caller_id == user.id

    def test_make_call_missing_receiver(self, logged_in_client):
        resp = logged_in_client.post("/api/calls/make", json={})
        assert resp.status_code == 400

    def test_answer_call(self, logged_in_client, user, user2):
        call = Call(caller_id=user2.id, receiver_id=user.id, call_type="audio", status="ringing")
        db.session.add(call)
        db.session.commit()
        resp = logged_in_client.post("/api/calls/answer", json={"call_id": call.id})
        assert resp.status_code == 200
        assert db.session.get(Call, call.id).status == "answered"

    def test_end_call(self, logged_in_client, user, user2):
        call = Call(caller_id=user.id, receiver_id=user2.id, call_type="video", status="answered")
        db.session.add(call)
        db.session.commit()
        resp = logged_in_client.post("/api/calls/end", json={
            "call_id": call.id, "duration": 90,
        })
        assert resp.status_code == 200
        c = db.session.get(Call, call.id)
        assert c.status == "ended"
        assert c.duration == 90

    def test_create_video_room(self, logged_in_client, user):
        resp = logged_in_client.post("/api/video/create_room", json={"call_type": "video"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["room_id"] is not None
        vc = VideoCall.query.filter_by(room_id=data["room_id"]).first()
        assert vc is not None

    def test_join_video_room(self, logged_in_client, user, user2):
        resp = logged_in_client.post("/api/video/create_room", json={"call_type": "video"})
        room_id = resp.get_json()["room_id"]
        from tests.conftest import login_as
        login_as(logged_in_client, user2)
        resp = logged_in_client.post(f"/api/video/join/{room_id}", json={"audio_only": True})
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_join_nonexistent_room(self, logged_in_client):
        resp = logged_in_client.post("/api/video/join/fake_room_123")
        assert resp.status_code == 404

    def test_end_video_room(self, logged_in_client, user):
        resp = logged_in_client.post("/api/video/create_room")
        room_id = resp.get_json()["room_id"]
        resp = logged_in_client.post(f"/api/video/end/{room_id}")
        assert resp.status_code == 200
        vc = VideoCall.query.filter_by(room_id=room_id, status="active").first()
        assert vc is None

    def test_end_room_not_creator(self, logged_in_client, user, user2):
        resp = logged_in_client.post("/api/video/create_room")
        room_id = resp.get_json()["room_id"]
        from tests.conftest import login_as
        login_as(logged_in_client, user2)
        resp = logged_in_client.post(f"/api/video/end/{room_id}")
        assert resp.status_code == 403


class TestSearch:
    """Tests for /api/search endpoints"""

    def test_global_search_users(self, logged_in_client, user, user2):
        resp = logged_in_client.get("/api/search/global?q=friend")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        users = data["results"]["users"]
        assert len(users) == 1
        assert users[0]["username"] == "friend"

    def test_global_search_groups(self, logged_in_client, user):
        g = Chat(chat_type='group', name="Python Developers", owner_id=user.id, is_public=True)
        db.session.add(g)
        db.session.commit()
        db.session.add(ChatMember(user=user, chat=g, role="owner"))
        db.session.commit()
        resp = logged_in_client.get("/api/search/global?q=Python")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["results"]["groups"]) == 1

    def test_global_search_channels(self, logged_in_client, user, user2):
        c = Chat(chat_type='channel', name="Tech News", owner_id=user2.id, is_public=True)
        db.session.add(c)
        db.session.commit()
        resp = logged_in_client.get("/api/search/global?q=Tech")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["results"]["channels"]) == 1

    def test_global_search_short_query(self, logged_in_client):
        resp = logged_in_client.get("/api/search/global?q=a")
        assert resp.status_code == 200
        data = resp.get_json()
        # Should return no results for short query
        assert data["results"]["users"] == []
        assert data["results"]["groups"] == []

    def test_recent_searches(self, logged_in_client, user):
        db.session.add(RecentSearch(user_id=user.id, search_query="hello", search_type="all"))
        db.session.add(RecentSearch(user_id=user.id, search_query="world", search_type="all"))
        db.session.commit()
        resp = logged_in_client.get("/api/recent_searches")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 2

    def test_recent_searches_empty(self, logged_in_client):
        resp = logged_in_client.get("/api/recent_searches")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_global_search_saves_recent(self, logged_in_client, user):
        logged_in_client.get("/api/search/global?q=testuser")
        rs = RecentSearch.query.filter_by(user_id=user.id).first()
        assert rs is not None
        assert rs.search_query == "testuser"


class TestPins:
    """Tests for /api/pins endpoints"""

    def test_pin_chat(self, logged_in_client, user):
        resp = logged_in_client.post("/api/pin", json={
            "chat_type": "personal", "chat_id": 42,
        })
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_unpin_chat(self, logged_in_client, user):
        from app.models import PinnedChat
        db.session.add(PinnedChat(user_id=user.id, chat_type="personal", chat_id=42))
        db.session.commit()
        resp = logged_in_client.post("/api/unpin", json={
            "chat_type": "personal", "chat_id": 42,
        })
        assert resp.status_code == 200
        pc = PinnedChat.query.filter_by(user_id=user.id, chat_type="personal", chat_id=42).first()
        assert pc is None

    def test_get_pinned(self, logged_in_client, user):
        from app.models import PinnedChat
        db.session.add(PinnedChat(user_id=user.id, chat_type="personal", chat_id=1))
        db.session.add(PinnedChat(user_id=user.id, chat_type="group", chat_id=5))
        db.session.commit()
        resp = logged_in_client.get("/api/pinned")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert len(data["pinned"]) == 2


class TestFavorites:
    """Tests for /api/favorites endpoints"""

    def test_get_favorites_empty(self, logged_in_client):
        resp = logged_in_client.get("/api/favorites")
        assert resp.status_code == 200
        assert resp.get_json()["favorites"] == []

    def test_add_favorite(self, logged_in_client, user):
        resp = logged_in_client.post("/api/favorites", json={
            "file_type": "image", "file_path": "img.jpg", "file_name": "Photo",
        })
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
        from app.models import Favorite
        fav = Favorite.query.filter_by(user_id=user.id).first()
        assert fav is not None
        assert fav.file_name == "Photo"

    def test_delete_favorite(self, logged_in_client, user):
        from app.models import Favorite
        fav = Favorite(user_id=user.id, file_type="image", file_path="img.jpg", file_name="Pic")
        db.session.add(fav)
        db.session.commit()
        resp = logged_in_client.delete(f"/api/favorites/{fav.id}")
        assert resp.status_code == 200
        assert db.session.get(Favorite, fav.id) is None


class TestSessions:
    """Tests for /api/sessions endpoints"""

    def test_get_sessions(self, logged_in_client, user):
        from app.models import UserSession
        db.session.add(UserSession(user_id=user.id, session_token="tok1", device="Web"))
        db.session.commit()
        resp = logged_in_client.get("/api/sessions")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert len(data["sessions"]) == 1

    def test_revoke_session(self, logged_in_client, user):
        from app.models import UserSession
        s = UserSession(user_id=user.id, session_token="tok2", device="Mobile")
        db.session.add(s)
        db.session.commit()
        resp = logged_in_client.post("/api/sessions/revoke", json={"session_id": s.id})
        assert resp.status_code == 200
        assert db.session.get(UserSession, s.id) is None or db.session.get(UserSession, s.id).is_active is False


class TestPremium:
    """Tests for premium-specific behavior"""

    def test_premium_page_redirects_unauthenticated(self, client):
        resp = client.get("/premium", follow_redirects=False)
        assert resp.status_code == 302

    def test_premium_page_renders(self, logged_in_client):
        resp = logged_in_client.get("/premium")
        assert resp.status_code == 200

    def test_premium_user_gets_premium_template(self, logged_in_premium, premium_user):
        resp = logged_in_premium.get("/premium")
        assert resp.status_code == 200
