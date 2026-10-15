from datetime import datetime
from flask import Blueprint, request, jsonify, session
from sqlalchemy.orm import joinedload, selectinload
from app import db
from app.models import User, Chat, ChatMember, Contact, BlockedUser, Message, UserMusic, ChatSubscriber, RecentSearch
from app.utils.helpers import get_current_user_id, get_current_user

spav2_search_bp = Blueprint('spav2_search', __name__, url_prefix='/api')


@spav2_search_bp.route('/search/global', methods=['GET'])
def global_search():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    query = request.args.get('q', '').strip()
    if not query or len(query) < 2:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'Query must be at least 2 characters'}}), 400

    q = f"%{query}%"
    blocked_ids = [b.blocked_user_id for b in BlockedUser.query.with_entities(BlockedUser.blocked_user_id).filter_by(user_id=current_user_id).all()]
    limit = min(request.args.get('per_page', 10, type=int), 50)

    # Users
    users = User.query.filter(User.is_deleted == False, User.username.ilike(q) | (User.display_name.ilike(q))).limit(limit).all()
    contacts_set = set(c.contact_id for c in Contact.query.with_entities(Contact.contact_id).filter_by(user_id=current_user_id).all())
    users_data = []
    for u in users:
        if u.id == current_user_id or u.id in blocked_ids:
            continue
        users_data.append({
            'user_id': u.id,
            'username': u.username,
            'display_name': u.display_name or u.username,
            'avatar_url': u.avatar_url,
            'is_contact': u.id in contacts_set,
            'status_emoji': getattr(u, 'status_emoji', '') or ''
        })

    # Groups
    group_ids = set(m.chat_id for m in ChatMember.query.with_entities(ChatMember.chat_id).filter_by(user_id=current_user_id).all())
    groups = Chat.query.filter(Chat.id.in_(group_ids), Chat.name.ilike(q), Chat.chat_type == 'group').limit(limit).all()
    group_counts = dict(db.session.query(ChatMember.chat_id, db.func.count(ChatMember.id)).filter(ChatMember.chat_id.in_([g.id for g in groups])).group_by(ChatMember.chat_id).all()) if groups else {}
    groups_data = []
    for g in groups:
        groups_data.append({
            'group_id': g.id,
            'name': g.name,
            'avatar_url': g.avatar_url,
            'member_count': group_counts.get(g.id, 0),
            'is_member': True
        })

    # Channels
    chan_ids = set(s.chat_id for s in ChatSubscriber.query.with_entities(ChatSubscriber.chat_id).filter_by(user_id=current_user_id).all())
    channels = Chat.query.filter(Chat.id.in_(chan_ids), Chat.name.ilike(q), Chat.chat_type == 'channel').limit(limit).all()
    chan_counts = dict(db.session.query(ChatSubscriber.chat_id, db.func.count(ChatSubscriber.id)).filter(ChatSubscriber.chat_id.in_([c.id for c in channels])).group_by(ChatSubscriber.chat_id).all()) if channels else {}
    channels_data = []
    for c in channels:
        channels_data.append({
            'channel_id': c.id,
            'name': c.name,
            'avatar_url': c.avatar_url,
            'subscriber_count': chan_counts.get(c.id, 0),
            'is_subscribed': True
        })

    return jsonify({'success': True, 'data': {
        'query': query,
        'per_page': limit,
        'results': {
            'users': users_data,
            'groups': groups_data,
            'channels': channels_data
        }
    }})


@spav2_search_bp.route('/users/<int:user_id>/music', methods=['GET'])
def get_user_music(user_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    u = User.query.filter_by(id=user_id, is_deleted=False).first()
    if not u:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'User not found'}}), 404

    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 100)
    offset_val = (page - 1) * per_page

    query_tracks = UserMusic.query.filter_by(user_id=user_id)
    total = query_tracks.count()
    tracks = query_tracks.order_by(UserMusic.added_at.desc()).offset(offset_val).limit(per_page).all()
    pages = (total + per_page - 1) // per_page if per_page else 0

    return jsonify({'success': True, 'data': {
        'tracks': [{
            'id': t.id,
            'file_url': t.file_url,
            'file_name': t.file_name,
            'artist': t.artist,
            'title': t.title,
            'duration': t.duration,
            'added_at': t.added_at.isoformat() if t.added_at else None
        } for t in tracks],
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': pages
    }})


