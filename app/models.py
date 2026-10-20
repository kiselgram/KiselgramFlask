# app/models.py

from app import db
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash


# ============ USER MODELS ============

class User(db.Model):
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(80), unique=True, nullable=True)
    email_verified = db.Column(db.Boolean, default=False)
    display_name = db.Column(db.String(80), nullable=True)
    password_hash = db.Column(db.String(120), nullable=True)
    telegram_chat_id = db.Column(db.String(50), unique=True, nullable=True)
    telegram_username = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    bio = db.Column(db.Text, nullable=True)
    avatar_url = db.Column(db.String(500), nullable=True)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    is_online = db.Column(db.Boolean, default=False)

    # Premium fields moved to UserPremium model
    is_admin = db.Column(db.Boolean, default=False)

    # Avatar type
    avatar_type = "image"

    # Notification settings
    notification_sound = db.Column(db.String(50), default='default')
    per_chat_sounds = db.Column(db.JSON, default=dict)
    mute_all = db.Column(db.Boolean, default=False)
    do_not_disturb = db.Column(db.Boolean, default=False)

    # Bot fields
    is_bot = db.Column(db.Boolean, default=False)
    bot_owner_id = db.Column(db.Integer, nullable=True)
    bot_token = db.Column(db.String(64), nullable=True)
    bot_webapp_url = db.Column(db.String(500), nullable=True)

    # Status emoji (Premium)
    status_emoji = db.Column(db.String(10), default='')

    # Privacy settings
    privacy_last_seen = db.Column(db.String(20), default='everyone')
    privacy_photo = db.Column(db.String(20), default='everyone')
    privacy_forward = db.Column(db.String(20), default='everyone')
    privacy_calls = db.Column(db.String(20), default='everyone')
    privacy_messages = db.Column(db.String(20), default='everyone')

    # Appearance settings
    theme = db.Column(db.String(10), default='light')
    font_size = db.Column(db.Integer, default=14)
    bubble_radius = db.Column(db.Integer, default=18)
    font_family = db.Column(db.String(100), default="'Inter', sans-serif")
    my_message_color = db.Column(db.String(20), default='#667eea')
    their_message_color = db.Column(db.String(20), default='#f3f4f6')
    wallpaper = db.Column(db.String(50), default='')
    wallpaper_image = db.Column(db.String(500), nullable=True)
    banner_color = db.Column(db.String(20), default='#2b8d8d')
    banner_image = db.Column(db.String(500), nullable=True)

    # Soft delete
    is_deleted = db.Column(db.Boolean, default=False)
    deleted_at = db.Column(db.DateTime, nullable=True)

    # Account freeze (suspend without deleting)
    is_frozen = db.Column(db.Boolean, default=False, index=True)
    frozen_at = db.Column(db.DateTime, nullable=True)

    # Guest mode
    is_guest = db.Column(db.Boolean, default=False)
    guest_expires_at = db.Column(db.DateTime, nullable=True)

    # Google OAuth
    google_id = db.Column(db.String(100), unique=True, nullable=True)
    profile_pic = db.Column(db.String(200), nullable=True)

    # Relationships
    sent_messages = db.relationship('Message', foreign_keys='Message.sender_id', backref='sender', lazy=True)
    received_messages = db.relationship('Message', foreign_keys='Message.receiver_id', backref='receiver', lazy=True)
    user_reactions = db.relationship('Reaction', backref='user', lazy=True)
    blocked_users = db.relationship('BlockedUser', foreign_keys='BlockedUser.user_id', backref='user', lazy=True)
    sessions = db.relationship('UserSession', backref='user', lazy=True)
    stories = db.relationship('Story', backref='user', lazy='dynamic')
    story_views = db.relationship('StoryView', backref='viewer', lazy='dynamic')
    story_likes = db.relationship('StoryLike', backref='user', lazy='dynamic')
    story_reactions = db.relationship('StoryReaction', backref='user', lazy='dynamic')

    # Premium relationship
    premium = db.relationship('UserPremium', backref='user', uselist=False, lazy=True)

    # Chat memberships (unified)
    chat_memberships = db.relationship('ChatMember', backref='user', lazy=True)
    chat_subscriptions = db.relationship('ChatSubscriber', backref='user', lazy=True)

    # Owned chats (groups/channels)
    owned_chats = db.relationship('Chat', foreign_keys='Chat.owner_id', backref='owner', lazy=True)

    # User properties
    reports_filed = db.relationship('Report', foreign_keys='Report.reporter_id', backref='reporter', lazy=True)
    reports_received = db.relationship('Report', foreign_keys='Report.reported_user_id', backref='reported_user', lazy=True)
    push_subscriptions = db.relationship('PushSubscription', backref='user', lazy=True)
    favorites = db.relationship('Favorite', backref='user', lazy=True)
    recent_searches = db.relationship('RecentSearch', backref='user', lazy=True)
    pinned_chats = db.relationship('PinnedChat', backref='user', lazy=True)
    email_verifications = db.relationship('EmailVerification', backref='user', lazy=True)
    k_settings = db.relationship('UserKSettings', backref='user', uselist=False, lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'display_name': self.display_name or self.username,
            'bio': self.bio,
            'avatar_url': self.avatar_url,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
            'is_online': self.is_online,
            'status_emoji': self.status_emoji,
            'is_premium': self.premium.is_premium if self.premium else False
        }

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User(id={self.id}, username={self.username!r})>'


