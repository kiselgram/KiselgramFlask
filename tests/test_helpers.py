# tests/test_helpers.py
from app.utils.helpers import hash_password, generate_invite_link, format_file_size, allowed_file

def test_hash_password():
    h = hash_password("test")
    assert isinstance(h, str) and len(h) > 0
    from werkzeug.security import check_password_hash
    assert check_password_hash(h, "test") is True

def test_generate_invite_link():
    link = generate_invite_link()
    assert len(link) == 22   # secrets.token_urlsafe(16) produces 22 chars

def test_format_file_size():
    assert format_file_size(0) == "0 B"
    assert format_file_size(1024) == "1.0 KB"
    assert format_file_size(1048576) == "1.0 MB"

def test_allowed_file():
    assert allowed_file("doc.pdf") == True
    assert allowed_file("photo.jpg") == True
    assert allowed_file("script.exe") == False