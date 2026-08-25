# app/__init__.py
import os
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, redirect, request, session, render_template, make_response, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_mail import Mail
from authlib.integrations.flask_client import OAuth

from flask_socketio import SocketIO

oauth = OAuth()
db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
mail = Mail()
socketio = SocketIO(cors_allowed_origins='*', async_mode='threading')

import platform

try:
    # freedesktop_os_release returns a dict of OS details
    info = platform.freedesktop_os_release()
    production = info.get("NAME") == "Ubuntu"
except (AttributeError, OSError):
    # Fallback for Windows/macOS or older Python versions where the method doesn't exist
    production = False

# Always respect DATABASE_URL env var (Docker deployment)
if os.environ.get('DATABASE_URL'):
    production = True



def create_app():
    from app.utils.helpers import get_current_user
    from app.utils.security import add_security_headers, generate_csrf_token, rate_limiter
    from app.models import User

    basedir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))

    app = Flask(__name__,
                template_folder=os.path.join(basedir, 'templates'),
                static_folder=os.path.join(basedir, 'static'),
                instance_path=os.path.join(basedir, 'instance')
                )

    # Load all config from config/kis.toml via the config module
    try:
        from app.config import Config
        app.config.from_object(Config())
    except Exception as e:
        print(f"⚠️ Error loading config: {e}")
        app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key')
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.instance_path, 'kiselgram.db')

    # Always enforce these
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Read encryption key from env (falls back to crypto.py's auto-detect)
    if os.environ.get('MESSAGE_ENCRYPTION_KEY'):
        app.config['MESSAGE_ENCRYPTION_KEY'] = os.environ['MESSAGE_ENCRYPTION_KEY']

    # Override database for production (env var required)
    if production:
        db_url = os.environ.get('DATABASE_URL')
        if not db_url:
            raise RuntimeError("DATABASE_URL environment variable is required in production mode")
        app.config['SQLALCHEMY_DATABASE_URI'] = db_url
        if not app.config.get('SECRET_KEY') or app.config['SECRET_KEY'] in ('dev-key', 'dev-secret-key-change-in-production'):
            sk = os.environ.get('SECRET_KEY')
            if not sk:
                raise RuntimeError("SECRET_KEY environment variable is required in production mode")
            app.config['SECRET_KEY'] = sk

    # Force debug off in production (safe override regardless of config)
    if production:
        app.config['DEBUG'] = False

    # Warn if debug is on
    if app.config.get('DEBUG'):
        print("⚠️  DEBUG mode is ON — do not expose this server to the internet")

    print(f"✅ Database URI: {app.config['SQLALCHEMY_DATABASE_URI']}")

    # Initialize extensions
    oauth.init_app(app)
    mail.init_app(app)

    # Register OAuth provider
    oauth.register(
        name='google',
        client_id=app.config.get('GOOGLE_CLIENT_ID', ''),
        client_secret=app.config.get('GOOGLE_CLIENT_SECRET', ''),
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'}
    )

    # Ensure instance folder exists
    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    socketio.init_app(app)

    # Register WebSocket notification namespace
    try:
        from app.notify_ws import init_notify_ws
        init_notify_ws(app, socketio)
    except Exception as e:
        app.logger.warning(f"Notify WebSocket not loaded: {e}")

    # ─── Security: headers, CSRF token context ───────────────────────────────
    app.after_request(add_security_headers)

    @app.context_processor
    def inject_csrf():
        return {'csrf_token': generate_csrf_token()}

    @app.teardown_appcontext
    def cleanup_rate_limiter(exc=None):
        rate_limiter.cleanup()

    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'

    @login_manager.user_loader
    def load_user(user_id):
        from app.models import User
        return User.query.get(int(user_id))

    # Register blueprints
    from app.routes import spa, spav2, premium, files
    from app.routes.utils_api import utils_api_bp
    spav2.Api2(app)
    spa.register_spa_blueprints(app)
    app.register_blueprint(premium.premium_bp)
    app.register_blueprint(files.files_bp)
    app.register_blueprint(utils_api_bp)

    # Register admin and push blueprints (new features)
    try:
        from app.routes.spav2.admin import spav2_admin_bp
        app.register_blueprint(spav2_admin_bp)
    except ImportError as e:
        app.logger.warning(f"Admin blueprint not loaded: {e}")
    try:
        from app.routes.spav2.push import spav2_push_bp
        app.register_blueprint(spav2_push_bp)
    except ImportError as e:
        app.logger.warning(f"Push blueprint not loaded: {e}")

    # Register video blueprint if enabled
    if app.config.get('VIDEO_ENABLED', False):
        try:
            from app.routes.video_integration import video_int_bp
            app.register_blueprint(video_int_bp)
        except ImportError as e:
            app.logger.warning(f"Video blueprint not loaded: {e}")

    # ================================================================
    # Nginx reverse proxy internal endpoint – returns the current user ID
    # ================================================================
    @app.route('/api/get_user_id')
    def get_user_id():
        user_id = session.get('user_id')
        if user_id is None:
            return '', 401
        resp = make_response('', 204)
        resp.headers['X-User-Id'] = str(user_id)
        return resp

    @app.route('/health')
    def health():
        return {'status': 'ok'}

    @app.route('/', methods=['GET'])
    def index():
        if request.host.startswith('admin.'):
            return redirect(url_for('spav2_admin.admin_page'))
        return render_template("kiselgram-home.html")

    @app.route('/logout', methods=['GET'])
    def logout():
        user_id = session.get('user_id')
        if user_id:
            user = User.query.get(user_id)
            if user:
                user.is_online = False
                user.last_seen = datetime.utcnow()
                db.session.commit()
        session.clear()
        return redirect('/auth/login')

    @app.route('/qr/<token>')
    def qr_login_page(token):
        return render_template('qr_login.html', token=token)

    @app.route('/join')
    def referral_join():
        ref = request.args.get('ref', '')
        if ref:
            return redirect(f'/k?ref={ref}')
        return redirect('/k')

    @app.route('/webapp/static')
    def webapp_static():
        return '<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Web App</title><style>body{margin:0;display:flex;align-items:center;justify-content:center;min-height:100vh;font-family:sans-serif;background:#1e1e2e;color:#f1f5f9;text-align:center}p{font-size:24px;opacity:0.6}</style></head><body><p>This is a web app &#127760;</p></body></html>', 200, {'Content-Type': 'text/html'}

    # Create tables if they don't exist (safe for concurrent workers)
    try:
        with app.app_context():
            db.create_all()
    except Exception:
        app.logger.warning("db.create_all() skipped (tables likely already exist)")

    # Background thread: cleanup expired stories every 30 minutes
    def story_cleanup_loop():
        with app.app_context():
            while True:
                try:
                    from app.models import Story
                    cutoff = datetime.utcnow() - timedelta(hours=24)
                    expired = Story.query.filter(Story.created_at < cutoff).all()
                    for story in expired:
                        if story.media_path:
                            p = os.path.join('uploads', story.media_path)
                            if os.path.exists(p):
                                os.remove(p)
                        if getattr(story, 'music_path', None):
                            p = os.path.join('uploads', story.music_path)
                            if os.path.exists(p):
                                os.remove(p)
                        db.session.delete(story)
                    db.session.commit()
                except Exception as e:
                    app.logger.error(f"Story cleanup error: {e}")
                time.sleep(1800)

    t = threading.Thread(target=story_cleanup_loop, daemon=True)
    t.start()

    return app