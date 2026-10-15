from flask import Blueprint, request, jsonify, send_file, url_for, session, current_app
import os
import uuid
import mimetypes
from datetime import datetime

from app import db
from app.models import User, Message, Chat, ChatMember, ChatSubscriber, File
from app.utils.logging_utils import log_main
from app.utils.helpers import get_current_user_id
from app.utils.security import rate_limit

files_bp = Blueprint('files', __name__)

class Logger:
    @staticmethod
    def info(*message):
        return log_main('info', str(format(message)), 'files')

    @staticmethod
    def warning(*message):
        return log_main('warning', str(format(message)), 'files')

    @staticmethod
    def exception(*message):
        return log_main('exception', str(format(message)), 'files')


main_logger = Logger()


def _get_config_extensions(key, default):
    """Helper: read extension list from app config, stripping leading dots"""
    raw = current_app.config.get(key, default)
    return {e.lstrip('.').lower() for e in raw}


def allowed_file(filename):
    """Check if file extension is allowed (reads ALLOWED_* from config/kis.toml)"""
    if '.' not in filename:
        return False

    ext = filename.rsplit('.', 1)[1].lower()

    allowed = (
        _get_config_extensions('ALLOWED_IMAGES', ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'])
        | _get_config_extensions('ALLOWED_DOCUMENTS', ['.pdf', '.doc', '.docx', '.txt', '.rtf'])
        | _get_config_extensions('ALLOWED_VIDEOS', ['.mp4', '.avi', '.mov', '.mkv', '.webm'])
        | {'webp', 'rtf', 'zip', 'rar', '7z', 'mp3', 'wav', 'ogg', 'm4a'}
    )

    return ext in allowed


def get_file_type(filename):
    """Determine file type based on extension (reads ALLOWED_* from config/kis.toml)"""
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''

    image_extensions = _get_config_extensions('ALLOWED_IMAGES', ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'])
    audio_extensions = {'mp3', 'wav', 'ogg', 'm4a'}
    video_extensions = _get_config_extensions('ALLOWED_VIDEOS', ['.mp4', '.avi', '.mov', '.mkv', '.webm'])
    document_extensions = _get_config_extensions('ALLOWED_DOCUMENTS', ['.pdf', '.doc', '.docx', '.txt', '.rtf'])
    archive_extensions = {'zip', 'rar', '7z'}

    if ext in image_extensions:
        return 'image'
    if ext in audio_extensions:
        return 'audio'
    if ext in video_extensions:
        return 'video'
    if ext in document_extensions:
        return 'document'
    if ext in archive_extensions:
        return 'archive'
    return 'other'


def format_file_size(bytes_count):
    """Format file size in human readable format"""
    if bytes_count == 0:
        return '0 B'

    size_names = ['B', 'KB', 'MB', 'GB']
    i = 0
    while bytes_count >= 1024 and i < len(size_names) - 1:
        bytes_count /= 1024
        i += 1

    return f"{bytes_count:.1f} {size_names[i]}"


def get_uploads_dir():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(current_dir))
    return os.path.join(project_root, 'uploads')


def safe_path_in_uploads(*parts):
    uploads_dir = get_uploads_dir()
    path = os.path.normpath(os.path.join(uploads_dir, *parts))
    # exact dir or strictly inside it (prefix match alone would allow
    # a sibling like uploads_evil/ — Sputnik path-traversal class fix)
    if path != uploads_dir and not path.startswith(uploads_dir + os.sep):
        return None
    return path


@files_bp.route('/uploads/<path:filename>')
def serve_file(filename):
    """Serve uploaded files"""
    try:
        base_upload_dir = get_uploads_dir()
        file_path = safe_path_in_uploads(filename)
        if not file_path:
            main_logger.warning("Blocked invalid file path: %s", filename)
            return "Invalid file path", 403

        if os.path.exists(file_path) and os.path.isfile(file_path):
            mimetype, _ = mimetypes.guess_type(filename)
            main_logger.info("Serving file: %s", file_path)
            return send_file(file_path, mimetype=mimetype)

        base_filename = os.path.basename(filename)
        alternative_paths = [
            safe_path_in_uploads('images', base_filename),
            safe_path_in_uploads('documents', base_filename),
            safe_path_in_uploads('media', base_filename),
            safe_path_in_uploads('stories', base_filename),
            safe_path_in_uploads(base_filename),
        ]

        for alt_path in alternative_paths:
            if alt_path and os.path.exists(alt_path) and os.path.isfile(alt_path):
                mimetype, _ = mimetypes.guess_type(base_filename)
                main_logger.info("Serving fallback file: %s", alt_path)
                return send_file(alt_path, mimetype=mimetype)

        main_logger.warning("File not found: %s", filename)
        return "File not found", 404

    except Exception as e:
        main_logger.exception("Error serving file %s: %s", filename, e)
        return str(e), 500


@files_bp.route('/uploads/avatars/<path:filename>')
def serve_avatar(filename):
    """Serve uploaded avatar files"""
    try:
        base_upload_dir = get_uploads_dir()
        file_path = safe_path_in_uploads(filename)
        if not file_path:
            main_logger.warning("Blocked invalid avatar path: %s", filename)
            return "Invalid file path", 403

        if os.path.exists(file_path) and os.path.isfile(file_path):
            mimetype, _ = mimetypes.guess_type(filename)
            main_logger.info("Serving avatar: %s", file_path)
            return send_file(file_path, mimetype=mimetype)

        base_filename = os.path.basename(filename)
        alternative_paths = [
            safe_path_in_uploads('images', base_filename),
            safe_path_in_uploads('documents', base_filename),
            safe_path_in_uploads('media', base_filename),
            safe_path_in_uploads('stories', base_filename),
            safe_path_in_uploads('avatars', base_filename),
            safe_path_in_uploads(base_filename),
        ]

        for alt_path in alternative_paths:
            if alt_path and os.path.exists(alt_path) and os.path.isfile(alt_path):
                mimetype, _ = mimetypes.guess_type(base_filename)
                main_logger.info("Serving avatar fallback: %s", alt_path)
                return send_file(alt_path, mimetype=mimetype)

        main_logger.warning("Avatar not found: %s", filename)
        return "File not found", 404

    except Exception as e:
        main_logger.exception("Error serving avatar %s: %s", filename, e)
        return str(e), 500


@files_bp.route('/files/upload_file', methods=['POST'])
@rate_limit('upload_file', max_requests=30, window=60)
def upload_file():
    """Handle file uploads for personal chats, groups, and channels"""
    user_id = get_current_user_id() or session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    current_user = User.query.get(user_id)
    if not current_user:
        return jsonify({'success': False, 'error': 'User not found'}), 401

    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file provided'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400

    if not allowed_file(file.filename):
        return jsonify({'success': False, 'error': 'File type not allowed'}), 400

    receiver_id = request.form.get('receiver_id')
    group_id = request.form.get('group_id')
    channel_id = request.form.get('channel_id')
    message_text = request.form.get('message', '')

    if not receiver_id and not group_id and not channel_id:
        return jsonify({'success': False, 'error': 'No receiver, group, or channel specified'}), 400

    try:
        if receiver_id:
            receiver = User.query.get(receiver_id)
            if not receiver:
                return jsonify({'success': False, 'error': 'Receiver not found'}), 404
            from app.models import BlockedUser
            if BlockedUser.query.filter_by(user_id=receiver_id, blocked_user_id=user_id).first():
                return jsonify({'success': False, 'error': 'You are blocked by this user'}), 403

        elif group_id:
            chat = Chat.query.get(group_id)
            if not chat:
                return jsonify({'success': False, 'error': 'Group not found'}), 404
            membership = ChatMember.query.filter_by(user_id=user_id, chat_id=group_id).first()
            if not membership:
                return jsonify({'success': False, 'error': 'You are not a member of this group'}), 403

        elif channel_id:
            chat = Chat.query.get(channel_id)
            if not chat:
                return jsonify({'success': False, 'error': 'Channel not found'}), 404
            if chat.owner_id != user_id:
                return jsonify({'success': False, 'error': 'Only channel owner can post'}), 403

        file_ext = file.filename.rsplit('.', 1)[1].lower()
        unique_filename = f"{uuid.uuid4().hex}.{file_ext}"
        file_type = get_file_type(file.filename)

        if file_type == 'image':
            upload_dir = 'images'
        elif file_type in ['audio', 'video']:
            upload_dir = 'media'
        else:
            upload_dir = 'documents'

        file_path_with_dir = os.path.join(upload_dir, unique_filename)
        full_save_path = safe_path_in_uploads(file_path_with_dir)

        if not full_save_path:
            return jsonify({'success': False, 'error': 'Invalid save path'}), 400

        os.makedirs(os.path.dirname(full_save_path), exist_ok=True)
        file.save(full_save_path)

        file_size = os.path.getsize(full_save_path)
        file_url = url_for('files.serve_file', filename=file_path_with_dir, _external=False)

        new_file = File(
            file_type=file_type,
            file_name=file.filename,
            file_path=file_path_with_dir,
            file_size=file_size,
            preview_size='big' if file_type == 'image' else 'medium' if file_type in ('video',) else 'none',
            uploader_id=user_id,
        )
        db.session.add(new_file)
        db.session.flush()

        new_message = Message(
            sender_id=current_user.id,
            content=message_text,
            has_attachment=True,
            file_name=file.filename,
            file_path=file_path_with_dir,
            file_type=file_type,
            file_size=file_size,
            file_id=new_file.id,
            timestamp=datetime.utcnow(),
            is_read=False
        )

        if receiver_id:
            new_message.receiver_id = int(receiver_id)
            a, b = sorted([user_id, int(receiver_id)])
            chat = Chat.query.filter_by(chat_type='personal', user1_id=a, user2_id=b).first()
            if not chat:
                chat = Chat(chat_type='personal', user1_id=a, user2_id=b)
                db.session.add(chat)
                db.session.flush()
            new_message.chat_id = chat.id
        elif group_id:
            new_message.chat_id = int(group_id)
            new_message.receiver_id = current_user.id
        elif channel_id:
            new_message.chat_id = int(channel_id)
            new_message.receiver_id = current_user.id

        db.session.add(new_message)
        db.session.commit()

        return jsonify({
            'success': True,
            'filename': unique_filename,
            'url': file_url,
            'message': {
                'id': new_message.id,
                'content': message_text,
                'sender_id': current_user.id,
                'sender_name': current_user.username,
                'timestamp': new_message.timestamp.isoformat(),
                'timestamp_formatted': new_message.timestamp.strftime('%H:%M'),
                'is_own': True,
                'is_read': False,
                'has_attachment': True,
                'file_name': file.filename,
                'file_url': file_url,
                'file_type': file_type,
                'file_size': file_size,
                'formatted_size': format_file_size(file_size),
                'preview_size': new_file.preview_size,
            }
        })

    except Exception as e:
        main_logger.exception("Upload error: %s", e)
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@files_bp.route('/files/upload_avatar', methods=['POST'])
@rate_limit('upload_avatar', max_requests=5, window=120)
def upload_avatar():
    """Handle avatar upload for user profile"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    current_user = User.query.get(user_id)
    if not current_user:
        return jsonify({'success': False, 'error': 'User not found'}), 401

    if 'avatar' not in request.files:
        return jsonify({'success': False, 'error': 'No file provided'}), 400

    file = request.files['avatar']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400

    allowed_image_types = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
    file_ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''

    if file_ext not in allowed_image_types:
        return jsonify({'success': False, 'error': 'Invalid image format'}), 400

    try:
        from PIL import Image

        image = Image.open(file)

        if image.mode in ('RGBA', 'P'):
            rgb_image = Image.new('RGB', image.size, (255, 255, 255))
            rgb_image.paste(image, mask=image.split()[-1] if image.mode == 'RGBA' else None)
            image = rgb_image

        image.thumbnail((400, 400), Image.Resampling.LANCZOS)

        unique_filename = f"avatar_{uuid.uuid4().hex}.jpg"
        base_upload_dir = get_uploads_dir()
        avatars_dir = os.path.join(base_upload_dir, 'avatars')
        os.makedirs(avatars_dir, exist_ok=True)

        file_path = os.path.join(avatars_dir, unique_filename)
        relative_path = os.path.join('avatars', unique_filename)

        image.save(file_path, 'JPEG', quality=85)

        if current_user.avatar_url:
            old_avatar_path = safe_path_in_uploads(current_user.avatar_url.replace('/uploads/', ''))
            if old_avatar_path and os.path.exists(old_avatar_path):
                os.remove(old_avatar_path)

        current_user.avatar_url = f"/uploads/{relative_path}"
        db.session.commit()

        return jsonify({
            'success': True,
            'avatar_url': current_user.avatar_url,
            'message': 'Avatar updated successfully'
        })

    except Exception as e:
        main_logger.exception("Avatar upload error: %s", e)
        return jsonify({'success': False, 'error': str(e)}), 500


@files_bp.route('/files/upload_story', methods=['POST'])
@rate_limit('upload_story', max_requests=10, window=60)
def upload_story():
    """Upload a story media file"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    if 'media' not in request.files:
        return jsonify({'success': False, 'error': 'No media provided'}), 400

    file = request.files['media']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400

    file_ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''

    if file_ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
        media_type = 'image'
    elif file_ext in ['mp4', 'mov', 'avi', 'webm']:
        media_type = 'video'
    else:
        return jsonify({'success': False, 'error': 'Unsupported media type'}), 400

    try:
        unique_filename = f"story_{uuid.uuid4().hex}.{file_ext}"
        base_upload_dir = get_uploads_dir()
        stories_dir = os.path.join(base_upload_dir, 'stories')
        os.makedirs(stories_dir, exist_ok=True)

        file_path = os.path.join(stories_dir, unique_filename)
        relative_path = os.path.join('stories', unique_filename)

        file.save(file_path)

        from app.models import Story
        new_story = Story(
            user_id=user_id,
            media_path=relative_path,
            media_type=media_type,
            caption=request.form.get('caption', '')
        )
        db.session.add(new_story)
        db.session.commit()

        return jsonify({
            'success': True,
            'story': {
                'id': new_story.id,
                'media_url': f"/uploads/{relative_path}",
                'media_type': media_type
            }
        })

    except Exception as e:
        main_logger.exception("Story upload error: %s", e)
        return jsonify({'success': False, 'error': str(e)}), 500


@files_bp.route('/files/delete_file/<int:message_id>', methods=['DELETE'])
def delete_file(message_id):
    """Delete a file message"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    message = Message.query.get_or_404(message_id)

    if message.sender_id != user_id:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403

    try:
        if message.file_path:
            file_path = safe_path_in_uploads(message.file_path)
            if file_path and os.path.exists(file_path):
                os.remove(file_path)

        db.session.delete(message)
        db.session.commit()

        return jsonify({'success': True, 'message': 'File deleted'})

    except Exception as e:
        main_logger.exception("Delete error: %s", e)
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500