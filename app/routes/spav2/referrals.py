from flask import Blueprint, request, jsonify
from datetime import datetime, timezone
from math import ceil
from sqlalchemy.exc import IntegrityError
from app import db
from app.models import User, Referral
from app.utils.helpers import get_current_user_id
from app.utils.security import rate_limit

spav2_referrals_bp = Blueprint('spav2_referrals', __name__, url_prefix='/api')

#: Number of successful referrals that grants premium automatically.
REFERRAL_PREMIUM_THRESHOLD = 10

#: Premium days the inviter earns per successful referral (stackable).
REFERRAL_PREMIUM_DAYS = 30


def grant_referral_reward(inviter):
    """Extend inviter premium by REFERRAL_PREMIUM_DAYS. No commit; caller commits.
    Returns (count, premium_until)."""
    from datetime import timedelta
    from app.models import UserPremium
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if not inviter.premium:
        inviter.premium = UserPremium(user_id=inviter.id, is_premium=True)
        db.session.flush()
    base = inviter.premium.premium_expires_at
    if not inviter.premium.is_premium or not base or base < now:
        base = now
    inviter.premium.is_premium = True
    inviter.premium.premium_expires_at = base + timedelta(days=REFERRAL_PREMIUM_DAYS)
    if not inviter.status_emoji:
        inviter.status_emoji = '\u2b50'
    count = Referral.query.filter_by(inviter_id=inviter.id).count()
    return count, inviter.premium.premium_expires_at


@spav2_referrals_bp.route('/referrals/check', methods=['POST'])
@rate_limit('referral_check', max_requests=20, window=60)
def check_referral():
    """Public: validate a friend code before registration."""
    code = (request.get_json() or {}).get('code', '').strip()
    if not code:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'Code required'}}), 400
    inviter = User.query.filter_by(username=code, is_deleted=False).first()
    if not inviter:
        return jsonify({'success': False, 'error': {'code': 'INVALID_CODE', 'message': 'Unknown friend code'}}), 404
    return jsonify({'success': True, 'data': {
        'username': inviter.username,
        'display_name': inviter.display_name or inviter.username,
        'avatar_url': inviter.avatar_url,
    }})


@spav2_referrals_bp.route('/referrals/info', methods=['GET'])
def referral_info():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    user = User.query.filter_by(id=current_user_id, is_deleted=False).first()
    if not user:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'User not found'}}), 404

    count = Referral.query.filter_by(inviter_id=current_user_id).count()
    threshold = REFERRAL_PREMIUM_THRESHOLD
    invite_url = f"https://kiselgram.ru/join?ref={user.username}"

    return jsonify({'success': True, 'data': {
        'invite_code': user.username,
        'invite_url': invite_url,
        'count': count,
        'threshold': threshold,
        'premium_days_per_referral': REFERRAL_PREMIUM_DAYS,
        'has_premium': user.premium.is_premium if user.premium else False,
    }})


@spav2_referrals_bp.route('/referrals/use', methods=['POST'])
def use_referral():
    data = request.get_json() or {}
    code = data.get('ref', '').strip()
    user_id = data.get('user_id') or get_current_user_id()

    if not code or not user_id:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION_ERROR', 'message': 'ref and user_id required'}}), 400

    inviter = User.query.filter_by(username=code, is_deleted=False).first()
    if not inviter:
        return jsonify({'success': False, 'error': {'code': 'INVALID_CODE', 'message': 'Invalid referral code'}}), 404

    if inviter.id == user_id:
        return jsonify({'success': False, 'error': {'code': 'SELF_REFERRAL', 'message': 'Cannot refer yourself'}}), 400

    ref = Referral(inviter_id=inviter.id, invited_user_id=user_id)
    db.session.add(ref)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'success': True, 'data': {'already_applied': True}})

    # Reward: every referral extends the inviter's premium (stackable).
    count, until = grant_referral_reward(inviter)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Failed to apply referral'}}), 500

    return jsonify({'success': True, 'data': {
        'inviter_username': inviter.username,
        'count': count,
        'premium_granted': True,
        'days_added': REFERRAL_PREMIUM_DAYS,
        'premium_until': until.isoformat(),
    }})


@spav2_referrals_bp.route('/referrals/list', methods=['GET'])
def referral_list():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    page = max(1, page)
    per_page = max(1, min(100, per_page))

    total = Referral.query.filter_by(inviter_id=current_user_id).count()
    pages = ceil(total / per_page) if total else 0

    refs = Referral.query.filter_by(inviter_id=current_user_id).order_by(Referral.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    users = User.query.filter(User.id.in_([r.invited_user_id for r in refs]), User.is_deleted == False).all()
    user_map = {u.id: u for u in users}

    return jsonify({'success': True, 'data': {
        'referrals': [{
            'username': user_map[r.invited_user_id].username if r.invited_user_id in user_map else 'deleted',
            'created_at': r.created_at.isoformat(),
        } for r in refs],
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total': total,
            'pages': pages,
        },
    }})
