# Update utils/helpers.py

from werkzeug.security import generate_password_hash
import secrets
import os
import re
import json
from datetime import datetime, timedelta
from PIL import Image
from app.models import Story, BlockedUser, ChatMember, Message, Forward, Reply, Reaction


def hash_password(password):
    return generate_password_hash(password)


def get_current_user():
    from flask import session, request
    from app.models import User, UserSession

    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        token = auth[7:]
        us = UserSession.query.filter_by(session_token=token, is_active=True).first()
        if us:
            return User.query.get(us.user_id)

    user_id = session.get('user_id')
    if user_id:
        return User.query.get(user_id)
    return None


def presence_visible(viewer_id, target_user):
    """Sputnik-style presence privacy: honor target's privacy_last_seen.

    'everyone' -> visible; 'nobody' -> hidden; 'contacts' (default) ->
    visible only if viewer is in target's contacts. Own presence always visible.
    """
    if target_user is None:
        return False
    if viewer_id is not None and viewer_id == target_user.id:
        return True
    policy = getattr(target_user, 'privacy_last_seen', 'everyone') or 'everyone'
    if policy == 'everyone':
        return True
    if policy == 'nobody':
        return False
    from app.models import Contact
    try:
        return Contact.query.filter_by(user_id=target_user.id, contact_id=viewer_id).first() is not None
    except Exception:
        return False


def get_current_user_id():
    from flask import session, request
    from app.models import UserSession

    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        token = auth[7:]
        us = UserSession.query.filter_by(session_token=token, is_active=True).first()
        if us:
            return us.user_id

    user_id = session.get('user_id')
    if user_id:
        return user_id
    return None


def generate_invite_link():
    return secrets.token_urlsafe(16)


def format_file_size(size_bytes):
    """Convert bytes to human readable format"""
    if size_bytes == 0:
        return "0 B"

    size_names = ["B", "KB", "MB", "GB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1

    return f"{size_bytes:.1f} {size_names[i]}"


def format_timestamp(dt):
    """Format datetime for display"""
    if not dt:
        return ''

    now = datetime.utcnow()
    diff = now - dt

    if diff.days == 0:
        return dt.strftime('%H:%M')
    elif diff.days == 1:
        return 'Yesterday'
    elif diff.days < 7:
        return dt.strftime('%A')
    else:
        return dt.strftime('%d.%m.%Y')


def highlight_text(text, query):
    if not text or not query:
        return text
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    return pattern.sub(lambda m: f'<span class="highlight">{m.group()}</span>', str(text))


def allowed_file(filename, allowed_extensions=None):
    """Check if file extension is allowed"""
    if '.' not in filename:
        return False

    ext = filename.rsplit('.', 1)[1].lower()

    if allowed_extensions is None:
        allowed_extensions = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'pdf', 'doc', 'docx', 'txt', 'mp3', 'mp4', 'zip'}

    return ext in allowed_extensions


def get_file_type(filename):
    """Determine file type from extension"""
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''

    image_extensions = {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp'}
    audio_extensions = {'mp3', 'wav', 'ogg', 'm4a'}
    video_extensions = {'mp4', 'avi', 'mov', 'mkv', 'webm'}
    document_extensions = {'pdf', 'doc', 'docx', 'txt', 'rtf'}
    archive_extensions = {'zip', 'rar', '7z'}

    if ext in image_extensions:
        return 'image'
    elif ext in audio_extensions:
        return 'audio'
    elif ext in video_extensions:
        return 'video'
    elif ext in document_extensions:
        return 'document'
    elif ext in archive_extensions:
        return 'archive'
    else:
        return 'other'


def create_thumbnail(image_path, thumbnail_path, size=(200, 200)):
    """Create thumbnail for images"""
    try:
        with Image.open(image_path) as img:
            img.thumbnail(size)
            img.save(thumbnail_path, 'JPEG' if thumbnail_path.lower().endswith('.jpg') else 'PNG')
        return True
    except Exception as e:
        print(f"Thumbnail creation failed: {e}")
        return False




def get_blocked_user_ids(user_id):
    try:
        blocks = BlockedUser.query.filter_by(user_id=user_id).all()
        return [b.blocked_user_id for b in blocks]
    except Exception:
        return []


_EMOJI_MANIFEST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'static', 'stickers', '_manifest.json',
)
_EMOJI_PACK = 'animatedemojies'
_EMOJI_FILE_MAX = 128
_ANIMATED_EMOJI_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'uploads', 'animated_emojis',
)


def get_animated_emojis():
    """Return list of {file, emoji} from server storage, fallback to manifest."""
    # Check server storage first (uploads/animated_emojis)
    try:
        if os.path.isdir(_ANIMATED_EMOJI_DIR):
            files = [f for f in os.listdir(_ANIMATED_EMOJI_DIR) if re.fullmatch(r'[A-Za-z0-9_]+\.(webp|tgs|gif)', f)]
            if files:
                try:
                    with open(_EMOJI_MANIFEST_PATH, 'r', encoding='utf-8') as fh:
                        manifest = json.load(fh)
                    stickers = manifest.get(_EMOJI_PACK, {}).get('stickers', [])
                    emoji_map = {s['file']: s.get('emoji', '') for s in stickers}
                except (OSError, ValueError, KeyError):
                    emoji_map = {}
                return [{'file': f, 'emoji': emoji_map.get(f, '')} for f in sorted(files)]
    except Exception:
        pass
    try:
        with open(_EMOJI_MANIFEST_PATH, 'r', encoding='utf-8') as fh:
            manifest = json.load(fh)
        stickers = manifest.get(_EMOJI_PACK, {}).get('stickers', [])
        return [{'file': s['file'], 'emoji': s.get('emoji', '')} for s in stickers if s.get('file')]
    except (OSError, ValueError, KeyError):
        return []