class UserPremium(db.Model):
    """Separate premium model for users"""
    __tablename__ = 'user_premium'

    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), primary_key=True)
    is_premium = db.Column(db.Boolean, default=False)
    premium_since = db.Column(db.DateTime, nullable=True)
    premium_expires_at = db.Column(db.DateTime, nullable=True)
    premium_auto_renew = db.Column(db.Boolean, default=False)
    premium_payment_method = db.Column(db.String(50), nullable=True)
    premium_plan = db.Column(db.String(20), nullable=True)

    def __repr__(self):
        return f'<UserPremium(user_id={self.user_id}, premium={self.is_premium})>'


# ============ UNIFIED CHAT MODEL ============

class Chat(db.Model):
    """Unified chat: personal, group, or channel"""
    __tablename__ = 'chats'

    id = db.Column(db.Integer, primary_key=True)
    chat_type = db.Column(db.String(20), nullable=False, index=True)  # 'personal', 'group', 'channel'
    name = db.Column(db.String(100), nullable=True)       # For group/channel; personal uses other user's name
    description = db.Column(db.Text, nullable=True)
    avatar_url = db.Column(db.String(500), nullable=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)  # For group/channel; null for personal
    is_public = db.Column(db.Boolean, default=True)       # For group/channel
    invite_link = db.Column(db.String(100), unique=True, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # For personal chats: the two participants are stored in ChatMember with role='participant'
    user1_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True, index=True)
    user2_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True, index=True)

    # Relationships
    members = db.relationship('ChatMember', backref='chat', lazy='dynamic', cascade='all, delete-orphan')
    subscribers = db.relationship('ChatSubscriber', backref='chat', lazy='dynamic', cascade='all, delete-orphan')
    messages = db.relationship('Message', backref='chat', lazy='dynamic')
    permissions = db.relationship('GroupPermission', backref='chat', lazy='dynamic', cascade='all, delete-orphan')
    admins = db.relationship('ChannelAdmin', backref='chat', lazy='dynamic', cascade='all, delete-orphan')

    archived = db.Column(db.Boolean, default=False)
    muted_until = db.Column(db.DateTime, nullable=True)
    theme_color = db.Column(db.String(20), nullable=True)
    wallpaper = db.Column(db.String(500), nullable=True)
    auto_delete_ttl = db.Column(db.Integer, nullable=True)  # seconds
    slow_mode = db.Column(db.Integer, default=0)  # seconds between messages (Telegram slow mode)
    linked_chat_id = db.Column(db.Integer, db.ForeignKey('chats.id', ondelete='SET NULL'), nullable=True)  # discussion group <-> channel
    no_forwards = db.Column(db.Boolean, default=False)  # protect content: block forwards
    hide_members = db.Column(db.Boolean, default=False)  # hide member list from non-admins

    __table_args__ = (
        db.CheckConstraint("chat_type IN ('personal', 'group', 'channel')"),
    )

    def __repr__(self):
        return f'<Chat(id={self.id}, type={self.chat_type!r}, name={self.name!r})>'


class ChatMember(db.Model):
    """Members of a group chat (or participants in personal chat)"""
    __tablename__ = 'chat_members'

    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chats.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    role = db.Column(db.String(20), default='member')  # 'owner', 'admin', 'member', 'participant'
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('chat_id', 'user_id', name='unique_chat_member'),)

    def __repr__(self):
        return f'<ChatMember(chat_id={self.chat_id}, user_id={self.user_id}, role={self.role!r})>'


class ChatSubscriber(db.Model):
    """Subscribers of a channel"""
    __tablename__ = 'chat_subscribers'

    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chats.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    subscribed_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('chat_id', 'user_id', name='unique_chat_subscriber'),)

    def __repr__(self):
        return f'<ChatSubscriber(chat_id={self.chat_id}, user_id={self.user_id})>'


