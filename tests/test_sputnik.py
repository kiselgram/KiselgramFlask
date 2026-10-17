"""Sputnik ideas pack tests — ported ideas from ilyyagoncharow12/sputnik."""

from datetime import datetime, timedelta

from app import db
from app.models import Message

API = "/api.v2/api/sputnik"


def _msg(user, chat_id, content="hello", **kw):
    m = Message(content=content, sender_id=user.id, chat_id=chat_id,
                timestamp=datetime.utcnow(), **kw)
    db.session.add(m)
    db.session.commit()
    return m


class TestEditHistory:
    def test_edit_saves_history(self, logged_in_client, user, personal_chat):
        m = _msg(user, personal_chat.id, "v1")
        r = logged_in_client.post(f"{API}/messages/{m.id}/edit", json={"content": "v2"})
        assert r.status_code == 200
        r = logged_in_client.get(f"{API}/messages/{m.id}/edits")
        edits = r.get_json()["data"]["edits"]
        assert len(edits) == 1
        assert edits[0]["old_text"] == "v1"
        assert edits[0]["new_text"] == "v2"

    def test_edit_forbidden_for_others(self, logged_in_client, user, user2, personal_chat):
        m = _msg(user2, personal_chat.id, "nope")
        r = logged_in_client.post(f"{API}/messages/{m.id}/edit", json={"content": "hack"})
        assert r.status_code == 403


class TestTrash:
    def test_trash_restore_cycle(self, logged_in_client, user, personal_chat):
        m = _msg(user, personal_chat.id, "bye")
        assert logged_in_client.post(f"{API}/messages/{m.id}/trash").status_code == 200
        items = logged_in_client.get(f"{API}/trash").get_json()["data"]["trash"]
        assert any(t["message_id"] == m.id for t in items)
        r = logged_in_client.post(f"{API}/trash/restore", json={"message_id": m.id})
        assert r.status_code == 200
        assert db.session.get(Message, m.id).is_deleted is False

    def test_trash_clear(self, logged_in_client, user, personal_chat):
        m = _msg(user, personal_chat.id, "x")
        logged_in_client.post(f"{API}/messages/{m.id}/trash")
        assert logged_in_client.post(f"{API}/trash/clear").status_code == 200
        assert logged_in_client.get(f"{API}/trash").get_json()["data"]["trash"] == []


class TestLinkPreview:
    def test_rejects_bad_url(self, logged_in_client):
        r = logged_in_client.get(f"{API}/link_preview", query_string={"url": "ftp://x"})
        assert r.status_code == 400

    def test_blocks_private_host(self, logged_in_client):
        r = logged_in_client.get(f"{API}/link_preview", query_string={"url": "http://127.0.0.1/secret"})
        assert r.status_code in (400, 502)
        assert r.get_json()["success"] is False


class TestAlbumsViews:
    def test_album_create_get_reorder(self, logged_in_client, user, personal_chat):
        ids = [_msg(user, personal_chat.id, f"p{i}").id for i in range(3)]
        r = logged_in_client.post(f"{API}/albums/create", json={"message_ids": ids})
        assert r.status_code == 200
        aid = r.get_json()["data"]["album_id"]
        got = logged_in_client.get(f"{API}/albums/{aid}").get_json()["data"]["message_ids"]
        assert got == ids
        rev = ids[::-1]
        r = logged_in_client.post(f"{API}/albums/{aid}/reorder", json={"message_ids": rev})
        assert r.status_code == 200
        got = logged_in_client.get(f"{API}/albums/{aid}").get_json()["data"]["message_ids"]
        assert got == rev

    def test_view_dedup(self, logged_in_client, user, personal_chat):
        m = _msg(user, personal_chat.id, "seen")
        r1 = logged_in_client.post(f"{API}/messages/{m.id}/view").get_json()["data"]
        r2 = logged_in_client.post(f"{API}/messages/{m.id}/view").get_json()["data"]
        assert r1["views"] == 1
        assert r2["views"] == 1

    def test_round_validation(self, logged_in_client, personal_chat):
        r = logged_in_client.post(f"{API}/round/send", json={
            "chat_id": personal_chat.id, "file_path": "circles/a.mp4", "duration": 61})
        assert r.status_code == 400
        r = logged_in_client.post(f"{API}/round/send", json={
            "chat_id": personal_chat.id, "file_path": "circles/a.mp4", "duration": 10})
        assert r.status_code == 200


