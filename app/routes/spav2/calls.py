from datetime import datetime
import secrets
import os
import json
import requests
from flask import Blueprint, request, jsonify, current_app
from app import db
from app.models import User, Call, VideoCall, VideoCallParticipant, PushSubscription
from app.utils.helpers import get_current_user_id, get_current_user

spav2_calls_bp = Blueprint('spav2_calls', __name__, url_prefix='/api')

VIDEO_HOST = os.environ.get('VIDEO_HOST', 'localhost')
VIDEO_PORT = os.environ.get('VIDEO_PORT', '5001')
VIDEO_BASE_URL = f"http://{VIDEO_HOST}:{VIDEO_PORT}"
VIDEO_TIMEOUT = 5


def _send_push(subscription, payload):
    """Send web push notification to a subscription."""
    try:
        from pywebpush import webpush, WebPushException
        vapid_private = os.environ.get('VAPID_PRIVATE_KEY', '')
        vapid_claims = {
            'sub': os.environ.get('VAPID_CLAIMS_SUB', 'mailto:admin@kiselgram.ru')
        }
        if not vapid_private:
            return False
        webpush(
            subscription_info={
                'endpoint': subscription.endpoint,
                'keys': {'p256dh': subscription.p256dh, 'auth': subscription.auth}
            },
            data=json.dumps(payload),
            vapid_private_key=vapid_private,
            vapid_claims=vapid_claims
        )
        return True
    except Exception as e:
        print(f'[push] send error: {e}')
        return False


def _send_push_to_user(user_id, payload):
    """Send push notification to all subscriptions of a user."""
    subs = PushSubscription.query.filter_by(user_id=user_id).all()
    for sub in subs:
        _send_push(sub, payload)


def _notify_ws(user_id, data):
    """Send WebSocket message to a user via the notify signaler."""
    try:
        from app.notify_ws import notify_users
        notify_users(user_id, data)
    except ImportError:
        pass


# ── Start a call: creates Call + VideoCall room + pushes notification ──
@spav2_calls_bp.route('/calls/start', methods=['POST'])
def start_call():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    data = request.get_json() or {}
    callee_id = data.get('callee_id')
    call_type = data.get('type', 'audio')

    if not callee_id:
        return jsonify({'success': False, 'error': {'code': 'INVALID_INPUT', 'message': 'callee_id required'}}), 400
    callee_id = int(callee_id)

    if callee_id == current_user_id:
        return jsonify({'success': False, 'error': {'code': 'INVALID_INPUT', 'message': 'Cannot call yourself'}}), 400

    callee = User.query.filter(User.id == callee_id, User.is_deleted == False).first()
    if not callee:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'User not found'}}), 404

    caller = User.query.get(current_user_id)
    room_token = f"room_{secrets.token_urlsafe(16)}"

    # Create call record
    call = Call(
        caller_id=current_user_id,
        receiver_id=callee_id,
        call_type=call_type,
        status='ringing',
        room_token=room_token,
        created_at=datetime.utcnow()
    )
    db.session.add(call)

    # Create video room via video server
    room_id = None
    room_url = None
    try:
        r = requests.post(f"{VIDEO_BASE_URL}/api/rooms", json={
            'username': caller.username if caller else 'User',
            'user_id': current_user_id,
            'name': f"{caller.username if caller else 'User'}'s Call",
        }, timeout=VIDEO_TIMEOUT)
        if r.status_code == 200:
            room_data = r.json()
            room_id = room_data.get('room_id')
            room_url = room_data.get('join_url', f"{VIDEO_BASE_URL}/room/{room_id}")
    except Exception as e:
        print(f'[calls] video server error: {e}')

    # If no room from video server, generate a fallback room_id
    if not room_id:
        room_id = f"call_{secrets.token_urlsafe(8)}"
        room_url = f"/api/video/room/{room_id}"

    # Create video call record
    vc = VideoCall(
        room_id=room_id,
        creator_id=current_user_id,
        call_type=call_type,
        status='active',
        started_at=datetime.utcnow()
    )
    db.session.add(vc)
    db.session.flush()

    participant = VideoCallParticipant(
        call_id=vc.id,
        user_id=current_user_id,
        joined_at=datetime.utcnow()
    )
    db.session.add(participant)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'DB_ERROR', 'message': 'Failed to create call'}}), 500

    # Send WebSocket notification to callee
    caller_name = caller.display_name if caller and hasattr(caller, 'display_name') else (caller.username if caller else 'Unknown')
    _notify_ws(callee_id, {
        'type': 'call-invite',
        'call_id': call.id,
        'caller_id': current_user_id,
        'caller_name': caller_name,
        'call_type': call_type,
        'room_id': room_id,
        'room_url': room_url
    })

    # Send web push notification to callee
    _send_push_to_user(callee_id, {
        'type': 'call-invite',
        'title': f'Incoming {call_type} call',
        'body': f'{caller_name} is calling you',
        'call_id': call.id,
        'room_id': room_id,
        'url': f'/k?chat=personal:{current_user_id}'
    })

    return jsonify({
        'success': True,
        'data': {
            'call_id': call.id,
            'room_id': room_id,
            'room_url': room_url
        }
    }), 201


