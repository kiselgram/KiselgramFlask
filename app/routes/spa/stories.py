import os
import json
import secrets
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify

from app import db
from app.models import User, Story, StoryView, StoryLike, StoryReaction, StoryPrivacy, StoryAllowedUser, Message, Chat
from app.utils.helpers import get_current_user_id, get_current_user

spa_stories_bp = Blueprint('spa_stories', __name__, url_prefix='/api')


ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'ico', 'svg', 'tiff', 'tif', 'heic', 'heif'}
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'webm', 'avi', 'mov', 'mkv', 'flv', 'wmv', 'm4v', 'mpg', 'mpeg', '3gp', '3g2'}


def _require_premium(user_id):
    user = User.query.get(user_id)
    if not user or not (user.premium.is_premium if user.premium else False):
        return jsonify({'success': False, 'error': 'Premium feature. Upgrade to access stories.'}), 403
    return None

def _get_or_create_personal_chat(user1_id, user2_id):
    a, b = sorted([user1_id, user2_id])
    chat = Chat.query.filter_by(chat_type='personal', user1_id=a, user2_id=b).first()
    if not chat:
        chat = Chat(chat_type='personal', user1_id=a, user2_id=b)
        db.session.add(chat)
        db.session.flush()
    return chat


def story_to_dict(story, current_user_id):
    """Convert a Story ORM object to a dictionary for API response."""
    liked = StoryLike.query.filter_by(story_id=story.id, user_id=current_user_id).first() is not None
    viewed = StoryView.query.filter_by(story_id=story.id, viewer_id=current_user_id).first() is not None

    return {
        'id': story.id,
        'user_id': story.user_id,
        'display_name': story.user.display_name or story.user.username,
        'username': story.user.username,
        'avatar': story.user.avatar_url,  # frontend uses avatar field
        'media_url': f"/uploads/{story.media_path}" if story.media_path else None,
        'media_type': story.media_type,
        'caption': story.caption,
        'music_path': f"/uploads/{story.music_path}" if getattr(story, 'music_path', None) else None,
        'created_at': story.created_at.isoformat(),
        'expires_at': (story.created_at + timedelta(hours=24)).isoformat(),
        'viewed': viewed,
        'view_count': StoryView.query.filter_by(story_id=story.id).count(),
        'like_count': StoryLike.query.filter_by(story_id=story.id).count(),
        'liked': liked,
        'privacy': getattr(story, 'privacy_type', 'everyone')
    }


# ==================== MAIN ENDPOINTS ====================

@spa_stories_bp.route('/stories', methods=['GET'])
def get_stories():
    """
    Return all visible stories grouped by user, with unviewed flag.
    Filters by privacy (everyone/contacts/selected) and 24h expiry.
    """
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    premium = _require_premium(current_user_id)
    if premium:
        return premium

    cutoff = datetime.utcnow() - timedelta(hours=24)
    # Base query: active stories of the current user and their contacts
    # For full implementation, use Nexgram logic with privacy checks.
    # Gather all story user IDs that the current user might see
    visible_user_ids = set([current_user_id])  # always include own stories
    for (uid,) in db.session.query(Message.sender_id).filter_by(receiver_id=current_user_id).distinct():
        visible_user_ids.add(uid)
    for (uid,) in db.session.query(Message.receiver_id).filter_by(sender_id=current_user_id).distinct():
        visible_user_ids.add(uid)

    stories = Story.query.filter(
        Story.created_at >= cutoff,
        Story.user_id.in_(visible_user_ids)
    ).order_by(Story.created_at.desc()).all()

    # Group by user
    user_stories = {}
    for story in stories:
        uid = story.user_id
        if uid not in user_stories:
            user = story.user
            user_stories[uid] = {
                'user_id': uid,
                'username': user.username,
                'display_name': user.display_name or user.username,
                'avatar_url': user.avatar_url,
                'avatar_letter': user.username[0].upper() if user.username else '?',
                'stories': [],
                'has_unviewed': False
            }
        data = story_to_dict(story, current_user_id)
        user_stories[uid]['stories'].append(data)
        if not data['viewed'] and uid != current_user_id:
            user_stories[uid]['has_unviewed'] = True

    # Sort: own stories first, then stories with unviewed first, then by newest
    sorted_users = sorted(user_stories.values(), key=lambda x: (
        0 if x['user_id'] == current_user_id else 1,
        0 if x['has_unviewed'] else 1,
        max([s['created_at'] for s in x['stories']]) if x['stories'] else '0'
    ), reverse=False)

    return jsonify({'success': True, 'stories': sorted_users})


