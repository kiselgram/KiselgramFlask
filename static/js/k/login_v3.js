K.loginV3 = {
  _state: {},
  _pollTimer: null,

  _hasClose() { return K.auth.accounts && K.auth.accounts.length > 0; },

  _v3Url(path) { return (K.api._base||V2).replace('api.v2', 'api.v3') + path; },

  _blankOverlay(blank) {
    const o = $('modalOverlay');
    if (blank) o.style.background = 'var(--bg-primary)';
    else o.style.background = '';
  },

  showPicker() {
    const blank = !K.loginV3._hasClose();
    K.loginV3._blankOverlay(blank);
    const o = $('modalOverlay'); o.style.display = 'flex';
    $('modalContent').innerHTML = `
      <div class="k-modal-header"><h3>Kiselgram</h3>${K.loginV3._hasClose() ? '<button class="k-modal-close" onclick="K.modals.close()"><i class="fas fa-times"></i></button>' : ''}</div>
      <div class="k-modal-body" style="text-align:center;padding:30px 20px">
        <p style="font-size:15px;margin-bottom:20px">Choose how to log in</p>
        <button class="k-btn k-btn-primary" style="width:100%;padding:14px;font-size:15px;margin-bottom:10px" onclick="K.loginV3._cleanup();K.loginV3.startEmail()">
          <i class="fas fa-envelope"></i> Email Login
        </button>
        <button class="k-btn k-btn-secondary" style="width:100%;padding:14px;font-size:15px;margin-bottom:10px" onclick="K.loginV3._cleanup();K.qrlogin.showQR()">
          <i class="fas fa-qrcode"></i> QR Code Login
        </button>
        <button class="k-btn k-btn-secondary" style="width:100%;padding:14px;font-size:15px;margin-bottom:10px" onclick="K.loginV3._cleanup();K.loginV3._guest()">
          <i class="fas fa-user-clock"></i> Guest Mode
        </button>
        <button class="k-btn k-btn-secondary" style="width:100%;padding:14px;font-size:15px;margin-bottom:10px" onclick="K.loginV3._cleanup();K.loginV3._stepFriend()">
          <i class="fas fa-user-plus"></i> I have a friend code
        </button>
        <div style="display:flex;align-items:center;gap:8px;margin:16px 0;opacity:0.4"><span style="flex:1;height:1px;background:var(--border-color)"></span><span style="font-size:12px;white-space:nowrap;color:var(--text-muted)">or continue with</span><span style="flex:1;height:1px;background:var(--border-color)"></span></div>
        <button class="k-oauth-btn k-oauth-google" style="width:100%;padding:12px;font-size:14px" onclick="K.auth.oauthLogin('google')">
          <svg viewBox="0 0 24 24" width="18" height="18"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>
          Google
        </button>
      </div>`;
  },

  _cleanup() {
    if (K.loginV3._pollTimer) { clearInterval(K.loginV3._pollTimer); K.loginV3._pollTimer = null; }
    K.loginV3._state = {};
  },

  // ── Friend code: skip email verification, friend vouches ───

  _stepFriend() {
    $('modalContent').innerHTML = `
      <div class="k-modal-header"><h3>Friend code</h3>${K.loginV3._closeBtn()}</div>
      <div class="k-modal-body" style="text-align:center">
        <p style="font-size:13px;color:var(--text-muted);margin-bottom:16px">Enter your friend's username — no email code needed, and they earn Premium!</p>
        <input class="k-input" id="v3FriendCode" placeholder="Friend's username" autocomplete="off" style="text-align:center;font-size:18px">
        <input class="k-input" id="v3FriendEmail" placeholder="Your email" autocomplete="off" style="text-align:center;font-size:16px">
        <div id="v3FriendError" style="font-size:12px;color:var(--error);margin-bottom:8px;display:none"></div>
        <button class="k-btn k-btn-primary" id="v3FriendBtn" style="width:100%;padding:12px;font-size:14px" onclick="K.loginV3._submitFriend()">Continue</button>
        <p style="margin-top:8px;font-size:12px"><a href="#" onclick="K.loginV3._cleanup();K.loginV3.showPicker();return false" style="color:var(--text-muted)">← Back</a></p>
      </div>`;
    setTimeout(() => $('v3FriendCode')?.focus(), 100);
    $('v3FriendCode').addEventListener('keydown', (e) => { if (e.key === 'Enter') K.loginV3._submitFriend(); });
    $('v3FriendEmail').addEventListener('keydown', (e) => { if (e.key === 'Enter') K.loginV3._submitFriend(); });
  },

  async _submitFriend() {
    const code = $('v3FriendCode')?.value?.trim().replace(/^@/, '');
    const email = $('v3FriendEmail')?.value?.trim().toLowerCase();
    const btn = $('v3FriendBtn'); const err = $('v3FriendError');
    if (!code) { err.textContent = 'Enter the friend code'; err.style.display = 'block'; return; }
    if (!email || !email.includes('@')) { err.textContent = 'Enter a valid email'; err.style.display = 'block'; return; }
    err.style.display = 'none';
    btn.disabled = true; btn.textContent = 'Checking...';
    try {
      const d = await K.api.post(K.loginV3._v3Url('/referrals/check'), { code });
      if (!d.success) { err.textContent = d.error?.message || 'Unknown friend code'; err.style.display = 'block'; btn.disabled = false; btn.textContent = 'Continue'; return; }
      K.loginV3._state.email = email;
      K.loginV3._state.ref = d.data.username;
      K.loginV3._state.friend_verified = true;
      try { sessionStorage.setItem('k_pending_ref', d.data.username); } catch (_) {}
      K.loginV3._stepRegFinish();
    } catch (e) {
      err.textContent = 'Connection error'; err.style.display = 'block'; btn.disabled = false; btn.textContent = 'Continue';
    }
  },

  // ── Version 1: Email Login ─────────────────────────────────

  startEmail() {
    K.loginV3._state = {};
    K.loginV3._renderStep('email');
  },

  _renderStep(step) {
    const o = $('modalOverlay'); o.style.display = 'flex';
    if (step === 'email') K.loginV3._stepEmail();
    else if (step === 'otp') K.loginV3._stepOtp();
    else if (step === 'pass') K.loginV3._stepPass();
    else if (step === 'reg-verify') K.loginV3._stepRegVerify();
    else if (step === 'reg-finish') K.loginV3._stepRegFinish();
    else if (step === 'done') K.loginV3._stepDone();
  },

  _closeBtn() {
    return K.loginV3._hasClose() ? '<button class="k-modal-close" onclick="K.modals.close()"><i class="fas fa-times"></i></button>' : '';
  },

  _stepEmail() {
    $('modalContent').innerHTML = `
      <div class="k-modal-header"><h3>Sign in</h3>${K.loginV3._closeBtn()}</div>
      <div class="k-modal-body" style="text-align:center">
        <p style="font-size:13px;color:var(--text-muted);margin-bottom:16px">Enter your email to get started</p>
        <input class="k-input" id="v3Email" type="email" placeholder="your@email.com" autocomplete="email" style="text-align:center;font-size:16px">
        <div id="v3EmailError" style="font-size:12px;color:var(--error);margin-bottom:8px;display:none"></div>
        <button class="k-btn k-btn-primary" id="v3EmailBtn" style="width:100%;padding:12px;font-size:14px" onclick="K.loginV3._submitEmail()">Continue</button>
        <p style="margin-top:12px;font-size:12px"><a href="#" onclick="K.loginV3._cleanup();K.loginV3.showPicker();return false" style="color:var(--text-muted)">← Back</a></p>
      </div>`;
    setTimeout(() => $('v3Email')?.focus(), 100);
    $('v3Email').addEventListener('keydown', (e) => { if (e.key === 'Enter') K.loginV3._submitEmail(); });
  },

  async _submitEmail() {
    const email = $('v3Email')?.value?.trim().toLowerCase();
    const btn = $('v3EmailBtn'); const err = $('v3EmailError');
    if (!email || !email.includes('@')) { err.textContent = 'Enter a valid email'; err.style.display = 'block'; return; }
    err.style.display = 'none';
    btn.disabled = true; btn.textContent = 'Checking...';
    try {
      const d = await K.api.post(K.loginV3._v3Url('/auth/check-email'), {email});
      if (!d.success) { err.textContent = d.error?.message || 'Error'; err.style.display = 'block'; btn.disabled = false; btn.textContent = 'Continue'; return; }
      K.loginV3._state.email = email;
      if (d.data.exists) {
        K.loginV3._state.exists = true;
        K.loginV3._stepOtp();
      } else {
        K.loginV3._state.exists = false;
        K.loginV3._stepRegVerify();
      }
    } catch(e) {
      err.textContent = 'Connection error'; err.style.display = 'block'; btn.disabled = false; btn.textContent = 'Continue';
    }
  },

  _stepOtp() {
    $('modalContent').innerHTML = `
      <div class="k-modal-header"><h3>Check your chat</h3>${K.loginV3._closeBtn()}</div>
      <div class="k-modal-body">
        <div id="v3OtpWidget"></div>
      </div>`;
    K.loginV3._sendOtp();
    if (window.K && K.otpWidget) {
      K.otpWidget.mount($('v3OtpWidget'), {
        digits: 5,
        bare: true,
        texts: {
          title: 'Enter login code',
          loadingTitle: 'Verifying...',
          loadingSubtitle: 'Checking the code.',
          successTitle: 'Verified',
          successSubtitle: 'Welcome back!',
          errorTitle: 'Wrong code',
          badge: 'OK',
          errorText: 'Incorrect code. Please try again.',
          resend: "Didn't get it? <span>Resend</span>",
          resendWait: "Didn't get it? <span>Wait…</span>",
        },
        subtitle: 'A 5-digit code was sent to your Kiselgram chat',
        verify: async (code) => {
          try {
            const d = await K.api.post(K.loginV3._v3Url('/auth/verify-otp'), {email: K.loginV3._state.email, code});
            if (!d.success) return {ok: false, error: d.error?.message || 'Invalid code'};
            K.loginV3._state.otp_verified = true;
            return {ok: true};
          } catch(e) { return {ok: false, error: 'Connection error'}; }
        },
        resend: () => K.loginV3._sendOtp(),
        onSuccess: () => K.loginV3._stepPass(),
      });
      return;
    }
    // Fallback when the widget script is not loaded.
    $('modalContent').innerHTML = `
      <div class="k-modal-header"><h3>Check your chat</h3>${K.loginV3._closeBtn()}</div>
      <div class="k-modal-body" style="text-align:center">
        <p style="font-size:13px;color:var(--text-muted);margin-bottom:16px">We sent a code to your Kiselgram chat</p>
        <input class="k-input" id="v3Otp" type="text" inputmode="numeric" maxlength="5" placeholder="00000" style="text-align:center;font-size:24px;letter-spacing:8px;font-family:monospace">
        <div id="v3OtpError" style="font-size:12px;color:var(--error);margin-bottom:8px;display:none"></div>
        <button class="k-btn k-btn-primary" id="v3OtpBtn" style="width:100%;padding:12px;font-size:14px" onclick="K.loginV3._submitOtp()">Verify Code</button>
        <p style="margin-top:8px;font-size:12px"><a href="#" onclick="K.loginV3._sendOtp();return false" style="color:var(--accent-blue)">Resend code</a></p>
      </div>`;
    setTimeout(() => $('v3Otp')?.focus(), 100);
    $('v3Otp').addEventListener('keydown', (e) => { if (e.key === 'Enter') K.loginV3._submitOtp(); });
  },

  async _sendOtpEmail() {
    try {
      await K.api.post(K.loginV3._v3Url('/auth/send-otp-email'), {email: K.loginV3._state.email});
      K.ui.toast('Code sent to your email', 'success');
    } catch(_) {
      K.ui.toast('Failed to send email', 'error');
    }
  },

  async _sendOtp() {
    try { await K.api.post(K.loginV3._v3Url('/auth/send-otp'), {email: K.loginV3._state.email}); } catch(_) { K.ui.toast('Failed to send OTP', 'error'); }
  },

  async _submitOtp() {
    const code = $('v3Otp')?.value?.trim();
    const btn = $('v3OtpBtn'); const err = $('v3OtpError');
    if (!code || code.length < 4) { err.textContent = 'Enter the code from your chat'; err.style.display = 'block'; return; }
    err.style.display = 'none';
    btn.disabled = true; btn.textContent = 'Verifying...';
    try {
      const d = await K.api.post(K.loginV3._v3Url('/auth/verify-otp'), {email: K.loginV3._state.email, code});
      if (!d.success) { err.textContent = d.error?.message || 'Invalid code'; err.style.display = 'block'; btn.disabled = false; btn.textContent = 'Verify Code'; return; }
      K.loginV3._state.otp_verified = true;
      K.loginV3._stepPass();
    } catch(e) {
      err.textContent = 'Connection error'; err.style.display = 'block'; btn.disabled = false; btn.textContent = 'Verify Code';
    }
  },

  _stepPass() {
    $('modalContent').innerHTML = `
      <div class="k-modal-header"><h3>Enter password</h3>${K.loginV3._closeBtn()}</div>
      <div class="k-modal-body" style="text-align:center">
        <p style="font-size:13px;color:var(--text-muted);margin-bottom:16px">Enter your password for <b>${esc(K.loginV3._state.email)}</b></p>
        <input class="k-input" id="v3Pass" type="password" placeholder="Password" autocomplete="current-password" style="text-align:center;font-size:16px">
        <div id="v3PassError" style="font-size:12px;color:var(--error);margin-bottom:8px;display:none"></div>
        <button class="k-btn k-btn-primary" id="v3PassBtn" style="width:100%;padding:12px;font-size:14px" onclick="K.loginV3._submitPass()">Sign in</button>
        <p style="margin-top:8px;font-size:12px"><a href="#" onclick="K.loginV3._loginOtpOnly();return false" style="color:var(--text-muted)">Skip password (less secure)</a></p>
      </div>`;
    setTimeout(() => $('v3Pass')?.focus(), 100);
    $('v3Pass').addEventListener('keydown', (e) => { if (e.key === 'Enter') K.loginV3._submitPass(); });
  },

  async _loginOtpOnly() {
    const btn = $('v3PassBtn'); const err = $('v3PassError');
    btn.disabled = true; btn.textContent = 'Signing in...';
    try {
      const d = await K.api.post(K.loginV3._v3Url('/auth/login-otp-only'), {
        email: K.loginV3._state.email,
        otp_verified: true,
      });
      if (!d.success) { err.textContent = d.error?.message || 'Error'; err.style.display = 'block'; btn.disabled = false; btn.textContent = 'Sign in'; return; }
      K.loginV3._state.session_token = d.data.session_token;
      K.loginV3._state.user = d.data.user;
      K.loginV3._finalizeLogin();
    } catch(e) {
      err.textContent = 'Connection error'; err.style.display = 'block'; btn.disabled = false; btn.textContent = 'Sign in';
    }
  },

  async _submitPass() {
    const password = $('v3Pass')?.value;
    const btn = $('v3PassBtn'); const err = $('v3PassError');
    if (!password) { err.textContent = 'Enter your password'; err.style.display = 'block'; return; }
    err.style.display = 'none';
    btn.disabled = true; btn.textContent = 'Signing in...';
    try {
      const d = await K.api.post(K.loginV3._v3Url('/auth/login-password'), {
        email: K.loginV3._state.email,
        password,
        otp_verified: true,
      });
      if (!d.success) { err.textContent = d.error?.message || 'Invalid password'; err.style.display = 'block'; btn.disabled = false; btn.textContent = 'Sign in'; return; }
      K.loginV3._state.session_token = d.data.session_token;
      K.loginV3._state.user = d.data.user;
      K.loginV3._finalizeLogin();
    } catch(e) {
      err.textContent = 'Connection error'; err.style.display = 'block'; btn.disabled = false; btn.textContent = 'Sign in';
    }
  },

  _stepRegVerify() {
    K.loginV3._sendRegCode();
    const email = K.loginV3._state.email;
    if (window.K && K.otpWidget) {
      $('modalContent').innerHTML = `
        <div class="k-modal-header"><h3>Verify email</h3>${K.loginV3._closeBtn()}</div>
        <div class="k-modal-body"><div id="v3RegWidget"></div></div>`;
      K.otpWidget.mount($('v3RegWidget'), {
        digits: 5,
        bare: true,
        texts: {
          title: 'Check your email',
          loadingTitle: 'Verifying...',
          loadingSubtitle: 'Checking the code.',
          successTitle: 'Email verified',
          successSubtitle: 'Creating your account…',
          errorTitle: 'Wrong code',
          badge: 'OK',
          errorText: 'Incorrect code. Please try again.',
          resend: "Didn't get it? <span>Resend</span>",
          resendWait: "Didn't get it? <span>Wait…</span>",
        },
        subtitle: 'A 5-digit code was sent to ' + email,
        verify: async (code) => {
          try {
            const d = await K.api.post(K.loginV3._v3Url('/auth/register-verify-code'), {email, code});
            if (!d.success) return {ok: false, error: d.error?.message || 'Invalid code'};
            K.loginV3._state.email_verified = true;
            return {ok: true};
          } catch(e) { return {ok: false, error: 'Connection error'}; }
        },
        resend: () => K.loginV3._sendRegCode(),
        onSuccess: () => K.loginV3._stepRegFinish(),
      });
      return;
    }
    $('modalContent').innerHTML = `
      <div class="k-modal-header"><h3>Verify email</h3>${K.loginV3._closeBtn()}</div>
      <div class="k-modal-body" style="text-align:center">
        <p style="font-size:13px;color:var(--text-muted);margin-bottom:16px">We sent a code to <b>${esc(K.loginV3._state.email)}</b></p>
        <input class="k-input" id="v3RegCode" type="text" inputmode="numeric" maxlength="5" placeholder="00000" style="text-align:center;font-size:24px;letter-spacing:8px;font-family:monospace">
        <div id="v3RegCodeError" style="font-size:12px;color:var(--error);margin-bottom:8px;display:none"></div>
        <button class="k-btn k-btn-primary" id="v3RegCodeBtn" style="width:100%;padding:12px;font-size:14px" onclick="K.loginV3._submitRegCode()">Verify Email</button>
        <p style="margin-top:8px;font-size:12px"><a href="#" onclick="K.loginV3._sendRegCode();return false" style="color:var(--accent-blue)">Resend code</a></p>
      </div>`;
    setTimeout(() => $('v3RegCode')?.focus(), 100);
    $('v3RegCode').addEventListener('keydown', (e) => { if (e.key === 'Enter') K.loginV3._submitRegCode(); });
  },

  async _sendRegCode() {
    try {
      const d = await K.api.post(K.loginV3._v3Url('/auth/register-send-code'), {email: K.loginV3._state.email});
      if (d && d.success && d.data && d.data.debug_code && K.ui && K.ui.toast) {
        K.ui.toast('Dev code: ' + d.data.debug_code, 'success');
      }
    } catch(_) { K.ui.toast('Failed to send code', 'error'); }
  },

  async _submitRegCode() {
    const code = $('v3RegCode')?.value?.trim();
    const btn = $('v3RegCodeBtn'); const err = $('v3RegCodeError');
    if (!code || code.length < 4) { err.textContent = 'Enter the code from your email'; err.style.display = 'block'; return; }
    err.style.display = 'none';
    btn.disabled = true; btn.textContent = 'Verifying...';
    try {
      const d = await K.api.post(K.loginV3._v3Url('/auth/register-verify-code'), {email: K.loginV3._state.email, code});
      if (!d.success) { err.textContent = d.error?.message || 'Invalid code'; err.style.display = 'block'; btn.disabled = false; btn.textContent = 'Verify Email'; return; }
      K.loginV3._state.email_verified = true;
      K.loginV3._stepRegFinish();
    } catch(e) {
      err.textContent = 'Connection error'; err.style.display = 'block'; btn.disabled = false; btn.textContent = 'Verify Email';
    }
  },

  async _stepRegFinish() {
    let avatars = [];
    try {
      const d = await K.api.get(K.loginV3._v3Url('/auth/preloaded-avatars'));
      if (d.success && d.data) avatars = d.data.avatars || [];
    } catch(_) {}
    const avatarHtml = avatars.length ? avatars.map((a, i) =>
      `<img src="/static/uploads/preloaded-avatars/${a}" class="k-avatar-option ${i===0?'selected':''}" data-avatar="${a}" onclick="document.querySelectorAll('.k-avatar-option').forEach(e=>e.classList.remove('selected'));this.classList.add('selected');K.loginV3._state.selectedAvatar='${esc(a)}'">`
    ).join('') : '<p style="font-size:12px;color:var(--text-muted)">No avatars available</p>';

    $('modalContent').innerHTML = `
      <div class="k-modal-header"><h3>Create account</h3>${K.loginV3._closeBtn()}</div>
      <div class="k-modal-body">
        <input class="k-input" id="v3RegUser" placeholder="Username" autocomplete="off" style="font-size:16px">
        <input class="k-input" id="v3RegName" placeholder="Display name" autocomplete="off" style="font-size:16px">
        <textarea class="k-input" id="v3RegBio" placeholder="Bio (optional)" style="font-size:14px;min-height:60px;resize:none"></textarea>
        <div style="margin-bottom:12px">
          <p style="font-size:12px;color:var(--text-muted);margin-bottom:6px">Pick an avatar</p>
          <div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:center">${avatarHtml}</div>
        </div>
        <div id="v3RegFinishError" style="font-size:12px;color:var(--error);margin-bottom:8px;display:none"></div>
        <button class="k-btn k-btn-primary" id="v3RegFinishBtn" style="width:100%;padding:12px;font-size:14px" onclick="K.loginV3._submitRegFinish()">Create Account</button>
      </div>`;
    if (avatars.length) K.loginV3._state.selectedAvatar = avatars[0];
    try {
      const ref = (window.K && K.invite) ? K.invite.pendingRef() : null;
      if (ref) {
        const note = document.createElement('p');
        note.style.cssText = 'font-size:12px;color:var(--text-muted);text-align:center;margin-bottom:8px';
        note.textContent = 'Invited by @' + ref + ' — they will earn Premium!';
        $('v3RegFinishBtn')?.before(note);
      }
    } catch (_) {}
    setTimeout(() => $('v3RegUser')?.focus(), 100);
    $('v3RegUser').addEventListener('keydown', (e) => { if (e.key === 'Enter') K.loginV3._submitRegFinish(); });
  },

  async _submitRegFinish() {
    const username = $('v3RegUser')?.value?.trim();
    const display_name = $('v3RegName')?.value?.trim();
    const bio = $('v3RegBio')?.value?.trim();
    const btn = $('v3RegFinishBtn'); const err = $('v3RegFinishError');
    if (!username) { err.textContent = 'Choose a username'; err.style.display = 'block'; return; }
    err.style.display = 'none';
    btn.disabled = true; btn.textContent = 'Creating...';
    try {
      const d = await K.api.post(K.loginV3._v3Url('/auth/register-finish'), {
        email: K.loginV3._state.email,
        username, display_name, bio,
        avatar: K.loginV3._state.selectedAvatar || '',
        email_verified: true,
        ref: K.loginV3._state.ref || '',
        friend_verified: !!K.loginV3._state.friend_verified,
      });
      if (!d.success) {
        const msg = d.error?.fields?.username || d.error?.message || 'Error';
        err.textContent = msg; err.style.display = 'block'; btn.disabled = false; btn.textContent = 'Create Account';
        return;
      }
      K.loginV3._state.session_token = d.data.session_token;
      K.loginV3._state.user = d.data.user;
      try {
        if (window.K && K.invite && d.data.user && d.data.user.user_id) {
          await K.invite.applyReferral(d.data.user.user_id);
        }
      } catch (_) {}
      K.loginV3._finalizeLogin();
    } catch(e) {
      err.textContent = 'Connection error'; err.style.display = 'block'; btn.disabled = false; btn.textContent = 'Create Account';
    }
  },

  _finalizeLogin() {
    const u = K.loginV3._state.user;
    if (!u || !K.loginV3._state.session_token) return;
    K.auth.accounts.push({
      username: u.username,
      displayName: u.display_name || u.username,
      avatarUrl: u.avatar_url || '',
      userId: u.user_id,
      token: K.loginV3._state.session_token,
    });
    K.auth.activeIdx = K.auth.accounts.length - 1;
    K.auth._save();
    K.auth.renderTabs();
    K.loginV3._stepDone();
  },

  _stepDone() {
    $('modalContent').innerHTML = `
      <div class="k-modal-header"><h3>Welcome!</h3></div>
      <div class="k-modal-body" style="text-align:center;padding:30px 20px">
        <div style="font-size:48px;margin-bottom:12px">🎉</div>
        <p style="font-size:15px;margin-bottom:6px">You're logged in as <b>${esc(K.loginV3._state.user?.display_name || K.loginV3._state.user?.username || '')}</b></p>
        <p style="font-size:13px;color:var(--text-muted);margin-bottom:20px">Version picker and chat list are loading...</p>
        <div style="color:var(--text-muted)"><i class="fas fa-spinner fa-spin"></i></div>
      </div>`;
    setTimeout(() => { K.modals.close(); K.loginV3._blankOverlay(false); location.reload(); }, 1500);
  },
};