# ── Accept a call ──
@spav2_calls_bp.route('/calls/<int:call_id>/accept', methods=['POST'])
def accept_call(call_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    call = Call.query.get(call_id)
    if not call:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Call not found'}}), 404
    if call.receiver_id != current_user_id:
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'Not your call'}}), 403
    if call.status != 'ringing':
        return jsonify({'success': False, 'error': {'code': 'INVALID_STATE', 'message': 'Call not ringing'}}), 400

    call.status = 'answered'

    # Find the video room
    vc = VideoCall.query.filter_by(creator_id=call.caller_id).order_by(VideoCall.started_at.desc()).first()
    room_id = vc.room_id if vc else None

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'DB_ERROR', 'message': 'Failed to accept call'}}), 500

    # Notify caller that call was accepted
    _notify_ws(call.caller_id, {
        'type': 'call-accepted',
        'call_id': call.id,
        'room_id': room_id
    })

    return jsonify({
        'success': True,
        'data': {
            'call_id': call.id,
            'room_id': room_id
        }
    })


# ── Reject a call ──
@spav2_calls_bp.route('/calls/<int:call_id>/reject', methods=['POST'])
def reject_call(call_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    call = Call.query.get(call_id)
    if not call:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Call not found'}}), 404
    if call.receiver_id != current_user_id:
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'Not your call'}}), 403

    call.status = 'ended'
    call.ended_at = datetime.utcnow()

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'DB_ERROR', 'message': 'Failed to reject call'}}), 500

    # Notify caller that call was rejected
    _notify_ws(call.caller_id, {
        'type': 'call-rejected',
        'call_id': call.id
    })

    return jsonify({'success': True, 'data': {'message': 'Call rejected'}})


# ── End a call ──
@spav2_calls_bp.route('/calls/<int:call_id>/end', methods=['POST'])
def end_call(call_id):
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    call = Call.query.get(call_id)
    if not call:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Call not found'}}), 404
    if call.caller_id != current_user_id and call.receiver_id != current_user_id:
        return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'Not your call'}}), 403

    call.status = 'ended'
    call.ended_at = datetime.utcnow()
    if call.created_at:
        call.duration_seconds = int((call.ended_at - call.created_at).total_seconds())

    # Update video call status
    vc = VideoCall.query.filter_by(creator_id=call.caller_id).order_by(VideoCall.started_at.desc()).first()
    if vc:
        vc.status = 'ended'
        vc.ended_at = datetime.utcnow()
        if vc.started_at:
            vc.duration = int((vc.ended_at - vc.started_at).total_seconds())

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': {'code': 'DB_ERROR', 'message': 'Failed to end call'}}), 500

    # Notify the other party
    other_id = call.receiver_id if call.caller_id == current_user_id else call.caller_id
    _notify_ws(other_id, {
        'type': 'call-ended',
        'call_id': call.id
    })

    return jsonify({'success': True, 'data': {'message': 'Call ended'}})


