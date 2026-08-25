"""
Per-user notification WebSocket endpoint.
Maps user_id → set of connected SocketIO sid(s).
Expose `notify_users(user_id, data)` for the backend to push events.
"""
import json
import threading
from flask import request
from app.utils.helpers import get_current_user_id

# Global state
_user_connections = {}  # user_id → set of sids
_lock = threading.Lock()
_socketio = None


def init_notify_ws(app, socketio_instance):
    """Register SocketIO event handlers for /ws/user/<id> namespace."""
    global _socketio
    _socketio = socketio_instance

    @socketio_instance.on('identify', namespace='/notify')
    def on_identify(data):
        user_id = data.get('user_id') if isinstance(data, dict) else None
        if not user_id:
            return
        user_id = int(user_id)
        from flask_socketio import join_room
        join_room(f'user_{user_id}')
        with _lock:
            _user_connections.setdefault(user_id, set()).add(request.sid)
        print(f'[notify] user {user_id} identified, sid={request.sid}')

    @socketio_instance.on('disconnect', namespace='/notify')
    def on_disconnect():
        with _lock:
            for uid, sids in list(_user_connections.items()):
                if request.sid in sids:
                    sids.discard(request.sid)
                    if not sids:
                        _user_connections.pop(uid, None)
                    print(f'[notify] user {uid} disconnected, sid={request.sid}')
                    break


def notify_users(user_id, data):
    """Send a JSON message to all connected sockets of a user."""
    if _socketio is None:
        return
    from flask_socketio import emit
    emit('message', data, room=f'user_{user_id}', namespace='/notify')
