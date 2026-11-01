"""Tests for video integration proxy endpoints under /video/."""

from unittest.mock import patch, MagicMock


class TestVideoHealth:
    """GET /video/health"""

    @patch("app.routes.video_integration.check_video_server")
    def test_health_ok(self, mock_check, client):
        mock_check.return_value = True
        resp = client.get("/video/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"

    @patch("app.routes.video_integration.check_video_server")
    def test_health_degraded(self, mock_check, client):
        mock_check.return_value = False
        resp = client.get("/video/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "degraded"


class TestVideoIndex:
    """GET /video/"""

    def test_index_redirects_when_not_logged_in(self, client):
        resp = client.get("/video/")
        assert resp.status_code == 302  # redirect to login

    def test_index_when_video_down(self, logged_in_client):
        resp = logged_in_client.get("/video/")
        # Should render video_server_down.html or return 503
        assert resp.status_code in (200, 503)


class TestVideoCreateRoom:
    """POST /video/create-room"""

    def test_create_room_not_logged_in(self, client):
        resp = client.post("/video/create-room", json={})
        assert resp.status_code == 302

    @patch("app.routes.video_integration.check_video_server")
    @patch("app.routes.video_integration._vs")
    def test_create_room_logged_in(self, mock_vs, mock_check, logged_in_client, user):
        mock_check.return_value = True
        mock_vs.return_value = {"room_id": "room-123", "success": True}
        resp = logged_in_client.post("/video/create-room", json={
            "room_name": "My Room",
        })
        assert resp.status_code == 200


class TestVideoListRooms:
    """GET /video/rooms"""

    @patch("app.routes.video_integration.check_video_server")
    @patch("app.routes.video_integration._vs")
    def test_list_rooms(self, mock_vs, mock_check, logged_in_client, user):
        mock_check.return_value = True
        mock_vs.return_value = {"rooms": []}
        resp = logged_in_client.get("/video/rooms")
        assert resp.status_code == 200


class TestVideoJoinRoom:
    """GET /video/room/<room_id>"""

    def test_join_room_not_logged_in(self, client):
        resp = client.get("/video/room/test-room")
        assert resp.status_code == 302

    @patch("app.routes.video_integration.check_video_server")
    @patch("app.routes.video_integration._vs")
    def test_join_room_logged_in(self, mock_vs, mock_check, logged_in_client, user):
        mock_check.return_value = True
        resp = logged_in_client.get("/video/room/test-room")
        assert resp.status_code == 302  # redirects to video server


class TestVideoRoomInfo:
    """GET /video/room/<room_id>/info"""

    @patch("app.routes.video_integration.check_video_server")
    @patch("app.routes.video_integration._vs")
    def test_room_info(self, mock_vs, mock_check, logged_in_client, user):
        mock_check.return_value = True
        mock_vs.return_value = {"room_id": "room-123", "participants": []}
        resp = logged_in_client.get("/video/room/room-123/info")
        assert resp.status_code == 200


class TestVideoCall:
    """POST /video/call/<user_id>"""

    @patch("app.routes.video_integration.check_video_server")
    @patch("app.routes.video_integration._vs")
    def test_initiate_call(self, mock_vs, mock_check, logged_in_client, user, user2):
        mock_check.return_value = True
        mock_vs.return_value = {"call_id": "call-123", "success": True}
        resp = logged_in_client.post(f"/video/call/{user2.id}", json={
            "callee_username": "friend",
        })
        assert resp.status_code == 200


class TestVideoIncomingCalls:
    """GET /video/calls/incoming"""

    @patch("app.routes.video_integration.check_video_server")
    @patch("app.routes.video_integration._vs")
    def test_incoming_calls(self, mock_vs, mock_check, logged_in_client, user):
        mock_check.return_value = True
        mock_vs.return_value = {"calls": []}
        resp = logged_in_client.get("/video/calls/incoming")
        assert resp.status_code == 200


class TestVideoAcceptDeclineEnd:
    """POST /video/calls/<call_id>/accept|decline|end"""

    @patch("app.routes.video_integration.check_video_server")
    @patch("app.routes.video_integration._vs")
    def test_accept_call(self, mock_vs, mock_check, logged_in_client, user):
        mock_check.return_value = True
        mock_vs.return_value = {"success": True}
        resp = logged_in_client.post("/video/calls/call-123/accept")
        assert resp.status_code == 200

    @patch("app.routes.video_integration.check_video_server")
    @patch("app.routes.video_integration._vs")
    def test_decline_call(self, mock_vs, mock_check, logged_in_client, user):
        mock_check.return_value = True
        mock_vs.return_value = {"success": True}
        resp = logged_in_client.post("/video/calls/call-123/decline")
        assert resp.status_code == 200

    @patch("app.routes.video_integration.check_video_server")
    @patch("app.routes.video_integration._vs")
    def test_end_call(self, mock_vs, mock_check, logged_in_client, user):
        mock_check.return_value = True
        mock_vs.return_value = {"success": True}
        resp = logged_in_client.post("/video/calls/call-123/end")
        assert resp.status_code == 200


class TestVideoLeave:
    """POST /video/leave/<room_id>"""

    def test_leave_room(self, logged_in_client, user):
        resp = logged_in_client.post("/video/leave/room-123")
        assert resp.status_code == 200


class TestVideoEmbed:
    """GET /video/embed/<room_id>"""

    def test_embed_not_logged_in(self, client):
        resp = client.get("/video/embed/room-123")
        assert resp.status_code == 302

    @patch("app.routes.video_integration.check_video_server")
    def test_embed_logged_in(self, mock_check, logged_in_client, user):
        mock_check.return_value = True
        resp = logged_in_client.get("/video/embed/room-123")
        assert resp.status_code == 200
