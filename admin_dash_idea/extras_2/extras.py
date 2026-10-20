"""
Extended admin API — clustering, bulk, notes, activity log, sessions, SSE.
Reuses the existing blueprint & decorator from admin.py.
"""
import json
import time
from datetime import datetime, timezone
from functools import wraps

from flask import Response, jsonify, request, stream_with_context
from app import db
from app.models import (
    User, Report, Message, Chat, ChatMember, ChatSubscriber,
    AdminAction, UserNote, UserSession,
)
from app.routes.spav2.admin import spav2_admin_bp, admin_required
from app.utils.helpers import get_current_user


# ============================================================
# KEYWORD GUESSER — replaces AI triage
# ============================================================

CATEGORY_KEYWORDS = {
    'violence':      ['kill', 'murder', 'shoot', 'weapon', 'bomb', 'terror', 'stab', 'attack'],
    'abuse':         ['insult', 'harass', 'threat', 'hate', 'racist', 'sexist',
                      'abuse', 'bully', 'curse', 'slur'],
    'nsfw':          ['nude', 'porn', 'nsfw', 'explicit', 'sex', 'xxx', 'naked', 'adult'],
    'spam':          ['spam', 'advertis', 'promo', 'buy now', 'click here',
                      'giveaway', 'free money', 'airdrop'],
    'scam':          ['scam', 'fraud', 'phishing', 'steal', 'hack', 'wallet', 'seed phrase'],
    'impersonation': ['impersonat', 'fake account', 'pretend', 'clone', 'copycat'],
    'copyright':     ['copyright', 'stolen', 'plagiar', 'dmca', 'republish'],
    'off-topic':     ['offtopic', 'off-topic', 'unrelated', 'not relevant'],
}

SEVERITY = {
    'violence': 'high', 'abuse': 'high', 'nsfw': 'high', 'scam': 'high',
    'impersonation': 'medium', 'copyright': 'medium',
    'spam': 'low', 'off-topic': 'low',
    'unknown': 'medium',
}

URGENCY_WORDS = ['urgent', 'immediately', 'asap', 'critical', 'severe', 'right now']


def guess_report(reason, reporter_age_hours=None, prior_reports_count=0):
    """Return a heuristic classification of a report reason."""
    if not reason:
        return {'category': 'unknown', 'severity': 'medium', 'score': 0,
                'confidence': 'low', 'matched_keywords': []}

    text = reason.lower()
    matches = {}
    for cat, kws in CATEGORY_KEYWORDS.items():
        hits = [kw for kw in kws if kw in text]
        if hits:
            matches[cat] = {'count': len(hits), 'hits': hits}

    if not matches:
        return {'category': 'unknown', 'severity': 'medium', 'score': 0,
                'confidence': 'low', 'matched_keywords': []}

    sev_rank = {'high': 3, 'medium': 2, 'low': 1}
    best_cat = max(matches, key=lambda c: (
        matches[c]['count'],
        sev_rank.get(SEVERITY.get(c, 'medium'), 0),
    ))
    info = matches[best_cat]
    severity = SEVERITY.get(best_cat, 'medium')

    urgency = sum(1 for w in URGENCY_WORDS if w in text)
    score = round(info['count'] + urgency * 0.5, 1)

    confidence = 'high' if info['count'] >= 2 else 'medium'
    if reporter_age_hours is not None and reporter_age_hours < 24:
        confidence = 'low'
    if prior_reports_count > 20:
        confidence = 'low'

    return {
        'category': best_cat,
        'severity': severity,
        'score': score,
        'confidence': confidence,
        'matched_keywords': info['hits'],
    }


def _reporter_stats(user_id):
    """Age in hours + prior report count for the reporter."""
    if not user_id:
        return None, 0
    u = User.query.get(user_id)
    if not u or not u.created_at:
        return None, Report.query.filter_by(reporter_id=user_id).count()
    age_h = (datetime.now(timezone.utc).replace(tzinfo=None) - u.created_at).total_seconds() / 3600
    return age_h, Report.query.filter_by(reporter_id=user_id).count()


# ============================================================
# AUDIT HELPER
# ============================================================

