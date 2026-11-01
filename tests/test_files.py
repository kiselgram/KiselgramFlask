"""Tests for file upload/serve/delete endpoints under /files/ and /uploads/."""

import io
import os
import tempfile
from unittest.mock import patch
from app import db
from app.models import User, Message, File


class TestServeFile:
    """GET /uploads/<path:filename> and /uploads/avatars/<path:filename>"""

    def test_serve_file_not_found(self, client):
        resp = client.get("/uploads/nonexistent.jpg")
        assert resp.status_code == 404

    def test_serve_file_path_traversal(self, client):
        resp = client.get("/uploads/../../../etc/passwd")
        assert resp.status_code == 403

    def test_serve_avatar_not_found(self, client):
        resp = client.get("/uploads/avatars/nonexistent.jpg")
        assert resp.status_code == 404


class TestUploadFile:
    """POST /files/upload_file"""

    def test_upload_file_to_user(self, logged_in_client, user, user2):
        data = {
            "file": (io.BytesIO(b"fake-file-content"), "test_doc.pdf"),
            "receiver_id": str(user2.id),
            "message": "Here is a file",
        }
        resp = logged_in_client.post("/files/upload_file", data=data,
                                     content_type="multipart/form-data")
        assert resp.status_code == 200
        result = resp.get_json()
        assert result["success"] is True
        assert result["message"]["has_attachment"] is True
        assert result["message"]["file_type"] == "document"
        # Clean up uploaded file
        if os.path.exists(result["url"].lstrip("/")):
            os.remove(result["url"].lstrip("/"))

    def test_upload_file_no_auth(self, client, user2):
        data = {
            "file": (io.BytesIO(b"data"), "test.txt"),
            "receiver_id": str(user2.id),
        }
        resp = client.post("/files/upload_file", data=data,
                           content_type="multipart/form-data")
        assert resp.status_code == 401

    def test_upload_file_no_file(self, logged_in_client, user):
        resp = logged_in_client.post("/files/upload_file", data={
            "receiver_id": "1",
        }, content_type="multipart/form-data")
        assert resp.status_code == 400

    def test_upload_file_disallowed_type(self, logged_in_client, user, user2):
        data = {
            "file": (io.BytesIO(b"data"), "script.exe"),
            "receiver_id": str(user2.id),
        }
        resp = logged_in_client.post("/files/upload_file", data=data,
                                     content_type="multipart/form-data")
        assert resp.status_code == 400

    def test_upload_file_no_recipient(self, logged_in_client, user):
        data = {
            "file": (io.BytesIO(b"data"), "test.txt"),
        }
        resp = logged_in_client.post("/files/upload_file", data=data,
                                     content_type="multipart/form-data")
        assert resp.status_code == 400

    def test_upload_image(self, logged_in_client, user, user2):
        data = {
            "file": (io.BytesIO(b"fake-image"), "photo.jpg"),
            "receiver_id": str(user2.id),
        }
        resp = logged_in_client.post("/files/upload_file", data=data,
                                     content_type="multipart/form-data")
        assert resp.status_code == 200
        result = resp.get_json()
        assert result["message"]["file_type"] == "image"


class TestUploadAvatar:
    """POST /files/upload_avatar"""

    def test_upload_avatar(self, logged_in_client, user):
        import io as _io
        from PIL import Image as _Img
        _buf = _io.BytesIO()
        _Img.new("RGB", (1, 1), color="red").save(_buf, format="PNG")
        data = {"avatar": (_io.BytesIO(_buf.getvalue()), "avatar.png")}
        resp = logged_in_client.post("/files/upload_avatar", data=data,
                                     content_type="multipart/form-data")
        assert resp.status_code == 200
        result = resp.get_json()
        assert result["success"] is True
        assert "avatar_url" in result

    def test_upload_avatar_no_auth(self, client):
        data = {"avatar": (io.BytesIO(b"data"), "avatar.jpg")}
        resp = client.post("/files/upload_avatar", data=data,
                           content_type="multipart/form-data")
        assert resp.status_code == 401

    def test_upload_avatar_no_file(self, logged_in_client, user):
        resp = logged_in_client.post("/files/upload_avatar", data={},
                                     content_type="multipart/form-data")
        assert resp.status_code == 400

    def test_upload_avatar_invalid_type(self, logged_in_client, user):
        data = {"avatar": (io.BytesIO(b"data"), "avatar.exe")}
        resp = logged_in_client.post("/files/upload_avatar", data=data,
                                     content_type="multipart/form-data")
        assert resp.status_code == 400


class TestUploadStory:
    """POST /files/upload_story"""

    def test_upload_story_image(self, logged_in_client, user):
        data = {
            "media": (io.BytesIO(b"fake-image"), "story.jpg"),
            "caption": "My story",
        }
        resp = logged_in_client.post("/files/upload_story", data=data,
                                     content_type="multipart/form-data")
        assert resp.status_code == 200
        result = resp.get_json()
        assert result["success"] is True
        assert result["story"]["media_type"] == "image"

    def test_upload_story_no_auth(self, client):
        data = {"media": (io.BytesIO(b"data"), "story.jpg")}
        resp = client.post("/files/upload_story", data=data,
                           content_type="multipart/form-data")
        assert resp.status_code == 401

    def test_upload_story_no_media(self, logged_in_client, user):
        resp = logged_in_client.post("/files/upload_story", data={},
                                     content_type="multipart/form-data")
        assert resp.status_code == 400

    def test_upload_story_invalid_type(self, logged_in_client, user):
        data = {"media": (io.BytesIO(b"data"), "story.exe")}
        resp = logged_in_client.post("/files/upload_story", data=data,
                                     content_type="multipart/form-data")
        assert resp.status_code == 400


class TestDeleteFile:
    """DELETE /files/delete_file/<message_id>"""

    def _make_chat(self, u1, u2):
        from app.models import Chat, ChatMember
        c = Chat(chat_type='personal')
        db.session.add(c)
        db.session.flush()
        db.session.add(ChatMember(chat_id=c.id, user_id=u1.id, role='participant'))
        db.session.add(ChatMember(chat_id=c.id, user_id=u2.id, role='participant'))
        db.session.flush()
        return c

    def test_delete_file_message(self, logged_in_client, user, user2):
        chat = self._make_chat(user, user2)
        msg = Message(content="File message", sender_id=user.id,
                      receiver_id=user2.id, chat_id=chat.id,
                      file_path="test.pdf", has_attachment=True)
        db.session.add(msg)
        db.session.commit()
        resp = logged_in_client.delete(f"/files/delete_file/{msg.id}")
        assert resp.status_code == 200
        assert db.session.get(Message, msg.id) is None

    def test_delete_others_file(self, logged_in_client, user, user2):
        chat = self._make_chat(user, user2)
        msg = Message(content="Not yours", sender_id=user2.id,
                      receiver_id=user.id, chat_id=chat.id,
                      file_path="test.pdf", has_attachment=True)
        db.session.add(msg)
        db.session.commit()
        resp = logged_in_client.delete(f"/files/delete_file/{msg.id}")
        assert resp.status_code == 403

    def test_delete_file_no_auth(self, client, user, user2):
        chat = self._make_chat(user, user2)
        msg = Message(content="No auth", sender_id=user.id,
                      receiver_id=user2.id, chat_id=chat.id,
                      file_path="test.pdf")
        db.session.add(msg)
        db.session.commit()
        resp = client.delete(f"/files/delete_file/{msg.id}")
        assert resp.status_code == 401
