const SPLASH_FADE_DURATION = 600;
const SPLASH_STEP_PCT = 5;
const SPLASH_MAX_PCT = 100;
const SPLASH_STEP_INTERVAL = 100;
const SPLASH_HIDE_DELAY = 2000;
const HASH_ROUTE_DELAY = 500;
const REDIRECT_DELAY = 2200;
const AUTH_FOCUS_DELAY = 100;
const RELOAD_DELAY = 500;
const QR_CODE_SIZE = 200;
const QR_DEFAULT_EXPIRES = 120;
const QR_POLL_INTERVAL = 2000;
const QR_COUNTDOWN_INTERVAL = 1000;
const OAUTH_POPUP_WIDTH = 600;
const OAUTH_POPUP_HEIGHT = 700;
const OAUTH_POPUP_LEFT = 200;
const OAUTH_POPUP_TOP = 100;
const POPUP_CHECK_INTERVAL = 1000;

K.auth = {
  accounts: (() => { try { return JSON.parse(localStorage.getItem('k_accounts') || '[]'); } catch(e) { return []; } })(),
  activeIdx: (() => { try { return parseInt(localStorage.getItem('k_active_idx') || '0', 10); } catch(e) { return 0; } })(),

  hideSplash() {
    const s = $('splashScreen'); if (s) { s.classList.add('fade-out'); setTimeout(() => { if (s) s.style.display = 'none'; }, SPLASH_FADE_DURATION); }
  },
  _startSplashTimer() {
    const fill = $('splashFill'); if (!fill) return;
    let pct = 0;
    const step = () => { pct += SPLASH_STEP_PCT; fill.style.width = Math.min(pct, SPLASH_MAX_PCT) + '%'; if (pct < SPLASH_MAX_PCT) setTimeout(step, SPLASH_STEP_INTERVAL); };
    step();
    setTimeout(() => K.auth.hideSplash(), SPLASH_HIDE_DELAY);
  },
  async init() {
    if (typeof K.chat._initActions === 'function') K.chat._initActions();
    K.auth._startSplashTimer();

    // Hash-based routing: /k#login or /k#register
    const hash = window.location.hash.replace('#', '');
    if (hash === 'login' || hash === 'register') {
      setTimeout(() => { K.loginV3.showPicker(); }, HASH_ROUTE_DELAY);
      window.location.hash = '';
    }

    if (this.accounts.length > 0) K.auth.activeIdx = Math.min(K.auth.activeIdx, this.accounts.length - 1);
    try {
      const d = await K.api.get(V2 + '/profile');
      if (d.success && d.data) {
        K.state.user = d.data;
        K.ui.renderUser();
        K.auth.renderTabs();
        K.chat.loadList();
        K.contacts.load();
        K.stories.load();
        K.settings.loadPrivacy();
        K.settings.loadSessions();
        K.saved.load();
        K.calls.connectNotify();
        return;
      }
    } catch(e) { console.warn('K init error', e); }
    if (this.accounts.length > 0) {
      this.removeAccount(this.activeIdx);
      location.reload();
    } else {
      if (hash !== 'login' && hash !== 'register') {
        setTimeout(() => { window.location.href = '/'; }, REDIRECT_DELAY);
      }
    }
  },
  async login(username, password) {
    try {
      const d = await K.api.post(V2 + '/auth/login', {username, password});
      if (d.success && d.data && d.data.session_token) {
        const u = d.data.user;
        this.accounts.push({username: u.username, displayName: u.display_name || u.username, avatarUrl: u.avatar_url || '', userId: u.user_id, token: d.data.session_token});
        this.activeIdx = this.accounts.length - 1;
        this._save();
        K.auth.renderTabs();
        return {success: true};
      }
      return {success: false, error: d.error?.message || 'Login failed'};
    } catch(e) {
      return {success: false, error: e.body?.error?.message || e.message || 'Invalid credentials'};
    }
  },
  async register(username, email, password) {
    try {
      const d = await K.api.post(V2 + '/auth/register', {username, email, password});
      if (d.success && d.data && d.data.session_token) {
        const u = d.data.user;
        this.accounts.push({username: u.username, displayName: u.display_name || u.username, avatarUrl: u.avatar_url || '', userId: u.user_id, token: d.data.session_token});
        this.activeIdx = this.accounts.length - 1;
        this._save();
        K.auth.renderTabs();
        return {success: true};
      }
      return {success: false, error: d.error?.message || 'Registration failed'};
    } catch(e) {
      return {success: false, error: e.body?.error?.message || e.message || 'Server error'};
    }
  },
  switchAccount(idx) {
    if (idx === this.activeIdx || idx < 0 || idx >= this.accounts.length) return;
    this.activeIdx = idx;
    this._save();
    location.reload();
  },
  removeAccount(idx) {
    if (idx < 0 || idx >= this.accounts.length) return;
    this.accounts.splice(idx, 1);
    if (this.activeIdx >= this.accounts.length) this.activeIdx = Math.max(0, this.accounts.length - 1);
    this._save();
  },
  async logout() {
    if (await K.ui.confirm('Sign out?')) {
      try { await K.api.post(V2 + '/auth/logout'); } catch(_) {}
      const wasActive = this.activeIdx;
      this.accounts.splice(wasActive, 1);
      if (this.accounts.length === 0) { this._save(); window.location.href = '/'; return; }
      if (this.activeIdx >= this.accounts.length) this.activeIdx = 0;
      this._save();
      location.reload();
    }
  },
  renderTabs() {
    const c = $('accountTabs'); if (!c) return;
    c.innerHTML = this.accounts.map((a, i) =>
      `<div class="k-acc-tab ${i === K.auth.activeIdx ? 'active' : ''}" onclick="K.auth.switchAccount(${i})" title="${esc(a.displayName)}">${esc(a.username[0] || '?').toUpperCase()}</div>`
    ).join('') + `<div class="k-acc-tab k-acc-add" onclick="K.loginV3.showPicker()" title="Add account">+</div>`;
  },
  showAddAccount() {
    const o = $('modalOverlay'); if (o) o.style.display = 'flex';
    const mc = $('modalContent'); if (mc) mc.innerHTML = `
      <div class="k-modal-header"><h3>Add Account</h3><button class="k-modal-close" onclick="K.modals.close()"><i class="fas fa-times"></i></button></div>
      <div class="k-modal-body">
        <input class="k-input" id="loginUser" placeholder="Username" autocomplete="off">
        <input class="k-input" type="password" id="loginPass" placeholder="Password">
        <div id="loginExtra" style="display:none">
          <input class="k-input" id="loginEmail" placeholder="Email" autocomplete="off">
        </div>
        <p style="font-size:12px;color:var(--text-muted);margin-top:-4px">
          <span id="loginToggleText">Don't have an account?</span>
          <a href="#" onclick="K.auth.toggleLoginMode();return false" id="loginToggleLink" style="color:var(--accent-blue)">Register</a>
        </p>
        <div class="k-oauth-divider"><span>or</span></div>
        <button class="k-btn k-btn-secondary" style="width:100%;margin-bottom:8px" onclick="K.auth.showQRRequest()">
          <i class="fas fa-qrcode"></i> Log in with QR
        </button>
        <div class="k-oauth-divider"><span>or continue with</span></div>
        <div class="k-oauth-buttons">
          <button class="k-oauth-btn k-oauth-google" onclick="K.auth.oauthLogin('google')">
            <svg viewBox="0 0 24 24" width="18" height="18"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>
            Google
          </button>
          <button class="k-oauth-btn k-oauth-github" onclick="K.auth.oauthLogin('github')">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z"/></svg>
            GitHub
          </button>
          <button class="k-oauth-btn k-oauth-discord" onclick="K.auth.oauthLogin('discord')">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028 14.09 14.09 0 0 0 1.226-1.994.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"/></svg>
            Discord
          </button>
        </div>
      </div>
      <div class="k-modal-footer">
        <button class="k-btn k-btn-secondary" onclick="K.modals.close()">Cancel</button>
        <button class="k-btn k-btn-primary" id="loginBtn" onclick="K.auth.doAddAccount()">Login</button>
      </div>`;
    K.auth._loginMode = 'login';
    setTimeout(() => $('loginUser')?.focus(), AUTH_FOCUS_DELAY);
  },

  showQRRequest() {
    const o = $('modalOverlay'); if (o) o.style.display = 'flex';
    const mc = $('modalContent'); if (mc) mc.innerHTML = `
      <div class="k-modal-header"><h3>QR Login</h3><button class="k-modal-close" onclick="K.modals.close()"><i class="fas fa-times"></i></button></div>
      <div class="k-modal-body" style="text-align:center">
        <p style="font-size:13px;color:var(--text-muted);margin-bottom:12px">Scan this QR with a device that's already logged in</p>
        <div id="qrRequestContainer" style="display:flex;justify-content:center;min-height:200px;align-items:center">
          <div style="color:var(--text-muted)"><i class="fas fa-spinner fa-spin"></i> Generating...</div>
        </div>
        <div id="qrRequestStatus" style="margin-top:10px;font-size:13px;color:var(--text-muted)"></div>
        <div id="qrRequestExpires" style="margin-top:4px;font-size:12px;color:var(--text-muted)"></div>
      </div>
      <div class="k-modal-footer" style="justify-content:center">
        <button class="k-btn k-btn-secondary" onclick="K.auth._qrCleanup();K.auth.showAddAccount()">Back</button>
        <button class="k-btn k-btn-secondary" onclick="K.auth._qrCleanup();K.modals.close()">Close</button>
      </div>`;
    K.auth._qrRequest();
  },

  async _qrRequest() {
    try {
      const d = await K.api.post(V3 + '/auth/qr/request');
      if (!d.success || !d.data) {
        $('qrRequestContainer').innerHTML = '<div style="color:var(--error)">Failed</div>';
        return;
      }
      const token = d.data.token;
      const container = $('qrRequestContainer');
      container.innerHTML = '<div id="qrReqCanvas" style="border-radius:12px;overflow:hidden"></div>';
      new QRCode('qrReqCanvas', {text: token, width: QR_CODE_SIZE, height: QR_CODE_SIZE, colorDark: '#000000', colorLight: '#ffffff'});
      $('qrRequestStatus').textContent = 'Waiting for authorization...';
      K.auth._qrStartPoll(token);
      K.auth._qrStartCountdown(d.data.expires_in || QR_DEFAULT_EXPIRES, 'qrRequestExpires');
    } catch(e) {
      $('qrRequestContainer').innerHTML = '<div style="color:var(--error)">Connection error</div>';
    }
  },

  async _qrStartPoll(token) {
    K.auth._qrStopPoll();
    K.auth._qrTimer = setInterval(async () => {
      try {
        const d = await K.api.get(V3 + '/auth/qr/status/' + token);
        if (d.success && d.data) {
          if (d.data.authorized && !d.data.consumed) {
            K.auth._qrStopPoll();
            $('qrRequestStatus').innerHTML = '<span style="color:var(--success)"><i class="fas fa-check-circle"></i> Authorized! Logging in...</span>';
            try {
              const r = await K.api.post(V3 + '/auth/qr/login', {token});
              if (r.success && r.data && r.data.session_token) {
                const u = r.data.user;
                K.auth.accounts.push({username: u.username, displayName: u.display_name || u.username, avatarUrl: u.avatar_url || '', userId: u.user_id, token: r.data.session_token});
                K.auth.activeIdx = K.auth.accounts.length - 1;
                K.auth._save();
                K.auth.renderTabs();
                K.modals.close();
                K.ui.toast('Logged in!', 'success');
                setTimeout(() => location.reload(), RELOAD_DELAY);
              }
            } catch(_) { K.auth._qrStopPoll(); return; }
          } else if (d.data.consumed || d.data.expired) {
            K.auth._qrStopPoll();
            $('qrRequestStatus').innerHTML = '<span style="color:var(--error)">Expired. <a href="#" onclick="K.auth._qrRequest();return false" style="color:var(--accent-blue)">Regenerate</a></span>';
          }
        }
      } catch(_) { K.auth._qrStopPoll(); }
    }, QR_POLL_INTERVAL);
  },

  _qrStartCountdown(seconds, elId) {
    const el = $(elId);
    if (!el) return;
    let remaining = seconds;
    el.textContent = 'Expires in ' + remaining + 's';
    clearInterval(K.auth._qrCountdown);
    K.auth._qrCountdown = setInterval(() => {
      remaining--;
      if (remaining <= 0) { clearInterval(K.auth._qrCountdown); el.textContent = 'Expired'; }
      else el.textContent = 'Expires in ' + remaining + 's';
    }, QR_COUNTDOWN_INTERVAL);
  },

  _qrStopPoll() {
    if (K.auth._qrTimer) { clearInterval(K.auth._qrTimer); K.auth._qrTimer = null; }
    if (K.auth._qrCountdown) { clearInterval(K.auth._qrCountdown); K.auth._qrCountdown = null; }
  },

  _qrCleanup() {
    K.auth._qrStopPoll();
    K.auth._qrRequestToken = null;
  },
  toggleLoginMode() {
    const extra = $('loginExtra'); const btn = $('loginBtn');
    const tl = $('loginToggleLink'); const tt = $('loginToggleText');
    if (K.auth._loginMode === 'login') {
      K.auth._loginMode = 'register';
      if (extra) extra.style.display = 'block';
      if (btn) btn.textContent = 'Register';
      if (tl) tl.textContent = 'Login';
      if (tt) tt.textContent = 'Already have an account? ';
    } else {
      K.auth._loginMode = 'login';
      if (extra) extra.style.display = 'none';
      if (btn) btn.textContent = 'Login';
      if (tl) tl.textContent = 'Register';
      if (tt) tt.textContent = "Don't have an account? ";
    }
  },
  async doAddAccount() {
    const btn = $('loginBtn'); if (btn) btn.disabled = true;
    const user = $('loginUser')?.value?.trim();
    const pass = $('loginPass')?.value;
    if (!user || !pass) { K.ui.toast('Enter username and password', 'error'); if (btn) btn.disabled = false; return; }
    try {
      let r;
      if (K.auth._loginMode === 'register') {
        const email = $('loginEmail')?.value?.trim();
        if (!email) { K.ui.toast('Enter your email', 'error'); return; }
        r = await K.auth.register(user, email, pass);
      } else {
        r = await K.auth.login(user, pass);
      }
      if (r.success) { K.modals.close(); K.ui.toast('Account added', 'success'); setTimeout(() => location.reload(), RELOAD_DELAY); }
      else { K.ui.toast(r.error || 'Failed', 'error'); }
    } catch(e) { K.ui.toast('Connection error', 'error'); }
    if (btn) btn.disabled = false;
  },
  async oauthLogin(provider) {
    const popup = window.open(V2 + '/auth/oauth/' + provider + '/login', 'oauth', `width=${OAUTH_POPUP_WIDTH},height=${OAUTH_POPUP_HEIGHT},left=${OAUTH_POPUP_LEFT},top=${OAUTH_POPUP_TOP}`);
    if (!popup) { K.ui.toast('Please allow popups for this site', 'error'); return; }
    if (K.auth._oauthHandler) window.removeEventListener('message', K.auth._oauthHandler);
    K.auth._oauthHandler = async (e) => {
      if (e.source !== popup) return;
      try {
        const data = typeof e.data === 'string' ? JSON.parse(e.data) : e.data;
        if (data.success && data.data && data.data.session_token) {
          const u = data.data.user;
          K.auth.accounts.push({username: u.username, displayName: u.display_name || u.username, avatarUrl: u.avatar_url || '', userId: u.user_id, token: data.data.session_token});
          K.auth.activeIdx = K.auth.accounts.length - 1;
          K.auth._save();
          K.auth.renderTabs();
          K.modals.close();
          K.ui.toast('Account added', 'success');
          setTimeout(() => location.reload(), RELOAD_DELAY);
        } else {
          K.ui.toast(data.error?.message || 'OAuth failed', 'error');
        }
      } catch(_) { K.ui.toast('OAuth login failed', 'error'); }
      window.removeEventListener('message', K.auth._oauthHandler);
      K.auth._oauthHandler = null;
    };
    window.addEventListener('message', K.auth._oauthHandler);
    const checkClosed = setInterval(() => {
      if (popup.closed) {
        clearInterval(checkClosed);
        if (K.auth._oauthHandler) {
          window.removeEventListener('message', K.auth._oauthHandler);
          K.auth._oauthHandler = null;
        }
      }
    }, POPUP_CHECK_INTERVAL);
  },
  _save() {
    localStorage.setItem('k_accounts', JSON.stringify(this.accounts));
    localStorage.setItem('k_active_idx', String(this.activeIdx));
  }
};