def _audit(action, target_type=None, target_id=None, details=None):
    try:
        actor = get_current_user()
        db.session.add(AdminAction(
            actor_id=actor.id if actor else None,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=json.dumps(details) if details else None,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()


# ============================================================
# GROUPED REPORTS (with guesses)
# ============================================================

@spav2_admin_bp.route('/reports/grouped', methods=['GET'])
@admin_required
def reports_grouped():
    status = request.args.get('status', 'pending')
    sort = request.args.get('sort', 'severity')
    rows = (Report.query.filter_by(status=status)
            .order_by(Report.created_at.desc()).all())

    by_msg = {}
    singles = []
    for r in rows:
        age, priors = _reporter_stats(r.reporter_id)
        g = guess_report(r.reason, age, priors)
        item = {
            'id': r.id,
            'reporter_id': r.reporter_id,
            'reported_user_id': r.reported_user_id,
            'reported_message_id': r.reported_message_id,
            'reason': r.reason,
            'created_at': r.created_at.isoformat() if r.created_at else None,
            'guess': g,
        }
        if r.reported_message_id:
            by_msg.setdefault(r.reported_message_id, []).append(item)
        else:
            singles.append(item)

    severity_rank = {'high': 3, 'medium': 2, 'low': 1}
    groups = []
    for msg_id, reports in by_msg.items():
        msg = Message.query.get(msg_id)
        sender = User.query.get(msg.sender_id) if msg else None
        worst = max(reports, key=lambda r: severity_rank.get(r['guess']['severity'], 0))
        groups.append({
            'kind': 'message',
            'message_id': msg_id,
            'message_content': (msg.content or '') if msg else None,
            'sender_id': sender.id if sender else None,
            'sender_username': sender.username if sender else None,
            'reports': reports,
            'count': len(reports),
            'severity': worst['guess']['severity'],
            'category': worst['guess']['category'],
        })

    if sort == 'severity':
        groups.sort(key=lambda g: (severity_rank.get(g['severity'], 0), g['count']), reverse=True)
        singles.sort(key=lambda r: severity_rank.get(r['guess']['severity'], 0), reverse=True)
    elif sort == 'date':
        groups.sort(key=lambda g: max((r['created_at'] or '') for r in g['reports']), reverse=True)
        singles.sort(key=lambda r: r['created_at'] or '', reverse=True)

    return jsonify({'success': True, 'data': {
        'groups': groups,
        'singles': singles,
    }})


# ============================================================
# BULK ACTIONS
# ============================================================

@spav2_admin_bp.route('/reports/bulk', methods=['POST'])
@admin_required
def reports_bulk():
    data = request.get_json() or {}
    ids = data.get('ids') or []
    action = data.get('action')

    if not ids or action not in ('resolve', 'dismiss', 'ban_senders', 'delete_messages'):
        return jsonify({'success': False, 'error': {'code': 'VALIDATION', 'message': 'bad input'}}), 400

    reports = Report.query.filter(Report.id.in_(ids)).all()
    affected = 0

    if action in ('resolve', 'dismiss'):
        for r in reports:
            r.status = 'resolved' if action == 'resolve' else 'dismissed'
            affected += 1
    elif action == 'delete_messages':
        for r in reports:
            if r.reported_message_id:
                m = Message.query.get(r.reported_message_id)
                if m and not m.is_deleted:
                    m.is_deleted = True
                    m.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    affected += 1
            r.status = 'actioned_deleted'
    elif action == 'ban_senders':
        sender_ids = set()
        for r in reports:
            if r.reported_message_id:
                m = Message.query.get(r.reported_message_id)
                if m and m.sender_id:
                    sender_ids.add(m.sender_id)
        for uid in sender_ids:
            u = User.query.get(uid)
            if u and not u.is_admin and not u.is_deleted:
                u.is_deleted = True
                u.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
                affected += 1
        for r in reports:
            r.status = 'actioned_banned'

    db.session.commit()
    _audit(f'bulk_{action}', details={'report_ids': ids, 'affected': affected})
    return jsonify({'success': True, 'data': {'count': len(reports),
                                              'affected': affected,
                                              'action': action}})


# ============================================================
# RESTORE (for undo)
# ============================================================

@spav2_admin_bp.route('/users/<int:user_id>/restore', methods=['POST'])
@admin_required
def restore_user(user_id):
    u = User.query.get(user_id)
    if not u:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'User not found'}}), 404
    u.is_deleted = False
    u.deleted_at = None
    db.session.commit()
    _audit('user_restore', 'user', user_id)
    return jsonify({'success': True})


@spav2_admin_bp.route('/reports/<int:report_id>/restore', methods=['POST'])
@admin_required
def restore_report(report_id):
    r = Report.query.get(report_id)
    if not r:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Report not found'}}), 404
    r.status = 'pending'
    db.session.commit()
    _audit('report_restore', 'report', report_id)
    return jsonify({'success': True})


# ============================================================
# ADMIN NOTES
# ============================================================

