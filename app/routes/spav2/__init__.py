from flask import Blueprint

class Api2:
    def __init__(self, app=None,autoreg=True):
        self.spav2_bp = Blueprint("spav2_master", __name__, url_prefix="/api.v2")
        self.autoreg = autoreg
        if app is not None:
            self.app = app
            self.register(app)

    def init_app(self, app):
        self.app = app
        self.register(app)


    def _load_bps(self):
        from .auth import spav2_auth_bp
        from .chat import spav2_chat_bp
        from .groups import spav2_groups_bp
        from .channels import spav2_channels_bp
        from .contacts import spav2_contacts_bp
        from .stories import spav2_stories_bp
        from .profile import spav2_profile_bp
        from .calls import spav2_calls_bp
        from .search import spav2_search_bp
        from .sessions import spav2_sessions_bp
        from .messages import spav2_messages_bp
        from .saved import spav2_saved_bp
        from .music import spav2_music_bp
        from .ksettings import spav2_ksettings_bp
        from .oauth import spav2_oauth_bp
        from .referrals import spav2_referrals_bp
        from .features import spav2_features_bp
        from .sputnik import spav2_sputnik_bp
        return [
            spav2_auth_bp, spav2_chat_bp, spav2_groups_bp, spav2_channels_bp,
            spav2_contacts_bp, spav2_stories_bp, spav2_profile_bp, spav2_calls_bp,
            spav2_search_bp, spav2_sessions_bp, spav2_messages_bp, spav2_saved_bp,
            spav2_music_bp, spav2_ksettings_bp, spav2_oauth_bp, spav2_referrals_bp,
            spav2_features_bp, spav2_sputnik_bp,
        ]

    def register(self, app):
        bps = self._load_bps()

        spav2_bp = self.spav2_bp
        for bp in bps:
            spav2_bp.register_blueprint(bp)

        # v3-only: QR code login + multi-step login (also under /api.v2/ for desktop client)
        from .qr_login import spav2_qr_bp
        from .login_v3 import spav2_login_v3_bp
        spav2_bp.register_blueprint(spav2_qr_bp)
        spav2_bp.register_blueprint(spav2_login_v3_bp)

        app.register_blueprint(spav2_bp)

        # Stub: duplicate all V2 + V3 routes under /api.v3/
        spav2_stub_bp = Blueprint("spav2_master_stub", __name__, url_prefix="/api.v3")
        for bp in bps:
            spav2_stub_bp.register_blueprint(bp)
        spav2_stub_bp.register_blueprint(spav2_qr_bp)
        spav2_stub_bp.register_blueprint(spav2_login_v3_bp)

        app.register_blueprint(spav2_stub_bp)



