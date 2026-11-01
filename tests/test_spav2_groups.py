"""Tests for V2 API group endpoints under /api.v2/api/."""

from datetime import datetime
from app import db
from app.models import User, Chat, ChatMember, Message, GroupPermission


API_PREFIX = "/api.v2/api"


def _create_group(owner, members=None, name="Test Group", session=None):
    """Helper to create a group and return it."""
    if members is None:
        members = []
    invite_link = "test_invite_link"
    chat = Chat(chat_type="group", name=name, description="A test group",
                owner_id=owner.id, is_public=False, invite_link=invite_link,
                created_at=datetime.utcnow())
    db.session.add(chat)
    db.session.flush()
    db.session.add(ChatMember(user_id=owner.id, chat_id=chat.id, role="owner"))
    for m in members:
        db.session.add(ChatMember(user_id=m.id, chat_id=chat.id, role="member"))
    for role in ("owner", "admin", "member"):
        db.session.add(GroupPermission(
            chat_id=chat.id, role=role, can_send_messages=True,
            can_send_media=True, can_add_members=role != "member",
            can_pin_messages=role != "member",
            can_change_info=role != "member",
            can_delete_messages=role != "member",
            can_ban_users=role == "owner"))
    db.session.commit()
    return chat


class TestV2Groups:
    """GET /api.v2/api/groups, GET /api.v2/api/groups/<id>"""

    def test_get_groups_empty(self, logged_in_client, user):
        resp = logged_in_client.get(f"{API_PREFIX}/groups")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["groups"] == []

    def test_get_groups_with_membership(self, logged_in_client, user, user2):
        _create_group(user, members=[user2])
        resp = logged_in_client.get(f"{API_PREFIX}/groups")
        data = resp.get_json()
        assert len(data["data"]["groups"]) == 1
        assert data["data"]["groups"][0]["name"] == "Test Group"
        assert data["data"]["groups"][0]["my_role"] == "owner"

    def test_get_group_detail(self, logged_in_client, user, user2):
        g = _create_group(user, members=[user2])
        resp = logged_in_client.get(f"{API_PREFIX}/groups/{g.id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["name"] == "Test Group"
        assert data["data"]["owner_id"] == user.id

    def test_get_group_not_found(self, logged_in_client, user):
        resp = logged_in_client.get(f"{API_PREFIX}/groups/99999")
        assert resp.status_code == 404

    def test_get_group_not_member(self, logged_in_client, user, user2, user3):
        g = _create_group(user2, members=[])
        resp = logged_in_client.get(f"{API_PREFIX}/groups/{g.id}")
        assert resp.status_code == 403

    def test_groups_unauthorized(self, client):
        resp = client.get(f"{API_PREFIX}/groups")
        assert resp.status_code == 401


class TestV2GroupMembers:
    """GET /api.v2/api/groups/<id>/members"""

    def test_get_members(self, logged_in_client, user, user2):
        g = _create_group(user, members=[user2])
        resp = logged_in_client.get(f"{API_PREFIX}/groups/{g.id}/members")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["data"]["members"]) == 2
        usernames = [m["username"] for m in data["data"]["members"]]
        assert "testuser" in usernames
        assert "friend" in usernames

    def test_get_members_pagination(self, logged_in_client, user):
        g = _create_group(user, members=[])
        resp = logged_in_client.get(
            f"{API_PREFIX}/groups/{g.id}/members?offset=0&limit=10")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["data"]["members"]) == 1  # just the owner


