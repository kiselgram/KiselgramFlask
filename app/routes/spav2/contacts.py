from datetime import datetime
from flask import Blueprint, request, jsonify
from sqlalchemy.orm import joinedload, selectinload
from app import db
from app.models import User, Contact, BlockedUser
from app.utils.helpers import get_current_user_id, presence_visible

spav2_contacts_bp = Blueprint('spav2_contacts', __name__, url_prefix='/api')


@spav2_contacts_bp.route('/contacts', methods=['GET'])
def get_contacts():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 100)
    offset = (page - 1) * per_page

    query = Contact.query.filter_by(user_id=current_user_id)
    total = query.count()
    contacts = query.order_by(Contact.id).offset(offset).limit(per_page).all()
    pages = (total + per_page - 1) // per_page if per_page else 0
    contact_ids = [c.contact_id for c in contacts]
    users = {}
    if contact_ids:
        user_rows = User.query.filter(User.id.in_(contact_ids), User.is_deleted == False).all()
        users = {u.id: u for u in user_rows}
    result = []
    for c in contacts:
        user = users.get(c.contact_id)
        if user:
            is_p = user.premium and user.premium.is_premium
            visible = presence_visible(current_user_id, user)
            result.append({
                'user_id': user.id,
                'username': user.username,
                'display_name': user.display_name or user.username,
                'avatar_url': user.avatar_url,
                'custom_name': c.custom_name,
                'is_online': getattr(user, 'is_online', False) if visible else False,
                'last_seen': user.last_seen.isoformat() if (user.last_seen and visible) else None,
                'added_at': c.created_at.isoformat() if c.created_at else None,
                'is_premium': is_p,
                'status_emoji': user.status_emoji or ('\u2b50' if is_p else '')
            })

    return jsonify({'success': True, 'data': {'contacts': result, 'total': total, 'page': page, 'per_page': per_page, 'pages': pages}})


@spav2_contacts_bp.route('/contacts', methods=['POST'])
def add_contact():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    data = request.get_json() or {}
    contact_id = data.get('contact_id')
    if not contact_id:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'contact_id is required'}}), 400

    existing = Contact.query.filter_by(user_id=current_user_id, contact_id=contact_id).first()
    if existing:
        return jsonify({'success': False, 'error': {'code': 'ALREADY_CONTACT', 'message': 'User is already in your contacts'}}), 400

    user = User.query.filter_by(id=contact_id, is_deleted=False).first()
    if not user:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'User not found'}}), 404

    c = Contact(user_id=current_user_id, contact_id=contact_id, created_at=datetime.utcnow())
    db.session.add(c)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Database error'}}), 500

    return jsonify({'success': True, 'data': {'contact': {
        'user_id': user.id, 'username': user.username,
        'display_name': user.display_name or user.username,
        'avatar_url': user.avatar_url,
        'custom_name': None, 'added_at': c.created_at.isoformat() if c.created_at else None
    }}}), 201


@spav2_contacts_bp.route('/contacts/rename', methods=['POST'])
def rename_contact():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    data = request.get_json() or {}
    contact_id = data.get('contact_id')
    name = data.get('name', '').strip()

    if not contact_id:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'contact_id is required'}}), 400

    contact = Contact.query.filter_by(user_id=current_user_id, contact_id=contact_id).first()
    if not contact:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Contact not found'}}), 404

    contact.custom_name = name
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Database error'}}), 500
    return jsonify({'success': True, 'data': {'user_id': contact_id, 'custom_name': name, 'updated_at': datetime.utcnow().isoformat()}})


@spav2_contacts_bp.route('/contacts/<int:contact_id>', methods=['DELETE'])
def remove_contact(contact_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    contact = Contact.query.filter_by(user_id=current_user_id, contact_id=contact_id).first()
    if contact:
        db.session.delete(contact)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Database error'}}), 500
    return jsonify({'success': True, 'data': {'message': 'Contact removed'}})


@spav2_contacts_bp.route('/blocked_users', methods=['GET'])
def get_blocked_users():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 100)
    offset = (page - 1) * per_page

    query = BlockedUser.query.filter_by(user_id=current_user_id)
    total = query.count()
    blocks = query.order_by(BlockedUser.id).offset(offset).limit(per_page).all()
    pages = (total + per_page - 1) // per_page if per_page else 0
    blocked_ids_list = [b.blocked_user_id for b in blocks]
    users = {}
    if blocked_ids_list:
        user_rows = User.query.filter(User.id.in_(blocked_ids_list), User.is_deleted == False).all()
        users = {u.id: u for u in user_rows}
    result = []
    for b in blocks:
        user = users.get(b.blocked_user_id)
        result.append({
            'user_id': b.blocked_user_id,
            'username': user.username if user else 'Unknown',
            'avatar_url': user.avatar_url if user else None,
            'blocked_at': b.created_at.isoformat() if b.created_at else None
        })

    return jsonify({'success': True, 'data': {'blocked_users': result, 'total': total, 'page': page, 'per_page': per_page, 'pages': pages}})


@spav2_contacts_bp.route('/block_user/<int:user_id>', methods=['POST'])
def block_user(user_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    existing = BlockedUser.query.filter_by(user_id=current_user_id, blocked_user_id=user_id).first()
    if not existing:
        b = BlockedUser(user_id=current_user_id, blocked_user_id=user_id, created_at=datetime.utcnow())
        db.session.add(b)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Database error'}}), 500
        blocked_at = datetime.utcnow().isoformat()
    else:
        blocked_at = existing.created_at.isoformat() if existing.created_at else datetime.utcnow().isoformat()

    user = User.query.get(user_id)
    return jsonify({'success': True, 'data': {
        'blocked_user_id': user_id,
        'username': user.username if user else None,
        'blocked_at': blocked_at
    }})


@spav2_contacts_bp.route('/unblock_user/<int:user_id>', methods=['POST'])
def unblock_user(user_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    existing = BlockedUser.query.filter_by(user_id=current_user_id, blocked_user_id=user_id).first()
    if existing:
        db.session.delete(existing)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Database error'}}), 500

    user = User.query.filter_by(id=user_id, is_deleted=False).first()
    return jsonify({'success': True, 'data': {'unblocked_user_id': user_id, 'username': user.username if user else None}})