class GroupPermission(db.Model):
    """Role-based permissions for groups (chat_type='group')"""
    __tablename__ = 'group_permissions'

    chat_id = db.Column(db.Integer, db.ForeignKey('chats.id', ondelete='CASCADE'), primary_key=True)
    role = db.Column(db.String(20), primary_key=True)  # 'owner', 'admin', 'member'
    can_send_messages = db.Column(db.Boolean, default=True)
    can_send_media = db.Column(db.Boolean, default=True)
    can_add_members = db.Column(db.Boolean, default=False)
    can_pin_messages = db.Column(db.Boolean, default=False)
    can_change_info = db.Column(db.Boolean, default=False)
    can_delete_messages = db.Column(db.Boolean, default=False)
    can_ban_users = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f'<GroupPermission(chat_id={self.chat_id}, role={self.role!r})>'


class ChannelAdmin(db.Model):
    """Channel admins with specific permissions (chat_type='channel')"""
    __tablename__ = 'channel_admins'

    chat_id = db.Column(db.Integer, db.ForeignKey('chats.id', ondelete='CASCADE'), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), primary_key=True)
    can_post = db.Column(db.Boolean, default=True)
    can_edit = db.Column(db.Boolean, default=False)
    can_delete = db.Column(db.Boolean, default=False)
    can_add_admins = db.Column(db.Boolean, default=False)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<ChannelAdmin(chat_id={self.chat_id}, user_id={self.user_id})>'


# ============ MESSAGE MODELS ============