def validate_emoji(emoji_file, emoji='', size=96, count=1):
    """Validate an animated emoji message payload against the manifest.

    Returns (emoji_data|None, error_message|None).
    """
    if not emoji_file or not isinstance(emoji_file, str):
        return None, 'emoji_file is required'
    if len(emoji_file) > _EMOJI_FILE_MAX:
        return None, 'emoji_file too long'
    file_name = os.path.basename(emoji_file)
    if file_name != emoji_file or not re.fullmatch(r'[A-Za-z0-9_]+\.(webp|tgs|gif)', file_name):
        return None, 'invalid emoji_file'
    try:
        size = int(size)
        count = int(count)
    except (TypeError, ValueError):
        return None, 'invalid emoji size/count'
    if not 16 <= size <= 512:
        return None, 'emoji size out of range'
    if not 1 <= count <= 100:
        return None, 'emoji count out of range'

    # Check server storage first
    server_path = os.path.join(_ANIMATED_EMOJI_DIR, file_name)
    if os.path.isfile(server_path):
        return {'file': file_name, 'emoji': emoji[:16] or '', 'size': size, 'count': count}, None
    manifest_files = {s.get('file') for s in get_animated_emojis()}
    if file_name not in manifest_files:
        return None, 'emoji_file not found in manifest'
    return {'file': file_name, 'emoji': emoji[:16] or '', 'size': size, 'count': count}, None

def get_animated_file_for_emoji(emoji_char):
    """Return animated file for a unicode emoji, or None."""
    if not emoji_char or not isinstance(emoji_char, str):
        return None
    emoji_char = emoji_char.strip()
    if not emoji_char:
        return None
    for item in get_animated_emojis():
        if item.get('emoji') == emoji_char:
            return item.get('file')
    stripped = emoji_char.replace('\ufe0f', '')
    if stripped != emoji_char:
        for item in get_animated_emojis():
            if item.get('emoji') == stripped or item.get('emoji', '').replace('\ufe0f', '') == stripped:
                return item.get('file')
    return None

def has_active_story(user_id):
    try:
        cutoff = datetime.utcnow() - timedelta(hours=24)
        return Story.query.filter(
            Story.user_id == user_id,
            Story.created_at >= cutoff
        ).count() > 0
    except Exception:
        return False

def user_to_dict(user):
    is_premium = (user.premium and user.premium.is_premium) or False
    return {
        'id': user.id,
        'username': user.username,
        'display_name': user.display_name or user.username,
        'bio': user.bio,
        'avatar_url': user.avatar_url,
        'is_online': getattr(user, 'is_online', False),
        'last_seen': user.last_seen.isoformat() if user.last_seen else None,
        'created_at': user.created_at.isoformat() if user.created_at else None,
        'has_story': has_active_story(user.id),
        'is_premium': is_premium,
        'status_emoji': user.status_emoji or ('\u2b50' if is_premium else ''),
        'followers_count': 0,
        'following_count': 0,
        'groups_count': ChatMember.query.filter_by(user_id=user.id).count()
    }

def message_to_dict(message, current_user_id):
    msg_data = {
        'id': message.id,
        'content': message.content,
        'sender_id': message.sender_id,
        'receiver_id': message.receiver_id,
        'chat_id': message.chat_id,
        'sender_name': message.sender.username if message.sender else 'Unknown',
        'timestamp': message.timestamp.isoformat() if message.timestamp else None,
        'timestamp_formatted': message.timestamp.strftime('%H:%M') if message.timestamp else '',
        'is_own': message.sender_id == current_user_id,
        'is_read': message.is_read,
        'has_attachment': message.has_attachment,
        'reply_to_id': None,
        'reply_to_content': None,
        'reply_to_sender': None,
        'forwarded_from': None,
        'emoji': message.emoji,
        'emoji_file': message.emoji_file,
        'emoji_url': f"/uploads/animated_emojis/{message.emoji_file}" if message.emoji_file else None,
        'emoji_size': message.emoji_size or 96,
        'emoji_count': message.emoji_count or 1,
        'reactions': {}
    }

    if message.has_attachment:
        file = message.file
        msg_data['file_type'] = file.file_type if file else message.file_type
        msg_data['file_name'] = file.file_name if file else message.file_name
        msg_data['file_size'] = file.file_size if file else message.file_size
        msg_data['formatted_size'] = format_file_size(msg_data['file_size']) if msg_data['file_size'] else '0 B'
        msg_data['file_url'] = f"/uploads/{file.file_path if file else message.file_path}" if (file or message.file_path) else None
        msg_data['preview_size'] = file.preview_size if file else (
            'big' if message.file_type == 'image'
            else 'medium' if message.file_type in ('video',)
            else 'none'
        )

    reply = Reply.query.filter_by(reply_message_id=message.id).first()
    if reply:
        original = Message.query.get(reply.original_message_id)
        if original:
            msg_data['reply_to_id'] = original.id
            msg_data['reply_to_content'] = original.content[:50] if original.content else ''
            msg_data['reply_to_sender'] = original.sender.username if original.sender else ''

    forward = Forward.query.filter_by(forwarded_message_id=message.id).first()
    if forward:
        msg_data['forwarded_from'] = forward.original_sender_name

    reactions = Reaction.query.filter_by(message_id=message.id).all()
    for r in reactions:
        if r.reaction_type not in msg_data['reactions']:
            msg_data['reactions'][r.reaction_type] = 0
        msg_data['reactions'][r.reaction_type] += 1

    return msg_data