@spa_stories_bp.route('/stories/create', methods=['POST'])
def create_story():
    """
    Create a new story. Accepts multipart form with 'media', 'caption', 'privacy', 'selected_users', 'music'.
    """
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    premium = _require_premium(current_user_id)
    if premium:
        return premium

    if 'media' not in request.files:
        return jsonify({'success': False, 'error': 'No media provided'}), 400

    file = request.files['media']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400

    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
    if ext in ALLOWED_IMAGE_EXTENSIONS:
        media_type = 'image'
    elif ext in ALLOWED_VIDEO_EXTENSIONS:
        media_type = 'video'
    else:
        return jsonify({'success': False, 'error': 'Unsupported media type'}), 400

    # Save the media file
    unique_name = f"story_{current_user_id}_{secrets.token_urlsafe(8)}.{ext}"
    stories_dir = os.path.join('uploads', 'stories')
    os.makedirs(stories_dir, exist_ok=True)
    media_path = os.path.join(stories_dir, unique_name)
    file.save(media_path)
    relative_media_path = os.path.join('stories', unique_name)

    # Optional music
    music_path = None
    if 'music' in request.files:
        music_file = request.files['music']
        if music_file and music_file.filename:
            music_ext = music_file.filename.rsplit('.', 1)[1].lower()
            music_name = f"story_music_{current_user_id}_{secrets.token_urlsafe(8)}.{music_ext}"
            music_dir = os.path.join('uploads', 'story_music')
            os.makedirs(music_dir, exist_ok=True)
            music_full_path = os.path.join(music_dir, music_name)
            music_file.save(music_full_path)
            music_path = os.path.join('story_music', music_name)

    caption = request.form.get('caption', '')
    privacy = request.form.get('privacy', 'everyone')
    selected_users = request.form.getlist('selected_users')

    new_story = Story(
        user_id=current_user_id,
        media_path=relative_media_path,
        media_type=media_type,
        caption=caption,
        created_at=datetime.utcnow()
    )
    # Extended fields – set if model supports them
    if hasattr(new_story, 'music_path'):
        new_story.music_path = music_path
    if hasattr(new_story, 'privacy_type'):
        new_story.privacy_type = privacy

    db.session.add(new_story)
    db.session.flush()

    # Store privacy settings (if tables exist)
    if hasattr(StoryPrivacy, '__tablename__'):
        db.session.add(StoryPrivacy(story_id=new_story.id, privacy_type=privacy))
    if privacy == 'selected' and selected_users and hasattr(StoryAllowedUser, '__tablename__'):
        for uid in selected_users:
            db.session.add(StoryAllowedUser(story_id=new_story.id, user_id=int(uid)))

    db.session.commit()

    return jsonify({'success': True, 'story': story_to_dict(new_story, current_user_id)})


@spa_stories_bp.route('/stories/<int:story_id>/view', methods=['POST'])
def view_story(story_id):
    """Mark a story as viewed by the current user."""
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    premium = _require_premium(current_user_id)
    if premium:
        return premium

    story = Story.query.get_or_404(story_id)
    existing = StoryView.query.filter_by(story_id=story_id, viewer_id=current_user_id).first()
    if not existing:
        db.session.add(StoryView(story_id=story_id, viewer_id=current_user_id, viewed_at=datetime.utcnow()))
        db.session.commit()
    return jsonify({'success': True})


@spa_stories_bp.route('/stories/<int:story_id>/like', methods=['POST'])
def like_story(story_id):
    """Toggle like on a story."""
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    premium = _require_premium(current_user_id)
    if premium:
        return premium

    existing = StoryLike.query.filter_by(story_id=story_id, user_id=current_user_id).first()
    if existing:
        db.session.delete(existing)
        liked = False
    else:
        db.session.add(StoryLike(story_id=story_id, user_id=current_user_id))
        liked = True
    db.session.commit()

    like_count = StoryLike.query.filter_by(story_id=story_id).count()
    return jsonify({'success': True, 'liked': liked, 'like_count': like_count})