class Message(db.Model):
    __tablename__ = 'message'

    id = db.Column(db.Integer, primary_key=True)
    _content = db.Column('content', db.Text, nullable=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chats.id', ondelete='CASCADE'), nullable=False, index=True)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=True, index=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    is_read = db.Column(db.Boolean, default=False)
    telegram_message_id = db.Column(db.String(50), nullable=True)
    is_from_telegram = db.Column(db.Boolean, default=False)
    delivered_at = db.Column(db.DateTime, nullable=True)
    read_at = db.Column(db.DateTime, nullable=True)
    is_saved = db.Column(db.Boolean, default=False)
    deleted_at = db.Column(db.DateTime, nullable=True)

    has_attachment = db.Column(db.Boolean, default=False)
    file_type = db.Column(db.String(20), nullable=True)
    file_name = db.Column(db.String(255), nullable=True)
    file_path = db.Column(db.String(500), nullable=True)
    file_size = db.Column(db.Integer, nullable=True)
    thumbnail_path = db.Column(db.String(500), nullable=True)

    is_encrypted = db.Column(db.Boolean, default=False)
    encrypted_content = db.Column(db.Text)
    encryption_key_id = db.Column(db.Integer)

    emoji = db.Column(db.String(16), nullable=True)
    emoji_file = db.Column(db.String(255), nullable=True)
    emoji_size = db.Column(db.Integer, default=96)
    emoji_count = db.Column(db.Integer, default=1)

    is_deleted = db.Column(db.Boolean, default=False)
    deleted_for_all = db.Column(db.Boolean, default=False)

    scheduled_at = db.Column(db.DateTime, nullable=True)

    edited_at = db.Column(db.DateTime, nullable=True)

    file_id = db.Column(db.Integer, db.ForeignKey('files.id', ondelete='SET NULL'), nullable=True)
    file = db.relationship('File', backref=db.backref('messages', lazy='dynamic'), lazy=True)

    reactions = db.relationship('Reaction', backref='message', lazy=True, cascade='all, delete-orphan')
    replies_to = db.relationship('Reply', foreign_keys='Reply.original_message_id', backref='original_message', lazy=True)
    reply_to = db.relationship('Reply', foreign_keys='Reply.reply_message_id', backref='reply_message', uselist=False, lazy=True)
    forwards_from = db.relationship('Forward', foreign_keys='Forward.original_message_id', backref='original_message', lazy=True)
    forwards_to = db.relationship('Forward', foreign_keys='Forward.forwarded_message_id', backref='forwarded_message', uselist=False, lazy=True)

    poll_id = db.Column(db.Integer, nullable=True)
    poll_question = db.Column(db.String(255), nullable=True)
    topic_id = db.Column(db.Integer, db.ForeignKey('tg_topic.id', ondelete='SET NULL'), nullable=True, index=True)  # forum topic/thread
    forwarded_from_id = db.Column(db.Integer, db.ForeignKey('message.id'), nullable=True)
    forwarded_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    @property
    def content(self):
        val = self._content
        if val and val.startswith('enc$'):
            try:
                from app.utils.crypto import decrypt_message
                return decrypt_message(val)
            except Exception:
                return val
        return val

    @content.setter
    def content(self, value):
        if value is not None and isinstance(value, str) and not value.startswith('enc$'):
            from app.utils.crypto import encrypt_message
            self._content = encrypt_message(value)
        else:
            self._content = value

    def __repr__(self):
        return f'<Message(id={self.id}, sender_id={self.sender_id}, chat_id={self.chat_id})>'


class File(db.Model):
    __tablename__ = 'files'
    id = db.Column(db.Integer, primary_key=True)
    file_type = db.Column(db.String(20), nullable=True)
    file_name = db.Column(db.String(255), nullable=True)
    file_path = db.Column(db.String(500), nullable=True)
    file_size = db.Column(db.Integer, nullable=True)
    thumbnail_path = db.Column(db.String(500), nullable=True)
    preview_size = db.Column(db.String(10), default='medium')
    uploader_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<File(id={self.id}, name={self.file_name!r}, type={self.file_type!r})>'


class Reaction(db.Model):
    __tablename__ = 'reaction'

    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('message.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    reaction_type = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('message_id', 'user_id', 'reaction_type', name='unique_user_message_reaction'),)

    def __repr__(self):
        return f'<Reaction(message_id={self.message_id}, user_id={self.user_id}, type={self.reaction_type!r})>'


class Reply(db.Model):
    __tablename__ = 'reply'

    id = db.Column(db.Integer, primary_key=True)
    original_message_id = db.Column(db.Integer, db.ForeignKey('message.id', ondelete='CASCADE'), nullable=False)
    reply_message_id = db.Column(db.Integer, db.ForeignKey('message.id', ondelete='CASCADE'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Reply(original={self.original_message_id}, reply={self.reply_message_id})>'


class Forward(db.Model):
    __tablename__ = 'forward'

    id = db.Column(db.Integer, primary_key=True)
    original_message_id = db.Column(db.Integer, db.ForeignKey('message.id', ondelete='CASCADE'), nullable=False)
    forwarded_message_id = db.Column(db.Integer, db.ForeignKey('message.id', ondelete='CASCADE'), nullable=False)
    forwarded_by_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    original_sender_name = db.Column(db.String(80), nullable=True)

    __table_args__ = (db.UniqueConstraint('original_message_id', 'forwarded_message_id', 'forwarded_by_id', name='unique_forward'),)

    def __repr__(self):
        return f'<Forward(original={self.original_message_id}, fwd={self.forwarded_message_id})>'


# ============ STORY MODELS ============

class Story(db.Model):
    __tablename__ = 'stories'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    media_path = db.Column(db.String(500), nullable=False)
    media_type = db.Column(db.String(20), default='image')
    caption = db.Column(db.Text)
    music_path = db.Column(db.String(500), nullable=True)
    privacy_type = db.Column(db.String(20), default='everyone')
    is_archived = db.Column(db.Boolean, default=False)  # older than 24h: hidden from feed, visible in archive
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    views = db.relationship('StoryView', backref='story', lazy='dynamic', cascade='all, delete-orphan')
    likes = db.relationship('StoryLike', backref='story', lazy='dynamic', cascade='all, delete-orphan')
    reactions = db.relationship('StoryReaction', backref='story', lazy='dynamic', cascade='all, delete-orphan')
    privacy_settings = db.relationship('StoryPrivacy', backref='story', uselist=False, cascade='all, delete-orphan')
    allowed_users = db.relationship('StoryAllowedUser', backref='story', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Story(id={self.id}, user_id={self.user_id}, type={self.media_type!r})>'


class StoryView(db.Model):
    __tablename__ = 'story_views'

    id = db.Column(db.Integer, primary_key=True)
    story_id = db.Column(db.Integer, db.ForeignKey('stories.id', ondelete='CASCADE'), nullable=False, index=True)
    viewer_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    viewed_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('story_id', 'viewer_id', name='unique_story_view'),)

    def __repr__(self):
        return f'<StoryView(story_id={self.story_id}, viewer_id={self.viewer_id})>'


class StoryLike(db.Model):
    __tablename__ = 'story_likes'

    id = db.Column(db.Integer, primary_key=True)
    story_id = db.Column(db.Integer, db.ForeignKey('stories.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('story_id', 'user_id', name='unique_story_like'),)

    def __repr__(self):
        return f'<StoryLike(story_id={self.story_id}, user_id={self.user_id})>'


class StoryReaction(db.Model):
    __tablename__ = 'story_reactions'

    id = db.Column(db.Integer, primary_key=True)
    story_id = db.Column(db.Integer, db.ForeignKey('stories.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    reaction = db.Column(db.String(10), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('story_id', 'user_id', name='unique_story_reaction'),)

    def __repr__(self):
        return f'<StoryReaction(story_id={self.story_id}, user_id={self.user_id}, reaction={self.reaction!r})>'


class StoryPrivacy(db.Model):
    __tablename__ = 'story_privacy'

    story_id = db.Column(db.Integer, db.ForeignKey('stories.id', ondelete='CASCADE'), primary_key=True)
    privacy_type = db.Column(db.String(20), default='everyone')

    def __repr__(self):
        return f'<StoryPrivacy(story_id={self.story_id})>'


class StoryAllowedUser(db.Model):
    __tablename__ = 'story_allowed_users'

    story_id = db.Column(db.Integer, db.ForeignKey('stories.id', ondelete='CASCADE'), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), primary_key=True)

    def __repr__(self):
        return f'<StoryAllowedUser(story_id={self.story_id}, user_id={self.user_id})>'


# ============ CONTACT MODELS ============

class Contact(db.Model):
    __tablename__ = 'contacts'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    contact_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    custom_name = db.Column(db.String(80), nullable=True)  # Property: a contact can have a name
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('user_id', 'contact_id', name='unique_contact'),)

    def __repr__(self):
        return f'<Contact(user_id={self.user_id}, contact_id={self.contact_id})>'


# ============ CALL MODELS ============

class Call(db.Model):
    __tablename__ = 'calls'

    id = db.Column(db.Integer, primary_key=True)
    caller_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    call_type = db.Column(db.String(10), default='audio')  # 'audio' or 'video'
    status = db.Column(db.String(20), default='ringing')   # ringing, answered, ended
    duration = db.Column(db.Integer, default=0)
    room_token = db.Column(db.String(100), nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)
    duration_seconds = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Call(id={self.id}, caller={self.caller_id}, receiver={self.receiver_id})>'


class VideoCall(db.Model):
    """Persistent record of a video room session"""
    __tablename__ = 'video_calls'

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.String(50), unique=True, nullable=False)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    chat_id = db.Column(db.Integer, db.ForeignKey('chats.id', ondelete='CASCADE'), nullable=True, index=True)  # group voice chat scope
    call_type = db.Column(db.String(10), default='video')
    status = db.Column(db.String(20), default='active')
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    ended_at = db.Column(db.DateTime, nullable=True)
    duration = db.Column(db.Integer, default=0)
    participant_count = db.Column(db.Integer, default=1)

    def __repr__(self):
        return f'<VideoCall(id={self.id}, room={self.room_id!r})>'


class VideoCallParticipant(db.Model):
    """Participants in a video call"""
    __tablename__ = 'video_call_participants'

    id = db.Column(db.Integer, primary_key=True)
    call_id = db.Column(db.Integer, db.ForeignKey('video_calls.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    left_at = db.Column(db.DateTime, nullable=True)
    audio_only = db.Column(db.Boolean, default=False)
    screensharing = db.Column(db.Boolean, default=False)

    __table_args__ = (db.UniqueConstraint('call_id', 'user_id', name='unique_call_participant'),)

    def __repr__(self):
        return f'<VideoCallParticipant(call_id={self.call_id}, user_id={self.user_id})>'


# ============ OTHER MODELS (USER PROPERTIES) ============

class BlockedUser(db.Model):
    __tablename__ = 'blocked_users'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    blocked_user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    blocked_user = db.relationship('User', foreign_keys=[blocked_user_id], backref='blocked_by')
    __table_args__ = (db.UniqueConstraint('user_id', 'blocked_user_id', name='unique_block'),)

    def __repr__(self):
        return f'<BlockedUser(user_id={self.user_id}, blocked={self.blocked_user_id})>'


class UserSession(db.Model):
    __tablename__ = 'user_sessions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    session_token = db.Column(db.String(255), unique=True, nullable=False)
    device = db.Column(db.String(200), nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_activity = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f'<UserSession(id={self.id}, user_id={self.user_id}, device={self.device!r})>'


class Report(db.Model):
    __tablename__ = 'reports'

    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    reported_user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    reported_message_id = db.Column(db.Integer, db.ForeignKey('message.id', ondelete='SET NULL'), nullable=True)
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='pending', index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    reported_message = db.relationship('Message', foreign_keys=[reported_message_id])

    def __repr__(self):
        return f'<Report(id={self.id}, reporter={self.reporter_id}, status={self.status!r})>'


class PushSubscription(db.Model):
    __tablename__ = 'push_subscriptions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    endpoint = db.Column(db.Text, nullable=False)
    p256dh = db.Column(db.Text, nullable=False)
    auth = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('user_id', 'endpoint', name='unique_user_endpoint'),)

    def __repr__(self):
        return f'<PushSubscription(id={self.id}, user_id={self.user_id})>'


class Favorite(db.Model):
    __tablename__ = 'favorites'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    file_type = db.Column(db.String(20), nullable=True)
    file_path = db.Column(db.String(500), nullable=True)
    file_name = db.Column(db.String(255), nullable=True)
    note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('user_id', 'file_path', name='unique_user_favorite'),)

    def __repr__(self):
        return f'<Favorite(id={self.id}, user_id={self.user_id})>'


class RecentSearch(db.Model):
    __tablename__ = 'recent_searches'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    search_query = db.Column(db.String(200), nullable=False)
    search_type = db.Column(db.String(20), default='all')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('user_id', 'search_query', name='unique_user_search'),)

    def __repr__(self):
        return f'<RecentSearch(id={self.id}, user_id={self.user_id}, query={self.search_query!r})>'


class PreloadedAvatar(db.Model):
    __tablename__ = 'preloaded_avatars'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(100), unique=True, nullable=False)
    display_name = db.Column(db.String(50))
    category = db.Column(db.String(20), default='default')

    def __repr__(self):
        return f'<PreloadedAvatar(id={self.id}, filename={self.filename!r})>'


class PinnedChat(db.Model):
    """Pinned chats for a user"""
    __tablename__ = 'pinned_chats'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    chat_type = db.Column(db.String(20), nullable=False)   # 'personal', 'group', 'channel'
    chat_id = db.Column(db.Integer, nullable=False)
    pinned_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('user_id', 'chat_type', 'chat_id', name='unique_pin'),)

    def __repr__(self):
        return f'<PinnedChat(user_id={self.user_id}, chat_type={self.chat_type!r}, chat_id={self.chat_id})>'


class EmailVerification(db.Model):
    __tablename__ = 'email_verifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=True)
    email = db.Column(db.String(128), nullable=True, index=True)
    token = db.Column(db.String(100), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    verified = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f'<EmailVerification(id={self.id}, email={self.email!r})>'


class UserMusic(db.Model):
    __tablename__ = 'user_music'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    file_url = db.Column(db.String(500), nullable=False)
    file_name = db.Column(db.String(255), nullable=True)
    artist = db.Column(db.String(255), nullable=True)
    title = db.Column(db.String(255), nullable=True)
    duration = db.Column(db.Integer, default=0)
    source_message_id = db.Column(db.Integer, db.ForeignKey('message.id', ondelete='SET NULL'), nullable=True)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('user_id', 'file_url', name='unique_user_music'),)

    def __repr__(self):
        return f'<UserMusic(id={self.id}, user_id={self.user_id}, title={self.title!r})>'


class UserKSettings(db.Model):
    """Per-user K SPA settings stored as JSON blob"""
    __tablename__ = 'user_k_settings'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, unique=True)
    settings = db.Column(db.JSON, default=dict)

    def to_dict(self):
        return {
            'user_id': self.user_id,
            'settings': self.settings or {}
        }

    def __repr__(self):
        return f'<UserKSettings(user_id={self.user_id})>'


class QrLoginToken(db.Model):
    __tablename__ = 'qr_login_tokens'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=True)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    consumed = db.Column(db.Boolean, default=False)
    consumed_at = db.Column(db.DateTime, nullable=True)
    authorized_by_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)

    user = db.relationship('User', backref='qr_login_tokens', lazy=True, foreign_keys=[user_id])
    authorized_by = db.relationship('User', backref='qr_authorized_tokens', lazy=True, foreign_keys=[authorized_by_id])

    def __repr__(self):
        return f'<QrLoginToken(id={self.id}, token={self.token!r})>'


