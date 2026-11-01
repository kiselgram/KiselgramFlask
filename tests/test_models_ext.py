"""Extended model tests for previously untested model classes.

Covers: File, StoryPrivacy, StoryAllowedUser, PushSubscription,
PreloadedAvatar, UserMusic, UserKSettings, QrLoginToken, LoginOtp.
"""

from datetime import datetime, timedelta, timezone
import secrets
from app import db
from app.models import (User, File, StoryPrivacy, StoryAllowedUser,
                        PushSubscription, PreloadedAvatar, UserMusic,
                        UserKSettings, QrLoginToken, LoginOtp, Story)


class TestFileModel:
    """File model — attached to Message for file uploads"""

    def test_create_file(self, session, user):
        f = File(
            file_type="image",
            file_name="photo.jpg",
            file_path="images/abc123.jpg",
            file_size=102400,
            preview_size="big",
            uploader_id=user.id,
        )
        session.add(f)
        session.commit()
        assert f.id is not None
        assert f.file_type == "image"
        assert f.file_name == "photo.jpg"

    def test_file_relationship(self, session, user):
        from app.models import Message
        f = File(file_type="document", file_name="doc.pdf",
                 file_path="documents/doc.pdf", file_size=5000,
                 uploader_id=user.id)
        session.add(f)
        session.flush()
        msg = Message(content="See doc", sender_id=user.id,
                      receiver_id=user.id, file_id=f.id,
                      has_attachment=True, chat_id=1)
        session.add(msg)
        session.commit()
        assert msg.file is not None
        assert msg.file.file_name == "doc.pdf"


class TestStoryPrivacyModel:
    """StoryPrivacy — per-story privacy setting"""

    def test_create_story_privacy(self, session, user):
        s = Story(user_id=user.id, media_path="stories/test.jpg",
                  media_type="image", created_at=datetime.utcnow())
        session.add(s)
        session.flush()
        sp = StoryPrivacy(story_id=s.id, privacy_type="close_friends")
        session.add(sp)
        session.commit()
        assert sp.story_id is not None
        assert sp.privacy_type == "close_friends"


class TestStoryAllowedUserModel:
    """StoryAllowedUser — individual users allowed to view a story"""

    def test_create_allowed_user(self, session, user, user2):
        s = Story(user_id=user.id, media_path="stories/test.jpg",
                  media_type="image", created_at=datetime.utcnow())
        session.add(s)
        session.flush()
        sau = StoryAllowedUser(story_id=s.id, user_id=user2.id)
        session.add(sau)
        session.commit()
        assert sau.story_id is not None


class TestPushSubscriptionModel:
    """PushSubscription — WebPush subscription storage"""

    def test_create_subscription(self, session, user):
        sub = PushSubscription(
            user_id=user.id,
            endpoint="https://push.example.com/endpoint123",
            p256dh="base64_encoded_key",
            auth="base64_encoded_auth",
        )
        session.add(sub)
        session.commit()
        assert sub.id is not None
        assert sub.endpoint == "https://push.example.com/endpoint123"

    def test_subscription_user_relationship(self, session, user):
        sub = PushSubscription(
            user_id=user.id,
            endpoint="https://push.example.com/abc",
            p256dh="key",
            auth="auth",
        )
        session.add(sub)
        session.commit()
        assert sub.user is not None
        assert sub.user.username == user.username


class TestPreloadedAvatarModel:
    """PreloadedAvatar — avatars available at registration"""

    def test_create_preloaded_avatar(self, session):
        pa = PreloadedAvatar(filename="avatar1.png", category="animals")
        session.add(pa)
        session.commit()
        assert pa.id is not None
        assert pa.filename == "avatar1.png"


class TestUserMusicModel:
    """UserMusic — music library tracks"""

    def test_create_track(self, session, user):
        t = UserMusic(
            user_id=user.id,
            file_url="/uploads/music/song.mp3",
            file_name="song.mp3",
            artist="Test Artist",
            title="Test Song",
            duration=180,
            added_at=datetime.utcnow(),
        )
        session.add(t)
        session.commit()
        assert t.id is not None
        assert t.title == "Test Song"

    def test_track_user_relationship(self, session, user):
        t = UserMusic(user_id=user.id, file_url="/uploads/music/t.mp3",
                      title="Track", added_at=datetime.utcnow())
        session.add(t)
        session.commit()
        assert t.user is not None
        assert t.user.username == user.username


class TestUserKSettingsModel:
    """UserKSettings — K-specific app settings"""

    def test_create_settings(self, session, user):
        ks = UserKSettings(user_id=user.id, settings={"theme": "dark"})
        session.add(ks)
        session.commit()
        assert ks.id is not None
        assert ks.settings == {"theme": "dark"}

    def test_to_dict(self, session, user):
        ks = UserKSettings(user_id=user.id, settings={"lang": "en"})
        session.add(ks)
        session.commit()
        d = ks.to_dict()
        assert d["user_id"] == user.id
        assert d["settings"]["lang"] == "en"


class TestQrLoginTokenModel:
    """QrLoginToken — QR code login tokens"""

    def test_create_token(self, session, user):
        token = secrets.token_urlsafe(32)
        qr = QrLoginToken(
            user_id=user.id,
            token=token,
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=2),
        )
        session.add(qr)
        session.commit()
        assert qr.id is not None
        assert qr.consumed is False

    def test_token_consumed(self, session, user):
        token = secrets.token_urlsafe(32)
        qr = QrLoginToken(
            user_id=user.id,
            token=token,
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=2),
        )
        session.add(qr)
        session.commit()
        qr.consumed = True
        qr.consumed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.commit()
        assert qr.consumed is True
        assert qr.consumed_at is not None


class TestLoginOtpModel:
    """LoginOtp — one-time password for V3 login"""

    def test_create_otp(self, session, user):
        otp = LoginOtp(
            user_id=user.id,
            code="123456",
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5),
        )
        session.add(otp)
        session.commit()
        assert otp.id is not None
        assert otp.used is False
        assert otp.code == "123456"

    def test_otp_expired(self, session, user):
        otp = LoginOtp(
            user_id=user.id,
            code="654321",
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1),
        )
        session.add(otp)
        session.commit()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        assert otp.expires_at < now

    def test_otp_mark_used(self, session, user):
        otp = LoginOtp(
            user_id=user.id,
            code="111111",
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5),
        )
        session.add(otp)
        session.commit()
        otp.used = True
        session.commit()
        assert otp.used is True