@spav2_search_bp.route('/users/<int:user_id>/files', methods=['GET'])
def get_user_files(user_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    u = User.query.filter_by(id=user_id, is_deleted=False).first()
    if not u:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'User not found'}}), 404

    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 100)
    offset_val = (page - 1) * per_page

    query_files = (Message.query
        .filter(
            ((Message.sender_id == current_user_id) & (Message.receiver_id == user_id)) |
            ((Message.sender_id == user_id) & (Message.receiver_id == current_user_id)),
            Message.has_attachment == True,
            Message.file_path.isnot(None)
        ))
    total = query_files.count()
    messages = query_files.order_by(Message.timestamp.desc()).offset(offset_val).limit(per_page).all()
    pages = (total + per_page - 1) // per_page if per_page else 0

    return jsonify({'success': True, 'data': {
        'files': [{
            'message_id': m.id,
            'file_path': m.file_path,
            'file_name': m.file_name,
            'file_type': m.file_type,
            'file_size': m.file_size,
            'thumbnail_path': m.thumbnail_path,
            'timestamp': m.timestamp.isoformat() if m.timestamp else None,
            'sender_id': m.sender_id
        } for m in messages],
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': pages
    }})


@spav2_search_bp.route('/search_in_chat', methods=['POST'])
def search_in_chat():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    data = request.get_json() or {}
    chat_id = data.get('chat_id')
    query = data.get('query', '').strip()

    if not chat_id or not query:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'chat_id and query are required'}}), 400

    chat_type = data.get('chat_type', 'personal')

    try:
        chat_id_int = int(chat_id)
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'Invalid chat_id format'}}), 400

    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 100)
    offset_val = (page - 1) * per_page

    if chat_type == 'personal':
        base_query = Message.query.filter(
            ((Message.sender_id == current_user_id) & (Message.receiver_id == chat_id_int)) |
            ((Message.sender_id == chat_id_int) & (Message.receiver_id == current_user_id))
        )
    else:
        base_query = Message.query.filter_by(chat_id=chat_id_int)

    all_messages = base_query.order_by(Message.timestamp.desc()).all()
    matched = [m for m in all_messages if m.content and query.lower() in m.content.lower()]
    total = len(matched)
    messages = matched[offset_val:offset_val + per_page]
    pages = (total + per_page - 1) // per_page if per_page else 0

    results = []
    for msg in messages:
        results.append({
            'message_id': msg.id,
            'sender_id': msg.sender_id,
            'content': msg.content,
            'timestamp': msg.timestamp.isoformat() if msg.timestamp else None
        })

    return jsonify({'success': True, 'data': {
        'chat_id': chat_id, 'chat_type': chat_type,
        'query': query, 'results': results, 'total': total,
        'page': page, 'per_page': per_page, 'pages': pages
    }})


@spav2_search_bp.route('/recent_searches', methods=['GET'])
def recent_searches():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    searches = RecentSearch.query.filter_by(user_id=current_user_id).order_by(RecentSearch.created_at.desc()).limit(10).all()
    return jsonify({'success': True, 'data': {'searches': [
        {'search_id': s.id, 'query': s.search_query, 'created_at': s.created_at.isoformat() if s.created_at else None}
        for s in searches
    ]}})


@spav2_search_bp.route('/recent_searches', methods=['POST'])
def add_recent_search():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    data = request.get_json() or {}
    query = data.get('query', '').strip()
    if not query:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'query is required'}}), 400

    existing = RecentSearch.query.filter_by(user_id=current_user_id, search_query=query).first()
    if existing:
        existing.created_at = datetime.utcnow()
    else:
        db.session.add(RecentSearch(user_id=current_user_id, search_query=query, created_at=datetime.utcnow()))

    recent = RecentSearch.query.filter_by(user_id=current_user_id).order_by(RecentSearch.created_at.desc()).all()
    for r in recent[20:]:
        db.session.delete(r)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Database error'}}), 500
    return jsonify({'success': True, 'data': {'message': 'Search saved'}})