class Referral(db.Model):
    __tablename__ = 'referrals'
    id = db.Column(db.Integer, primary_key=True)
    inviter_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    invited_user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    inviter = db.relationship('User', foreign_keys=[inviter_id], backref='referrals_made')
    invited = db.relationship('User', foreign_keys=[invited_user_id], backref='referral_invite')

    def __repr__(self):
        return f'<Referral(inviter={self.inviter_id}, invited={self.invited_user_id})>'


class LoginOtp(db.Model):
    __tablename__ = 'login_otps'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    code = db.Column(db.String(6), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)

    user = db.relationship('User', backref='login_otps', lazy=True)

    def __repr__(self):
        return f'<LoginOtp(id={self.id}, user_id={self.user_id}, used={self.used})>'


# ============ POLL MODELS ============

class Poll(db.Model):
    __tablename__ = 'poll'
    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.String(255), nullable=False)
    options = db.Column(db.JSON, nullable=False)
    is_multiple = db.Column(db.Boolean, default=False)
    is_anonymous = db.Column(db.Boolean, default=True)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    chat_type = db.Column(db.String(20), nullable=True)
    chat_id = db.Column(db.Integer, nullable=True)
    closed = db.Column(db.Boolean, default=False)
    quiz_answer = db.Column(db.Integer, nullable=True)  # correct option_index (Telegram quiz mode)
    quiz_explanation = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship('User', backref='polls', lazy=True)
    votes = db.relationship('PollVote', backref='poll', lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Poll(id={self.id}, question={self.question!r})>'


class PollVote(db.Model):
    __tablename__ = 'poll_vote'
    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey('poll.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    option_index = db.Column(db.Integer, nullable=False)
    voted_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('poll_id', 'user_id', 'option_index', name='unique_poll_vote'),)
    user = db.relationship('User', backref='poll_votes', lazy=True)


# ============ PINNED MESSAGES ============

class Pin(db.Model):
    __tablename__ = 'pin'
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('message.id', ondelete='CASCADE'), nullable=False)
    chat_type = db.Column(db.String(20), nullable=True)
    chat_id = db.Column(db.Integer, nullable=False)
    pinned_by = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    pinned_at = db.Column(db.DateTime, default=datetime.utcnow)

    message = db.relationship('Message', backref='pins', lazy=True)