@spav2_admin_bp.route('/users/<int:user_id>/notes', methods=['GET', 'POST'])
@admin_required
def user_notes(user_id):
    if request.method == 'GET':
        notes = (UserNote.query.filter_by(target_user_id=user_id)
                 .order_by(UserNote.created_at.desc()).all())
        return jsonify({'success': True, 'data': {'notes': [{
            'id': n.id,
            'body': n.body,
            'author_username': n.author.username if n.author else None,
            'created_at': n.created_at.isoformat() if n.created_at else None,
        } for n in notes]}})

    body = ((request.get_json() or {}).get('body') or '').strip()
    if not body:
        return jsonify({'success': False, 'error': {'code': 'VALIDATION', 'message': 'empty'}}), 400

    note = UserNote(
        target_user_id=user_id,
        author_id=get_current_user().id,
        body=body,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.session.add(note)
    db.session.commit()
    _audit('user_note_added', 'user', user_id)
    return jsonify({'success': True, 'data': {'id': note.id}})


@spav2_admin_bp.route('/users/<int:user_id>/notes/<int:note_id>', methods=['DELETE'])
@admin_required
def user_note_delete(user_id, note_id):
    note = UserNote.query.filter_by(id=note_id, target_user_id=user_id).first()
    if not note:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Note not found'}}), 404
    db.session.delete(note)
    db.session.commit()
    return jsonify({'success': True})


# ============================================================
# ACTION LOG PER USER
# ============================================================

@spav2_admin_bp.route('/users/<int:user_id>/action-log', methods=['GET'])
@admin_required
def user_action_log(user_id):
    rows = (AdminAction.query
            .filter_by(target_type='user', target_id=user_id)
            .order_by(AdminAction.created_at.desc())
            .limit(100).all())
    actor_ids = {a.actor_id for a in rows if a.actor_id}
    actors = {u.id: u.username for u in User.query.filter(User.id.in_(actor_ids)).all()} if actor_ids else {}
    return jsonify({'success': True, 'data': {'actions': [{
        'id': a.id,
        'action': a.action,
        'actor_username': actors.get(a.actor_id),
        'details': json.loads(a.details) if a.details else None,
        'created_at': a.created_at.isoformat() if a.created_at else None,
    } for a in rows]}})


# ============================================================
# SESSIONS
# ============================================================

@spav2_admin_bp.route('/users/<int:user_id>/sessions', methods=['GET'])
@admin_required
def user_sessions(user_id):
    rows = (UserSession.query.filter_by(user_id=user_id)
            .order_by(UserSession.created_at.desc()).limit(50).all())
    return jsonify({'success': True, 'data': {'sessions': [{
        'id': s.id,
        'ip': getattr(s, 'ip_address', None),
        'user_agent': getattr(s, 'user_agent', None),
        'last_active': getattr(s, 'last_active', None).isoformat() if getattr(s, 'last_active', None) else None,
        'created_at': s.created_at.isoformat() if s.created_at else None,
    } for s in rows]}})


@spav2_admin_bp.route('/users/<int:user_id>/sessions/<int:session_id>/revoke', methods=['POST'])
@admin_required
def user_session_revoke(user_id, session_id):
    s = UserSession.query.filter_by(id=session_id, user_id=user_id).first()
    if not s:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Session not found'}}), 404
    db.session.delete(s)
    db.session.commit()
    _audit('session_revoke', 'user', user_id, {'session_id': session_id})
    return jsonify({'success': True})


# ============================================================
# ACTIVITY FEED (SSE)
# ============================================================

@spav2_admin_bp.route('/activity/stream', methods=['GET'])
@admin_required
def activity_stream():
    since = request.args.get('since', 0, type=int)

    def gen():
        cursor = since
        while True:
            actions = (AdminAction.query
                       .filter(AdminAction.id > cursor)
                       .order_by(AdminAction.id.asc())
                       .limit(20).all())
            for a in actions:
                cursor = a.id
                actor = User.query.get(a.actor_id) if a.actor_id else None
                payload = {
                    'id': a.id,
                    'action': a.action,
                    'actor': actor.username if actor else 'system',
                    'target_type': a.target_type,
                    'target_id': a.target_id,
                    'created_at': a.created_at.isoformat() if a.created_at else None,
                }
                yield f"data: {json.dumps(payload)}\n\n"
            time.sleep(2)

    return Response(stream_with_context(gen()), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@spav2_admin_bp.route('/activity/recent', methods=['GET'])
@admin_required
def activity_recent():
    rows = AdminAction.query.order_by(AdminAction.id.desc()).limit(30).all()
    actor_ids = {a.actor_id for a in rows if a.actor_id}
    actors = {u.id: u.username for u in User.query.filter(User.id.in_(actor_ids)).all()} if actor_ids else {}
    return jsonify({'success': True, 'data': {'events': [{
        'id': a.id,
        'action': a.action,
        'actor': actors.get(a.actor_id, 'system'),
        'target_type': a.target_type,
        'target_id': a.target_id,
        'created_at': a.created_at.isoformat() if a.created_at else None,
    } for a in rows]}})


# ============================================================
# CHANGELOG
# ============================================================

@spav2_admin_bp.route('/changelog', methods=['GET'])
@admin_required
def changelog():
    return jsonify({'success': True, 'data': {'entries': [
        {'version': '3.3', 'date': '2026-10-20',
         'items': ['Report clustering', 'Keyword guesser', 'Bulk actions',
                   'Admin notes', 'SSE activity feed']},
        {'version': '3.2', 'date': '2026-09-12',
         'items': ['2FA cleanup', 'Terminal rate-limit', 'Mail account reset']},
        {'version': '3.1', 'date': '2026-08-04',
         'items': ['Promo codes', 'Channel creation']},
    ]}})