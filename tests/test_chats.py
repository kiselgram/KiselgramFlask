import pytest
def test_chat_list_page_requires_login(client):
    resp = client.get("/chat_list", follow_redirects=False)
    assert resp.status_code == 302


def test_chat_list_page_renders(logged_in_client):
    resp = logged_in_client.get("/chat_list")
    assert resp.status_code == 200
    assert b"Kiselgram" in resp.data


def test_about_page(client):
    resp = client.get("/kis_info")
    assert resp.status_code == 200
    assert b"v4" in resp.data or b"Kiselgram" in resp.data


def test_premium_page_requires_login(client):
    resp = client.get("/premium", follow_redirects=False)
    assert resp.status_code == 302


def test_app_redirect(logged_in_client):
    resp = logged_in_client.get("/app")
    assert resp.status_code == 302


def test_mobile_page_renders(logged_in_client):
    resp = logged_in_client.get("/mobile")
    assert resp.status_code == 200


def test_user_profile_page(client, user):
    resp = client.get(f"/@{user.username}")
    assert resp.status_code == 200


def test_user_profile_page_not_found(client):
    resp = client.get("/@nonexistent_user")
    assert resp.status_code == 404


def test_chat_detail_redirect(logged_in_client):
    resp = logged_in_client.get("/chat/1")
    assert resp.status_code == 302


def test_group_detail_redirect(logged_in_client):
    resp = logged_in_client.get("/group/1")
    assert resp.status_code == 302


def test_channel_detail_redirect(logged_in_client):
    resp = logged_in_client.get("/channel/1")
    assert resp.status_code == 302