# ============ INVITE LINKS ============

class InviteLink(db.Model):
    __tablename__ = 'invite_link'
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('chats.id', ondelete='CASCADE'), nullable=False)
    code = db.Column(db.String(64), unique=True, nullable=False)
    link = db.Column(db.String(255), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    uses = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship('User', backref='invite_links', lazy=True)


class SavedMessage(db.Model):
    __tablename__ = 'saved_message'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    message_id = db.Column(db.Integer, db.ForeignKey('message.id', ondelete='CASCADE'), nullable=False)
    tag = db.Column(db.String(40), nullable=True, index=True)  # premium-style saved tags
    saved_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('user_id', 'message_id', name='unique_saved_msg'),)


class Archive(db.Model):
    __tablename__ = 'chat_archive'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chats.id', ondelete='CASCADE'), nullable=False)
    archived_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('user_id', 'chat_id', name='unique_archive_entry'),)


# --- Sputnik ideas pack (ported from ilyyagoncharow12/sputnik) ---
# Small additive tables only; no changes to existing tables.


class SputnikMessageEdit(db.Model):
    """Edit history: old -> new text with editor + timestamp (Sputnik idea)."""

    __tablename__ = 'sputnik_message_edit'
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('message.id', ondelete='CASCADE'), nullable=False, index=True)
    editor_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    old_text = db.Column(db.Text, nullable=True)
    new_text = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class SputnikTrash(db.Model):
    """Message-level trash bin: soft-deleted snapshot restorable by owner."""

    __tablename__ = 'sputnik_trash'
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, nullable=False, index=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    snapshot = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (db.UniqueConstraint('message_id', 'owner_id', name='unique_sputnik_trash'),)


