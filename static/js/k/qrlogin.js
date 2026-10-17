K.qrlogin = {
  _timer: null,
  _countdownTimer: null,
  _currentToken: null,
  _isUnAuth: false,

  showQR() {
    const blank = !K.loginV3._hasClose();
    K.loginV3._blankOverlay(blank);
    K.qrlogin._isUnAuth = !K.loginV3._hasClose();
    const o = $('modalOverlay'); o.style.display = 'flex';
    const modeHtml = K.qrlogin._isUnAuth ? '' : `
      <div class="k-qr-mode-select" style="display:flex;gap:8px;margin-bottom:16px">
        <button class="k-btn k-btn-primary" id="qrModeShow" style="flex:1" onclick="K.qrlogin._switchMode('show')">Get scanned</button>
        <button class="k-btn k-btn-secondary" id="qrModeScan" style="flex:1" onclick="K.qrlogin._switchMode('scan')">Scan QR</button>
      </div>`;
    const qrClose = K.loginV3._hasClose() ? '<button class="k-modal-close" onclick="K.qrlogin._cleanup();K.modals.close()"><i class="fas fa-times"></i></button>' : '';
    $('modalContent').innerHTML = `
      <div class="k-modal-header"><h3>QR Code Login</h3>${qrClose}</div>
      <div class="k-modal-body" style="text-align:center">
        ${modeHtml}
        <div id="qrBody">
          <p style="font-size:13px;color:var(--text-muted);margin-bottom:12px">${K.qrlogin._isUnAuth ? 'Scan this QR with a logged-in device to authorize login' : 'Scan this code with another device to log in'}</p>
          <div id="qrCodeContainer" style="display:flex;justify-content:center;min-height:200px;align-items:center">
            <div style="color:var(--text-muted)"><i class="fas fa-spinner fa-spin"></i> Generating...</div>
          </div>
          <div id="qrStatus" style="margin-top:10px;font-size:13px;color:var(--text-muted)"></div>
          <div id="qrExpires" style="margin-top:4px;font-size:12px;color:var(--text-muted)"></div>
        </div>
        <div id="qrScanBody" style="display:none;text-align:center">
          <p style="font-size:13px;color:var(--text-muted);margin-bottom:12px">Point your camera at the QR code shown on the other device</p>
          <input class="k-input" id="qrTokenInput" placeholder="Or paste the token here" style="text-align:center;font-family:monospace;font-size:14px">
          <button class="k-btn k-btn-primary" onclick="K.qrlogin._doScan()" style="width:100%">Authorize Login</button>
          <div id="qrScanStatus" style="margin-top:10px;font-size:13px;color:var(--text-muted)"></div>
        </div>
      </div>`;
    K.qrlogin._mode = 'show';
    K.qrlogin._generate();
  },

  _switchMode(mode) {
    K.qrlogin._cleanup();
    K.qrlogin._mode = mode;
    $('qrModeShow').className = mode === 'show' ? 'k-btn k-btn-primary' : 'k-btn k-btn-secondary';
    $('qrModeScan').className = mode === 'scan' ? 'k-btn k-btn-primary' : 'k-btn k-btn-secondary';
    if (mode === 'show') {
      $('qrBody').style.display = 'block';
      $('qrScanBody').style.display = 'none';
      K.qrlogin._generate();
    } else {
      $('qrBody').style.display = 'none';
      $('qrScanBody').style.display = 'block';
    }
  },

  async _generate() {
    try {
      const ep = K.qrlogin._isUnAuth ? '/auth/qr/request' : '/auth/qr/generate';
      const d = await K.api.post(V3 + ep);
      if (!d.success || !d.data) {
        $('qrCodeContainer').innerHTML = '<div style="color:var(--error)">Failed to generate QR code</div>';
        return;
      }
      K.qrlogin._currentToken = d.data.token;
      const container = $('qrCodeContainer');
      container.innerHTML = '<div id="qrCanvas" style="border-radius:12px;overflow:hidden"></div>';
      new QRCode('qrCanvas', {text: K.qrlogin._currentToken, width: 200, height: 200, colorDark: '#000000', colorLight: '#ffffff'});
      $('qrStatus').textContent = 'Waiting for scan...';
      K.qrlogin._startPolling();
      K.qrlogin._startCountdown(d.data.expires_in || 120);
    } catch(e) {
      $('qrCodeContainer').innerHTML = '<div style="color:var(--error)">Connection error</div>';
    }
  },

  async _completeLogin() {
    try {
      const d = await K.api.post(V3 + '/auth/qr/login', {token: K.qrlogin._currentToken});
      if (d.success && d.data) {
        K.loginV3._state.user = d.data.user;
        K.loginV3._state.session_token = d.data.session_token;
        K.loginV3._finalizeLogin();
      } else {
        $('qrStatus').innerHTML = '<span style="color:var(--error)">Login failed: ' + (d.error?.message || 'Unknown error') + '</span>';
      }
    } catch(e) {
      $('qrStatus').innerHTML = '<span style="color:var(--error)">Connection error during login</span>';
    }
  },

  async _doScan() {
    const token = $('qrTokenInput')?.value?.trim();
    if (!token) { K.ui.toast('Enter a token', 'error'); return; }
    const st = $('qrScanStatus');
    try {
      const d = await K.api.post(V3 + '/auth/qr/authorize', {token});
      if (d.success) {
        st.innerHTML = '<span style="color:var(--success)"><i class="fas fa-check-circle"></i> Login authorized! Tell the other device to continue.</span>';
      } else {
        st.innerHTML = '<span style="color:var(--error)">' + (d.error?.message || 'Authorization failed') + '</span>';
      }
    } catch(e) {
      st.innerHTML = '<span style="color:var(--error)">Connection error</span>';
    }
  },

  async _startPolling() {
    K.qrlogin._stopPolling();
    const token = K.qrlogin._currentToken;
    if (!token) return;
    K.qrlogin._timer = setInterval(async () => {
      try {
        const d = await K.api.get(V3 + '/auth/qr/status/' + token);
        if (d.success && d.data) {
          if (K.qrlogin._isUnAuth) {
            // Mode B: this device logs in once the other side authorizes.
            if (d.data.authorized && !d.data.consumed) {
              K.qrlogin._stopPolling();
              $('qrStatus').innerHTML = '<span style="color:var(--success)"><i class="fas fa-check-circle"></i> Authorized! Logging in...</span>';
              await K.qrlogin._completeLogin();
            } else if (d.data.expired) {
              K.qrlogin._stopPolling();
              $('qrStatus').innerHTML = '<span style="color:var(--error)">Expired. <a href="#" onclick="K.qrlogin._generate();return false" style="color:var(--accent-blue)">Regenerate</a></span>';
            }
          } else {
            // Mode A: this device is already logged in — the token carries
            // our user_id from the start, so `authorized` is true immediately.
            // Only count the scan when the other device completes login.
            if (d.data.consumed) {
              K.qrlogin._stopPolling();
              $('qrStatus').innerHTML = '<span style="color:var(--success)"><i class="fas fa-check-circle"></i> Logged in on the other device!</span>';
              setTimeout(() => { K.qrlogin._cleanup(); K.modals.close(); K.loginV3._blankOverlay(false); }, 1500);
            } else if (d.data.expired) {
              K.qrlogin._stopPolling();
              $('qrStatus').innerHTML = '<span style="color:var(--error)">Expired. <a href="#" onclick="K.qrlogin._generate();return false" style="color:var(--accent-blue)">Regenerate</a></span>';
            }
          }
        }
      } catch(_) {}
    }, 2000);
  },

  _startCountdown(seconds) {
    K.qrlogin._stopCountdown();
    const el = $('qrExpires');
    if (!el) return;
    let remaining = seconds;
    el.textContent = 'Expires in ' + remaining + 's';
    K.qrlogin._countdownTimer = setInterval(() => {
      remaining--;
      if (remaining <= 0) { K.qrlogin._stopCountdown(); el.textContent = 'Expired'; }
      else el.textContent = 'Expires in ' + remaining + 's';
    }, 1000);
  },

  _stopCountdown() {
    if (K.qrlogin._countdownTimer) { clearInterval(K.qrlogin._countdownTimer); K.qrlogin._countdownTimer = null; }
  },

  _stopPolling() {
    if (K.qrlogin._timer) { clearInterval(K.qrlogin._timer); K.qrlogin._timer = null; }
  },

  _cleanup() {
    K.qrlogin._stopPolling();
    K.qrlogin._stopCountdown();
    K.qrlogin._currentToken = null;
    K.qrlogin._isUnAuth = false;
    K.qrlogin._mode = 'show';
  },
};