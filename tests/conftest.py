import pytest
from app import create_app, db as _db
from app.models import User, UserPremium, Chat, ChatMember
from datetime import datetime

TEST_DB = "sqlite:///:memory:"


@pytest.fixture(scope="session")
def app():
    """Create the Flask app once per session."""
    app = create_app()
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = TEST_DB
    app.config["MAIL_SUPPRESS_SEND"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        _db.create_all()
        yield app


@pytest.fixture(scope="function")
def client(app):
    return app.test_client()


def _clear_all_tables():
    """Delete all data from all tables (fast, no DDL)."""
    _db.session.execute(_db.text("PRAGMA foreign_keys = OFF"))
    for table in reversed(_db.metadata.sorted_tables):
        _db.session.execute(table.delete())
    _db.session.execute(_db.text("PRAGMA foreign_keys = ON"))
    _db.session.commit()


@pytest.fixture(scope="function")
def session(app):
    """Provide a clean database per test by truncating all data."""
    with app.app_context():
        _clear_all_tables()
        yield _db.session


@pytest.fixture
def user(session):
    u = User(
        username="testuser",
        email="test@example.com",
        email_verified=True,
        display_name="Test User",
    )
    u.set_password("testpass")
    session.add(u)
    session.commit()
    return u


@pytest.fixture
def user2(session):
    u = User(
        username="friend",
        email="friend@example.com",
        email_verified=True,
        display_name="Friend",
    )
    u.set_password("friendpass")
    session.add(u)
    session.commit()
    return u


@pytest.fixture
def admin_user(session):
    u = User(
        username="admin",
        email="admin@example.com",
        email_verified=True,
        display_name="Admin User",
        is_admin=True,
    )
    u.set_password("adminpass")
    session.add(u)
    session.commit()
    return u


@pytest.fixture
def personal_chat(session, user, user2):
    chat = Chat(chat_type='personal')
    session.add(chat)
    session.flush()
    m1 = ChatMember(chat_id=chat.id, user_id=user.id, role='participant')
    m2 = ChatMember(chat_id=chat.id, user_id=user2.id, role='participant')
    session.add(m1)
    session.add(m2)
    session.commit()
    return chat


@pytest.fixture
def premium_user(session):
    u = User(
        username="premium",
        email="premium@example.com",
        email_verified=True,
        display_name="Premium User",
    )
    u.set_password("premiumpass")
    session.add(u)
    session.flush()
    up = UserPremium(user_id=u.id, is_premium=True)
    session.add(up)
    session.commit()
    return u


@pytest.fixture
def user3(session):
    u = User(
        username="thirduser",
        email="third@example.com",
        email_verified=True,
        display_name="Third User",
    )
    u.set_password("thirdpass")
    session.add(u)
    session.commit()
    return u


@pytest.fixture
def logged_in_client(client, user):
    with client.session_transaction() as sess:
        sess["user_id"] = user.id
        sess["username"] = user.username
    return client


@pytest.fixture
def logged_in_admin(client, admin_user):
    with client.session_transaction() as sess:
        sess["user_id"] = admin_user.id
        sess["username"] = admin_user.username
    return client


@pytest.fixture
def logged_in_premium(client, premium_user):
    with client.session_transaction() as sess:
        sess["user_id"] = premium_user.id
        sess["username"] = premium_user.username
    return client


@pytest.fixture
def logged_in_user2(client, user2):
    with client.session_transaction() as sess:
        sess["user_id"] = user2.id
        sess["username"] = user2.username
    return client


def login_as(client, user_obj):
    """Helper to log in a client as a given user."""
    with client.session_transaction() as sess:
        sess["user_id"] = user_obj.id
        sess["username"] = user_obj.username


@pytest.fixture(autouse=True)
def clear_rate_limiter(app):
    """Clear the in-memory rate limiter before each test."""
    from app.utils.security import rate_limiter, _ACCOUNT_FAILURES
    rate_limiter._store.clear()
    _ACCOUNT_FAILURES.clear()
    # Clear in-memory typing status too
    try:
        from app.routes.spav2 import messages as _msgs
        _msgs._typing_status.clear()
    except Exception:
        pass
    yield
