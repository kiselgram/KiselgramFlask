from flask import Blueprint, request, jsonify, session, current_app, url_for, render_template_string
from datetime import datetime, timezone
import secrets
import json
import requests
from app import db, oauth
from app.models import User, UserSession

spav2_oauth_bp = Blueprint('spav2_oauth', __name__, url_prefix='/api/auth/oauth')

PROVIDERS = {
    'google': {
        'id_field': 'google_id',
        'userinfo_url': 'https://www.googleapis.com/oauth2/v3/userinfo',
        'userinfo_fn': lambda info: {
            'provider_id': info.get('sub'),
            'email': info.get('email'),
            'name': info.get('name'),
            'picture': info.get('picture'),
        },
        'email_verified': True,
    },
    'github': {
        'id_field': 'github_id',
        'userinfo_url': 'https://api.github.com/user',
        'userinfo_fn': lambda info: {
            'provider_id': str(info.get('id')),
            'email': info.get('email'),
            'name': info.get('name') or info.get('login'),
            'picture': info.get('avatar_url'),
        },
        'email_verified': True,
    },
    'discord': {
        'id_field': 'discord_id',
        'userinfo_url': 'https://discord.com/api/users/@me',
        'userinfo_fn': lambda info: {
            'provider_id': info.get('id'),
            'email': info.get('email'),
            'name': info.get('global_name') or info.get('username'),
            'picture': f"https://cdn.discordapp.com/avatars/{info.get('id')}/{info.get('avatar')}.png" if info.get('avatar') else None,
        },
        'email_verified': True,
    },
}

CALLBACK_HTML = '''<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Redirecting...</title></head>
<body style="display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;background:#1e1e2e;color:#f1f5f9;font-family:sans-serif">
<p>Signing you in...</p>
<script>
(function() {
  var data = {{DATA}};
  if (window.opener) {
    window.opener.postMessage(data, '*');
    setTimeout(function() { window.close(); }, 500);
  } else {
    var msg = (data && data.error && data.error.message) ? data.error.message : (data.error || 'Account added! You can close this window.');
    document.body.innerHTML = '<p>' + msg + '</p><p style="font-size:12px;opacity:0.6">If this window does not close, <a href="/" style="color:#5e72e4">return to Kiselgram</a></p>';
    setTimeout(function() {
      try { window.location.href = '/?oauth_result=' + encodeURIComponent(JSON.stringify(data)); } catch(e) {}
    }, 1000);
  }
})();
<\/script>
</body></html>'''


def _fetch_userinfo(provider_name, token):
    cfg = PROVIDERS.get(provider_name)
    if not cfg:
        return None
    resp = requests.get(
        cfg['userinfo_url'],
        headers={'Authorization': f'Bearer {token["access_token"]}'}
    )
    if provider_name == 'github':
        gh_info = resp.json()
        if not gh_info.get('email'):
            emails_resp = requests.get(
                'https://api.github.com/user/emails',
                headers={'Authorization': f'Bearer {token["access_token"]}'}
            )
            emails = emails_resp.json()
            primary = next((e for e in emails if e.get('primary')), None)
            if primary:
                gh_info['email'] = primary.get('email')
        return cfg['userinfo_fn'](gh_info)
    return cfg['userinfo_fn'](resp.json())


def _find_or_create_user(provider_name, userinfo):
    cfg = PROVIDERS[provider_name]
    id_field = cfg['id_field']
    provider_id = userinfo['provider_id']
    email = userinfo.get('email')
    name = userinfo.get('name')
    picture = userinfo.get('picture')

    kwargs = {id_field: provider_id}
    user = User.query.filter_by(**kwargs).first()
    if not user:
        if email:
            user = User.query.filter_by(email=email).first()
        if not user:
            base_username = email.split('@')[0] if email else provider_name + '_user'
            username = base_username
            counter = 1
            while User.query.filter_by(username=username).first():
                username = f"{base_username}{counter}"
                counter += 1
            user = User(
                username=username,
                display_name=name,
                avatar_url=picture,
                email=email,
                email_verified=cfg['email_verified'],
                **kwargs,
            )
            db.session.add(user)
        else:
            setattr(user, id_field, provider_id)
            if not user.avatar_url:
                user.avatar_url = picture
            if not user.display_name:
                user.display_name = name
            if not user.email_verified and email == user.email:
                user.email_verified = True
    else:
        user.display_name = name
        user.avatar_url = picture
        if not user.email_verified:
            user.email_verified = True

    db.session.commit()
    return user