# ── Call history ──
@spav2_calls_bp.route('/calls/history', methods=['GET'])
def call_history():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    per_page = min(max(per_page, 1), 100)

    base_q = Call.query.filter(
        (Call.caller_id == current_user_id) | (Call.receiver_id == current_user_id)
    )
    total = base_q.count()
    pages = (total + per_page - 1) // per_page if per_page else 0

    calls = base_q.order_by(Call.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

    peer_ids = set()
    for call in calls:
        peer_ids.add(call.receiver_id if call.caller_id == current_user_id else call.caller_id)
    peers = {u.id: u for u in User.query.filter(User.id.in_(peer_ids), User.is_deleted == False).all()}

    result = []
    for call in calls:
        is_outgoing = call.caller_id == current_user_id
        peer_id = call.receiver_id if is_outgoing else call.caller_id
        peer = peers.get(peer_id)

        result.append({
            'call_id': call.id,
            'call_type': call.call_type,
            'peer_id': peer_id,
            'peer_name': peer.display_name if peer and hasattr(peer, 'display_name') else (peer.username if peer else 'Unknown'),
            'peer': {
                'user_id': peer_id,
                'username': peer.username if peer else None,
                'avatar_url': peer.avatar_url if peer else None
            },
            'direction': 'outgoing' if is_outgoing else 'incoming',
            'status': call.status,
            'duration_seconds': getattr(call, 'duration_seconds', 0) or call.duration or 0,
            'created_at': call.created_at.isoformat() if call.created_at else None,
            'ended_at': call.ended_at.isoformat() if call.ended_at else None
        })

    return jsonify({'success': True, 'data': {'calls': result, 'page': page, 'per_page': per_page, 'total': total, 'pages': pages}})


# ── Legacy: create room (backward compat) ──
@spav2_calls_bp.route('/video/create-room', methods=['POST'])
def video_create_room():
    current_user_id = get_current_user_id()
    if not current_user_id:
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'}}), 401

    user = get_current_user()

    try:
        r = requests.post(f"{VIDEO_BASE_URL}/api/rooms", json={
            'username': user.username if user else 'User',
            'user_id': current_user_id,
            'name': f"{user.username if user else 'User'}'s Video Call",
        }, timeout=VIDEO_TIMEOUT)

        if r.status_code != 200:
            return jsonify({'success': False, 'error': {'code': 'VIDEO_SERVER_ERROR', 'message': 'Video server error'}}), 502

        room_data = r.json()
        room_id = room_data.get('room_id')
        join_url = room_data.get('join_url', f"{VIDEO_BASE_URL}/room/{room_id}")

        vc = VideoCall(
            room_id=room_id,
            creator_id=current_user_id,
            call_type='video',
            status='active',
            started_at=datetime.utcnow()
        )
        db.session.add(vc)
        db.session.flush()

        participant = VideoCallParticipant(
            call_id=vc.id,
            user_id=current_user_id,
            joined_at=datetime.utcnow()
        )
        db.session.add(participant)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            return jsonify({'success': False, 'error': {'code': 'DB_ERROR', 'message': 'Failed to create video call'}}), 500

        return jsonify({'success': True, 'data': {
            'room_id': room_id,
            'room_url': join_url,
            'video_call_id': vc.id
        }})

    except requests.exceptions.ConnectionError:
        return jsonify({'success': False, 'error': {'code': 'VIDEO_SERVER_OFFLINE', 'message': 'Video server not running'}}), 503
    except Exception as e:
        return jsonify({'success': False, 'error': {'code': 'INTERNAL_ERROR', 'message': str(e)}}), 500
