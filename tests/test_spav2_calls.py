"""Tests for V2 API calls endpoints under /api.v2/api/."""

from unittest.mock import patch, MagicMock
from app import db
from app.models import User, Call, VideoCall


API_PREFIX = "/api.v2/api"


class TestV2CallHistory:
    """GET /api.v2/api/calls/history"""

    def test_call_history_empty(self, logged_in_client, user):
        resp = logged_in_client.get(f"{API_PREFIX}/calls/history")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["calls"] == []

    def test_call_history_with_data(self, logged_in_client, user, user2):
        from datetime import datetime
        call = Call(call_type="voice", caller_id=user.id,
                    receiver_id=user2.id, status="ended",
                    created_at=datetime.utcnow())
        db.session.add(call)
        db.session.commit()
        resp = logged_in_client.get(f"{API_PREFIX}/calls/history")
        data = resp.get_json()
        assert len(data["data"]["calls"]) == 1
        assert data["data"]["calls"][0]["call_type"] == "voice"
        assert data["data"]["calls"][0]["direction"] == "outgoing"

    def test_call_history_unauthorized(self, client):
        resp = client.get(f"{API_PREFIX}/calls/history")
        assert resp.status_code == 401


class TestV2MakeCall:
    """POST /api.v2/api/calls/make"""

    def test_make_call(self, logged_in_client, user, user2):
        resp = logged_in_client.post(f"{API_PREFIX}/calls/make", json={
            "receiver_id": user2.id,
            "call_type": "voice",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["success"] is True
        assert data["data"]["call"]["call_type"] == "voice"
        assert data["data"]["call"]["status"] == "ringing"
        assert "room_token" in data["data"]["call"]

    def test_make_call_video(self, logged_in_client, user, user2):
        resp = logged_in_client.post(f"{API_PREFIX}/calls/make", json={
            "receiver_id": user2.id,
            "call_type": "video",
        })
        assert resp.status_code == 201
        assert resp.get_json()["data"]["call"]["call_type"] == "video"

    def test_make_call_invalid_type(self, logged_in_client, user, user2):
        resp = logged_in_client.post(f"{API_PREFIX}/calls/make", json={
            "receiver_id": user2.id,
            "call_type": "fax",
        })
        assert resp.status_code == 400

    def test_make_call_user_not_found(self, logged_in_client, user):
        resp = logged_in_client.post(f"{API_PREFIX}/calls/make", json={
            "receiver_id": 99999,
        })
        assert resp.status_code == 404

    def test_make_call_unauthorized(self, client, user2):
        resp = client.post(f"{API_PREFIX}/calls/make", json={
            "receiver_id": user2.id,
        })
        assert resp.status_code == 401


class TestV2VideoCreateRoom:
    """POST /api.v2/api/video/create-room"""

    @patch("app.routes.spav2.calls.requests.post")
    def test_create_room(self, mock_post, logged_in_client, user):
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.json.return_value = {
            "room_id": "test-room-123",
            "join_url": "http://video:5001/room/test-room-123",
        }
        resp = logged_in_client.post(f"{API_PREFIX}/video/create-room", json={
            "chat_id": 1,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["room_id"] == "test-room-123"
        vc = VideoCall.query.filter_by(room_id="test-room-123").first()
        assert vc is not None

    @patch("app.routes.spav2.calls.requests.post")
    def test_create_room_video_server_error(self, mock_post, logged_in_client, user):
        mock_post.return_value = MagicMock(status_code=500)
        resp = logged_in_client.post(f"{API_PREFIX}/video/create-room", json={
            "chat_id": 1,
        })
        assert resp.status_code == 502

    @patch("app.routes.spav2.calls.requests.post")
    def test_create_room_connection_error(self, mock_post, logged_in_client, user):
        import requests
        mock_post.side_effect = requests.exceptions.ConnectionError()
        resp = logged_in_client.post(f"{API_PREFIX}/video/create-room", json={
            "chat_id": 1,
        })
        assert resp.status_code == 503

    def test_create_room_unauthorized(self, client):
        resp = client.post(f"{API_PREFIX}/video/create-room", json={})
        assert resp.status_code == 401