class SputnikFolder(db.Model):
    """Chat folder (pairs of chat_type + chat_id, Sputnik-style)."""

    __tablename__ = 'sputnik_folder'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SputnikFolderChat(db.Model):
    __tablename__ = 'sputnik_folder_chat'
    id = db.Column(db.Integer, primary_key=True)
    folder_id = db.Column(db.Integer, db.ForeignKey('sputnik_folder.id', ondelete='CASCADE'), nullable=False, index=True)
    chat_type = db.Column(db.String(20), nullable=False, default='personal')
    chat_id = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('folder_id', 'chat_type', 'chat_id', name='unique_sputnik_folder_chat'),)


class SputnikSticker(db.Model):
    """Custom user sticker built from an uploaded image (Sputnik idea)."""

    __tablename__ = 'sputnik_sticker'
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    file_path = db.Column(db.String(500), nullable=False)
    emoji = db.Column(db.String(16), nullable=True)
    is_favorite = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class SputnikAlbum(db.Model):
    """Album groups several messages into one gallery item (Sputnik idea)."""

    __tablename__ = 'sputnik_album'
    id = db.Column(db.Integer, primary_key=True)
    album_uid = db.Column(db.String(64), nullable=False, index=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    message_id = db.Column(db.Integer, db.ForeignKey('message.id', ondelete='CASCADE'), nullable=False, index=True)
    position = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('album_uid', 'message_id', name='unique_sputnik_album_item'),)


