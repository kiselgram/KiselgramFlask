from flask import Blueprint, jsonify, request, session
from app import db
from app.models import UserSession, User
from app.utils.helpers import get_current_user_id

spav2_sessions_bp = Blueprint('spav2_sessions', __name__, url_prefix='/api')


@spav2_sessions_bp.route('/sessions', methods=['GET'])
def get_sessions():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 100)
    pagination = UserSession.query.filter_by(user_id=current_user_id).order_by(UserSession.last_activity.desc()).paginate(page=page, per_page=per_page, error_out=False)
    sessions = pagination.items
    return jsonify({'success': True, 'data': {
        'sessions': [
            {
                'session_token': s.session_token,
                'device': s.device or 'Unknown device',
                'ip_address': s.ip_address,
                'is_current': s.session_token == session.get('session_token'),
                'last_active': s.last_activity.isoformat() if s.last_activity else None,
                'created_at': s.created_at.isoformat() if s.created_at else None
            }
            for s in sessions
        ],
        'page': page,
        'per_page': per_page,
        'total': pagination.total,
        'pages': pagination.pages
    }})


@spav2_sessions_bp.route('/sessions/<int:session_id>', methods=['DELETE'])
def terminate_session(session_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    s = UserSession.query.filter_by(id=session_id, user_id=current_user_id).first()
    if not s:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Session not found'}}), 404

    try:
        s.is_active = False
        db.session.commit()
        return jsonify({'success': True, 'data': {'message': 'Session terminated'}})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': str(e)}}), 500