def _make_session(user):
    session_token = secrets.token_urlsafe(32)
    session['user_id'] = user.id
    session['username'] = user.username
    user.is_online = True
    user.last_seen = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.add(UserSession(
        user_id=user.id,
        session_token=session_token,
        device=f'{user.username} Web (OAuth)',
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        last_activity=datetime.now(timezone.utc).replace(tzinfo=None),
        is_active=True,
    ))
    db.session.commit()
    return session_token


@spav2_oauth_bp.route('/<provider>/login', methods=['GET'])
def oauth_login(provider):
    if provider not in PROVIDERS:
        return jsonify({'success': False, 'error': {'code': 'INVALID_PROVIDER', 'message': f'Unknown provider: {provider}'}}), 400

    redirect_uri = url_for('spav2_master.spav2_oauth.oauth_callback', provider=provider, _external=True)
    try:
        client = oauth.create_client(provider)
        return client.authorize_redirect(redirect_uri)
    except Exception as e:
        current_app.logger.error(f"OAuth {provider} login error: {e}")
        return jsonify({'success': False, 'error': {'code': 'OAUTH_ERROR', 'message': str(e)}}), 500


@spav2_oauth_bp.route('/<provider>/callback', methods=['GET'])
def oauth_callback(provider):
    if provider not in PROVIDERS:
        return jsonify({'success': False, 'error': {'code': 'INVALID_PROVIDER', 'message': f'Unknown provider: {provider}'}}), 400

    try:
        client = oauth.create_client(provider)
        token = client.authorize_access_token()
    except Exception as e:
        current_app.logger.error(f"OAuth {provider} callback token error: {e}")
        return render_template_string(CALLBACK_HTML.replace('{{DATA}}', json.dumps(
            {'success': False, 'error': {'code': 'OAUTH_FAILED', 'message': 'Authorization failed'}}
        )))

    userinfo = _fetch_userinfo(provider, token)
    if not userinfo or not userinfo.get('provider_id'):
        return render_template_string(CALLBACK_HTML.replace('{{DATA}}', json.dumps(
            {'success': False, 'error': {'code': 'OAUTH_FAILED', 'message': 'Failed to fetch user info'}}
        )))

    try:
        user = _find_or_create_user(provider, userinfo)
        session_token = _make_session(user)
    except Exception as e:
        current_app.logger.error(f"OAuth {provider} user creation error: {e}")
        db.session.rollback()
        return render_template_string(CALLBACK_HTML.replace('{{DATA}}', json.dumps(
            {'success': False, 'error': {'code': 'SERVER_ERROR', 'message': 'Failed to create session'}}
        )))

    success_data = json.dumps({
        'success': True,
        'data': {
            'user': {
                'user_id': user.id,
                'username': user.username,
                'email': user.email,
                'display_name': user.display_name or user.username,
                'avatar_url': user.avatar_url,
                'bio': getattr(user, 'bio', None),
                'is_premium': user.premium.is_premium if user.premium else False,
                'is_admin': getattr(user, 'is_admin', False),
                'is_online': True,
                'last_seen': datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
                'created_at': user.created_at.isoformat() if user.created_at else datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            },
            'session_token': session_token,
        },
    })
    return render_template_string(CALLBACK_HTML.replace('{{DATA}}', success_data))