class TestStickersFolders:
    def test_sticker_flow(self, logged_in_client, user, personal_chat):
        r = logged_in_client.post(f"{API}/stickers/upload", json={"file_path": "stickers/a.png", "emoji": "🔥"})
        sid = r.get_json()["data"]["sticker_id"]
        assert logged_in_client.post(f"{API}/stickers/{sid}/favorite", json={"favorite": True}).status_code == 200
        fav = logged_in_client.get(f"{API}/stickers", query_string={"favorite": "1"}).get_json()["data"]["stickers"]
        assert any(s["id"] == sid for s in fav)
        r = logged_in_client.post(f"{API}/stickers/send", json={"sticker_id": sid, "chat_id": personal_chat.id})
        assert r.status_code == 200

    def test_folder_flow(self, logged_in_client, personal_chat):
        r = logged_in_client.post(f"{API}/folders/create", json={"name": "Work"})
        fid = r.get_json()["data"]["folder_id"]
        r = logged_in_client.post(f"{API}/folders/{fid}/chats", json={
            "chats": [{"chat_type": "personal", "chat_id": personal_chat.id},
                      {"chat_type": "group", "chat_id": personal_chat.id}]})
        assert r.status_code == 200
        folders = logged_in_client.get(f"{API}/folders").get_json()["data"]["folders"]
        assert any(f["id"] == fid and len(f["chats"]) == 2 for f in folders)
        assert logged_in_client.delete(f"{API}/folders/{fid}").status_code == 200


class TestSecretsAccounts:
    def test_cloud_and_applock(self, logged_in_client):
        assert logged_in_client.post(f"{API}/cloud/setup", json={"password": "secret1"}).status_code == 200
        assert logged_in_client.post(f"{API}/cloud/verify", json={"password": "secret1"}).status_code == 200
        assert logged_in_client.post(f"{API}/cloud/verify", json={"password": "nope"}).status_code == 403
        assert logged_in_client.post(f"{API}/applock/set", json={"pin": "1234"}).status_code == 200
        assert logged_in_client.post(f"{API}/applock/verify", json={"pin": "1234"}).status_code == 200
        assert logged_in_client.post(f"{API}/applock/verify", json={"pin": "0000"}).status_code == 403

    def test_contacts_import(self, logged_in_client, user, user2):
        r = logged_in_client.post(f"{API}/contacts/import", json={"usernames": [user2.username]})
        assert r.get_json()["data"]["added"] >= 1
        r = logged_in_client.post(f"{API}/contacts/import",
                                  json={"vcf": f"BEGIN:VCARD\nFN:{user2.username}\nEND:VCARD"})
        assert r.status_code == 200


class TestScheduledHealth:
    def test_scheduled_list_send_now(self, logged_in_client, user, personal_chat):
        future = datetime.utcnow() + timedelta(hours=1)
        m = _msg(user, personal_chat.id, "later", scheduled_at=future)
        items = logged_in_client.get(f"{API}/scheduled").get_json()["data"]["scheduled"]
        assert any(s["message_id"] == m.id for s in items)
        assert logged_in_client.post(f"{API}/scheduled/{m.id}/send_now").status_code == 200

    def test_db_health_admin_only(self, app, user, admin_user):
        c_user = app.test_client()
        with c_user.session_transaction() as s:
            s["user_id"] = user.id
        c_admin = app.test_client()
        with c_admin.session_transaction() as s:
            s["user_id"] = admin_user.id
        assert c_user.get(f"{API}/db/health").status_code == 403
        r = c_admin.get(f"{API}/db/health")
        assert r.status_code == 200
        assert "edits" in r.get_json()["data"]
        assert c_admin.post(f"{API}/db/cleanup_orphans").status_code == 200

    def test_features(self, logged_in_client):
        assert logged_in_client.get(f"{API}/features").status_code == 200