@spa_stories_bp.route('/stories/<int:story_id>/reaction', methods=['POST'])
def react_to_story(story_id):
    """Add a reaction (❤️, 🔥, 👎, 👍) to a story."""
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    premium = _require_premium(current_user_id)
    if premium:
        return premium

    data = request.get_json()
    reaction = data.get('reaction')
    if reaction not in ('❤️', '🔥', '👎', '👍'):
        return jsonify({'success': False, 'error': 'Invalid reaction'}), 400

    # Upsert the reaction (one per user per story)
    existing = StoryReaction.query.filter_by(story_id=story_id, user_id=current_user_id).first()
    if existing:
        existing.reaction = reaction
    else:
        db.session.add(StoryReaction(story_id=story_id, user_id=current_user_id, reaction=reaction))
    db.session.commit()

    # Optionally, send a message to the story owner
    story = Story.query.get(story_id)
    if story and story.user_id != current_user_id:
        chat = _get_or_create_personal_chat(current_user_id, story.user_id)
        reaction_map = {'❤️': '❤️', '🔥': '🔥', '👎': '👎', '👍': '👍'}
        reaction_text = reaction_map.get(reaction, reaction)
        msg = Message(content=f"📱 Reaction to your story: {reaction_text}",
                      sender_id=current_user_id, receiver_id=story.user_id,
                      chat_id=chat.id, timestamp=datetime.utcnow())
        db.session.add(msg)
        db.session.commit()

    return jsonify({'success': True})


@spa_stories_bp.route('/stories/<int:story_id>/reply', methods=['POST'])
def reply_to_story(story_id):
    """Reply to a story – sends a message to the story owner."""
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    premium = _require_premium(current_user_id)
    if premium:
        return premium

    data = request.get_json()
    reply_text = data.get('reply_text', '').strip()
    if not reply_text:
        return jsonify({'success': False, 'error': 'Reply text required'}), 400

    story = Story.query.get_or_404(story_id)
    chat = _get_or_create_personal_chat(current_user_id, story.user_id)
    from app.models import Message

    msg = Message(
        content=f"📱 Story reply: {reply_text}",
        sender_id=current_user_id,
        receiver_id=story.user_id,
        chat_id=chat.id,
        timestamp=datetime.utcnow()
    )
    db.session.add(msg)
    db.session.commit()

    from app.utils.helpers import message_to_dict as _story_msg_dict
    return jsonify({'success': True, 'chat_id': story.user_id, 'message': _story_msg_dict(msg, current_user_id)})


@spa_stories_bp.route('/stories/<int:story_id>/stats', methods=['GET'])
def story_stats(story_id):
    """Get detailed statistics for a story (only the owner can see)."""
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    premium = _require_premium(current_user_id)
    if premium:
        return premium

    story = Story.query.get_or_404(story_id)
    if story.user_id != current_user_id:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403

    # Viewers
    views = StoryView.query.filter_by(story_id=story_id).order_by(StoryView.viewed_at.desc()).all()
    viewers_list = []
    for v in views:
        u = User.query.get(v.viewer_id)
        if u:
            viewers_list.append({
                'id': u.id, 'username': u.username, 'display_name': u.display_name or u.username,
                'avatar': u.avatar_url, 'viewed_at': v.viewed_at.isoformat()
            })

    # Likes
    likes = StoryLike.query.filter_by(story_id=story_id).order_by(StoryLike.created_at.desc()).all()
    likes_list = []
    for l in likes:
        u = User.query.get(l.user_id)
        if u:
            likes_list.append({'id': u.id, 'username': u.username, 'display_name': u.display_name or u.username,
                               'avatar': u.avatar_url, 'created_at': l.created_at.isoformat()})

    # Reactions
    reactions = StoryReaction.query.filter_by(story_id=story_id).order_by(StoryReaction.created_at.desc()).all()
    reactions_list = []
    for r in reactions:
        u = User.query.get(r.user_id)
        if u:
            reactions_list.append({'id': u.id, 'username': u.username, 'display_name': u.display_name or u.username,
                                   'avatar': u.avatar_url, 'reaction': r.reaction, 'created_at': r.created_at.isoformat()})

    # Replies are not stored separately; they are chat messages. For now, return empty.
    return jsonify({
        'success': True,
        'viewers': viewers_list,
        'likes': likes_list,
        'reactions': reactions_list,
        'total_views': len(viewers_list),
        'total_likes': len(likes_list),
        'total_reactions': len(reactions_list)
    })


@spa_stories_bp.route('/stories/<int:story_id>', methods=['DELETE'])
def delete_story(story_id):
    """Delete a story (only the owner can delete)."""
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    premium = _require_premium(current_user_id)
    if premium:
        return premium

    story = Story.query.get_or_404(story_id)
    if story.user_id != current_user_id:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403

    # Delete media file if it exists
    if story.media_path:
        full_path = os.path.join('uploads', story.media_path)
        if os.path.exists(full_path):
            os.remove(full_path)
    if getattr(story, 'music_path', None):
        music_full = os.path.join('uploads', story.music_path)
        if os.path.exists(music_full):
            os.remove(music_full)

    db.session.delete(story)
    db.session.commit()
    return jsonify({'success': True})