class TestV2GroupMessages:
    """GET /api.v2/api/group_messages/<group_id>"""

    def test_get_group_messages(self, logged_in_client, user, user2):
        g = _create_group(user, members=[user2])
        for i in range(3):
            db.session.add(Message(
                content=f"Group msg {i}", sender_id=user.id,
                chat_id=g.id, receiver_id=user.id,
                timestamp=datetime.utcnow()))
        db.session.commit()
        resp = logged_in_client.get(f"{API_PREFIX}/group_messages/{g.id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["data"]["messages"]) == 3

    def test_get_group_messages_not_member(self, logged_in_client, user, user2):
        g = _create_group(user2, members=[])
        resp = logged_in_client.get(f"{API_PREFIX}/group_messages/{g.id}")
        assert resp.status_code == 403

    def test_get_group_messages_pagination(self, logged_in_client, user, user2):
        g = _create_group(user, members=[user2])
        msgs = []
        for i in range(5):
            m = Message(content=f"M{i}", sender_id=user.id,
                        chat_id=g.id, receiver_id=user.id,
                        timestamp=datetime.utcnow())
            db.session.add(m)
            msgs.append(m)
        db.session.commit()
        resp = logged_in_client.get(
            f"{API_PREFIX}/group_messages/{g.id}?after={msgs[2].id}&limit=2")
        data = resp.get_json()
        assert len(data["data"]["messages"]) == 2
        assert data["data"]["pagination"]["has_more"] is False


class TestV2CreateGroup:
    """POST /api.v2/api/groups/create"""

    def test_create_group(self, logged_in_client, user, user2):
        resp = logged_in_client.post(f"{API_PREFIX}/groups/create", json={
            "name": "New Group",
            "description": "A brand new group",
            "member_ids": [user2.id],
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["data"]["group"]["name"] == "New Group"
        g = Chat.query.filter_by(name="New Group").first()
        assert g is not None
        assert g.chat_type == "group"
        members = ChatMember.query.filter_by(chat_id=g.id).all()
        assert len(members) == 2

    def test_create_group_no_name(self, logged_in_client, user):
        resp = logged_in_client.post(f"{API_PREFIX}/groups/create", json={
            "member_ids": [],
        })
        assert resp.status_code == 400

    def test_create_group_unauthorized(self, client):
        resp = client.post(f"{API_PREFIX}/groups/create", json={
            "name": "Hacker Group",
        })
        assert resp.status_code == 401


class TestV2SendGroupMessage:
    """POST /api.v2/api/send_group_message"""

    def test_send_group_message(self, logged_in_client, user, user2):
        g = _create_group(user, members=[user2])
        resp = logged_in_client.post(f"{API_PREFIX}/send_group_message", json={
            "group_id": g.id,
            "content": "Hello group!",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["data"]["message"]["content"] == "Hello group!"
        msg = Message.query.filter_by(chat_id=g.id).first()
        assert msg is not None

    def test_send_group_message_not_member(self, logged_in_client, user, user2):
        g = _create_group(user2, members=[])
        resp = logged_in_client.post(f"{API_PREFIX}/send_group_message", json={
            "group_id": g.id,
            "content": "Intruder!",
        })
        assert resp.status_code == 403

    def test_send_group_message_missing_group(self, logged_in_client, user):
        resp = logged_in_client.post(f"{API_PREFIX}/send_group_message", json={
            "content": "No group",
        })
        assert resp.status_code == 400


class TestV2UpdateGroup:
    """POST /api.v2/api/groups/<id>/update"""

    def test_update_group_name(self, logged_in_client, user, user2):
        g = _create_group(user, members=[user2])
        resp = logged_in_client.post(
            f"{API_PREFIX}/groups/{g.id}/update", json={
                "name": "Renamed Group",
            })
        assert resp.status_code == 200
        assert db.session.get(Chat, g.id).name == "Renamed Group"

    def test_update_group_not_owner(self, logged_in_client, user, user2):
        g = _create_group(user2, members=[user])
        resp = logged_in_client.post(
            f"{API_PREFIX}/groups/{g.id}/update", json={
                "name": "Hijacked",
            })
        assert resp.status_code == 403


class TestV2GroupMemberRole:
    """POST /api.v2/api/groups/<id>/members/<user_id>/role"""

    def test_promote_to_admin(self, logged_in_client, user, user2):
        g = _create_group(user, members=[user2])
        resp = logged_in_client.post(
            f"{API_PREFIX}/groups/{g.id}/members/{user2.id}/role", json={
                "role": "admin",
            })
        assert resp.status_code == 200
        m = ChatMember.query.filter_by(
            user_id=user2.id, chat_id=g.id).first()
        assert m.role == "admin"

    def test_demote_to_member(self, logged_in_client, user, user2):
        g = _create_group(user, members=[user2])
        cm = ChatMember.query.filter_by(user_id=user2.id, chat_id=g.id).first()
        cm.role = 'admin'
        db.session.commit()
        resp = logged_in_client.post(
            f"{API_PREFIX}/groups/{g.id}/members/{user2.id}/role", json={
                "role": "member",
            })
        assert resp.status_code == 200
        m = ChatMember.query.filter_by(
            user_id=user2.id, chat_id=g.id).first()
        assert m.role == "member"

    def test_change_role_not_owner(self, logged_in_client, user, user2):
        g = _create_group(user2, members=[user])
        resp = logged_in_client.post(
            f"{API_PREFIX}/groups/{g.id}/members/{user2.id}/role", json={
                "role": "admin",
            })
        assert resp.status_code == 403

    def test_change_role_invalid(self, logged_in_client, user, user2):
        g = _create_group(user, members=[user2])
        resp = logged_in_client.post(
            f"{API_PREFIX}/groups/{g.id}/members/{user2.id}/role", json={
                "role": "superadmin",
            })
        assert resp.status_code == 400


class TestV2JoinLeaveGroup:
    """GET /api.v2/api/join_group/<invite_link>, POST leave_group"""

    def test_join_group(self, logged_in_client, user, user2):
        g = _create_group(user2, members=[])
        resp = logged_in_client.get(
            f"{API_PREFIX}/join_group/{g.invite_link}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["group"]["name"] == g.name
        assert ChatMember.query.filter_by(
            user_id=user.id, chat_id=g.id).first() is not None

    def test_join_group_invalid_link(self, logged_in_client, user):
        resp = logged_in_client.get(f"{API_PREFIX}/join_group/badlink123")
        assert resp.status_code == 404

    def test_leave_group(self, logged_in_client, user, user2):
        g = _create_group(user2, members=[user])
        resp = logged_in_client.post(f"{API_PREFIX}/leave_group/{g.id}")
        assert resp.status_code == 200
        assert ChatMember.query.filter_by(
            user_id=user.id, chat_id=g.id).first() is None

    def test_leave_group_owner(self, logged_in_client, user, user2):
        g = _create_group(user, members=[user2])
        resp = logged_in_client.post(f"{API_PREFIX}/leave_group/{g.id}")
        assert resp.status_code == 403

    def test_leave_group_not_member(self, logged_in_client, user, user2):
        g = _create_group(user2, members=[])
        resp = logged_in_client.post(f"{API_PREFIX}/leave_group/{g.id}")
        assert resp.status_code == 404