class SputnikMessageView(db.Model):
    """Deduped per-user message/channel views (Sputnik: one view per user)."""

    __tablename__ = 'sputnik_message_view'
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('message.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('message_id', 'user_id', name='unique_sputnik_view'),)


class SputnikSecret(db.Model):
    """User cloud (2FA) password + app-lock PIN hashes (bcrypt, Sputnik idea)."""

    __tablename__ = 'sputnik_secret'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    kind = db.Column(db.String(20), nullable=False, default='cloud')
    secret_hash = db.Column(db.String(255), nullable=False)
    hint = db.Column(db.String(255), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('user_id', 'kind', name='unique_sputnik_secret'),)


class SputnikDraft(db.Model):
    """Unsent composer text per (chat_type, chat_id) — Sputnik drafts idea."""

    __tablename__ = 'sputnik_draft'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    chat_type = db.Column(db.String(20), nullable=False, default='personal')
    chat_id = db.Column(db.Integer, nullable=False)
    text = db.Column(db.Text, nullable=True)
    reply_to_id = db.Column(db.Integer, db.ForeignKey('message.id', ondelete='SET NULL'), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    __table_args__ = (db.UniqueConstraint('user_id', 'chat_type', 'chat_id', name='unique_sputnik_draft'),)


class SputnikJoinRequest(db.Model):
    """Join requests for private groups (Sputnik showcase idea)."""

    __tablename__ = 'sputnik_join_request'
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chats.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    status = db.Column(db.String(20), default='pending', index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('chat_id', 'user_id', name='unique_sputnik_join_req'),)


class SputnikMemberPerm(db.Model):
    """Per-member permission overrides in groups (Sputnik idea)."""

    __tablename__ = 'sputnik_member_perm'
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chats.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    perms = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('chat_id', 'user_id', name='unique_sputnik_member_perm'),)


class SputnikGroupRestrict(db.Model):
    """Group bans / mutes with optional expiry (Sputnik idea)."""

    __tablename__ = 'sputnik_group_restrict'
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chats.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    kind = db.Column(db.String(10), nullable=False, default='ban', index=True)
    reason = db.Column(db.String(255), nullable=True)
    until = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('chat_id', 'user_id', 'kind', name='unique_sputnik_restrict'),)


# --- Telegram parity pack (forum topics, live geo, bot commands) ---


class TgTopic(db.Model):
    """Forum topic/thread inside a group (Telegram Topics idea)."""

    __tablename__ = 'tg_topic'
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chats.id', ondelete='CASCADE'), nullable=False, index=True)
    title = db.Column(db.String(80), nullable=False)
    icon = db.Column(db.String(16), nullable=True)
    is_closed = db.Column(db.Boolean, default=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    messages = db.relationship('Message', backref='topic', lazy='dynamic')


class TgLiveLocation(db.Model):
    """Live location share session (Telegram live location idea)."""

    __tablename__ = 'tg_live_location'
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('message.id', ondelete='CASCADE'), nullable=False, unique=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chats.id', ondelete='CASCADE'), nullable=False, index=True)
    lat = db.Column(db.Float, nullable=False)
    lon = db.Column(db.Float, nullable=False)
    until = db.Column(db.DateTime, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TgBotCommand(db.Model):
    """Bot command menu entries (Telegram Bot API setMyCommands idea)."""

    __tablename__ = 'tg_bot_command'
    id = db.Column(db.Integer, primary_key=True)
    bot_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    command = db.Column(db.String(32), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('bot_id', 'command', name='unique_tg_bot_cmd'),)


class TgCollectible(db.Model):
    """Ownable username (Telegram Fragment-style collectible, off-chain).

    Invariant: a collectible name is never equal to any User.username.
    Wearing swaps names so the invariant always holds.
    """

    __tablename__ = 'tg_collectible'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(32), unique=True, nullable=False, index=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    price = db.Column(db.Integer, nullable=True)  # ask price in Stars (informational; transfers are the primitive)
    for_sale = db.Column(db.Boolean, default=False, index=True)
    last_sale_price = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AdminAction(db.Model):
    """Audit log of admin actions (extras_2)."""

    __tablename__ = 'admin_action'

    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True, index=True)
    action = db.Column(db.String(64), nullable=False, index=True)
    target_type = db.Column(db.String(32), nullable=True, index=True)
    target_id = db.Column(db.Integer, nullable=True, index=True)
    details = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    actor = db.relationship('User', foreign_keys=[actor_id])

    def __repr__(self):
        return f'<AdminAction(id={self.id}, action={self.action!r})>'


class UserNote(db.Model):
    """Admin-only note attached to a user (extras_2)."""

    __tablename__ = 'user_note'

    id = db.Column(db.Integer, primary_key=True)
    target_user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True, index=True)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    target = db.relationship('User', foreign_keys=[target_user_id], backref='admin_notes')
    author = db.relationship('User', foreign_keys=[author_id])

    def __repr__(self):
        return f'<UserNote(id={self.id}, target={self.target_user_id})>'
