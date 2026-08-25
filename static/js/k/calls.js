const SECOND_MS = 1000;

K.calls = {
  _timer: null, _started: null,
  _activeCallId: null,   // the call_id we're in or ringing
  _activeRoomId: null,
  _pendingCall: null,     // incoming call data awaiting accept/reject
  _notifyWs: null,        // notification WebSocket
  _ringingTimeout: null,  // auto-cancel outgoing after 60s

  // ── Notification WebSocket (SPA → server, per-user via SocketIO) ──
  connectNotify() {
    const u = K.state.user;
    if (!u) return;
    const token = u.token || u.session_token;
    if (!token) return;

    try {
      const socket = io('/notify', { transports: ['websocket', 'polling'] });
      socket.on('connect', () => {
        console.log('[notify] connected');
        socket.emit('identify', { user_id: u.user_id || u.userId });
      });
      socket.on('disconnect', () => {
        console.log('[notify] disconnected');
      });
      socket.on('message', (d) => {
        K.calls._handleNotify(d);
      });
      this._notifyWs = socket;
    } catch (e) {
      console.warn('[notify] connect failed:', e);
    }
  },

  _handleNotify(d) {
    const t = d.type;
    if (t === 'call-invite') {
      // Someone is calling us — show incoming call overlay
      K.calls._pendingCall = d;
      K.calls._showIncoming(d);
    } else if (t === 'call-accepted') {
      // Callee accepted — redirect to room
      clearTimeout(K.calls._ringingTimeout);
      K.calls._ringingTimeout = null;
      const roomUrl = '/api/video/room/' + d.room_id;
      K.calls.start(roomUrl, d.call_id);
    } else if (t === 'call-rejected') {
      // Callee rejected — hide outgoing overlay
      clearTimeout(K.calls._ringingTimeout);
      K.calls._ringingTimeout = null;
      K.calls._hideOutgoing();
      K.ui.toast('Call declined', 'error');
    }
  },

  // ── Incoming call overlay ──
  _showIncoming(d) {
    const overlay = $('incomingCallOverlay');
    const nameEl = $('incomingCallerName');
    const typeEl = $('incomingCallType');
    if (nameEl) nameEl.textContent = d.caller_name || 'Incoming call';
    if (typeEl) typeEl.textContent = (d.call_type || 'audio') + ' call';
    if (overlay) overlay.style.display = 'flex';

    // Play ringtone (if supported)
    try {
      const ctx = new AudioContext();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = 440;
      gain.gain.value = 0.3;
      osc.connect(gain).connect(ctx.destination);
      osc.start();
      this._ringtone = { osc, ctx };
      setTimeout(() => { try { osc.stop(); ctx.close(); } catch {} }, 30000);
    } catch {}

    // Auto-dismiss after 30 seconds
    this._incomingTimeout = setTimeout(() => K.calls.reject(), 30000);
  },

  async accept() {
    const d = this._pendingCall;
    if (!d) return;
    clearTimeout(this._incomingTimeout);
    const overlay = $('incomingCallOverlay');
    if (overlay) overlay.style.display = 'none';
    try { this._ringtone?.osc?.stop(); this._ringtone?.ctx?.close(); } catch {}
    this._pendingCall = null;

    try {
      const resp = await K.api.post(V2 + '/calls/' + d.call_id + '/accept');
      if (resp.success && resp.data?.room_id) {
        const roomUrl = '/api/video/room/' + resp.data.room_id;
        K.calls.start(roomUrl, d.call_id);
      } else {
        K.ui.toast('Failed to accept call', 'error');
      }
    } catch (e) {
      K.ui.toast('Failed to accept call', 'error');
    }
  },

  async reject() {
    const d = this._pendingCall;
    clearTimeout(this._incomingTimeout);
    const overlay = $('incomingCallOverlay');
    if (overlay) overlay.style.display = 'none';
    try { this._ringtone?.osc?.stop(); this._ringtone?.ctx?.close(); } catch {}
    if (!d) return;
    this._pendingCall = null;

    try {
      await K.api.post(V2 + '/calls/' + d.call_id + '/reject');
    } catch (e) {}
  },

  // ── Outgoing call overlay ──
  _showOutgoing(peerName, callType) {
    const overlay = $('outgoingCallOverlay');
    const nameEl = $('outgoingCallerName');
    const typeEl = $('outgoingCallType');
    if (nameEl) nameEl.textContent = 'Calling ' + (peerName || '') + '...';
    if (typeEl) typeEl.textContent = (callType || 'audio') + ' call';
    if (overlay) overlay.style.display = 'flex';

    // Auto-cancel after 60 seconds
    this._ringingTimeout = setTimeout(() => K.calls.cancel(), 60000);
  },

  _hideOutgoing() {
    const overlay = $('outgoingCallOverlay');
    if (overlay) overlay.style.display = 'none';
  },

  async cancel() {
    clearTimeout(this._ringingTimeout);
    this._ringingTimeout = null;
    this._hideOutgoing();
    if (this._activeCallId) {
      try { await K.api.post(V2 + '/calls/' + this._activeCallId + '/end'); } catch {}
      this._activeCallId = null;
    }
  },

  // ── Start / join a video room (iframe mode) ──
  start(url, callId) {
    this._hideOutgoing();
    const overlay = $('videoOverlay');
    const frame = $('videoFrame');
    if (overlay) overlay.style.display = 'flex';
    if (frame) {
      frame.innerHTML = `<iframe src="${esc(url)}" allow="camera;microphone;display-capture" style="width:100%;height:100%;border:none"></iframe>`;
    }
    const vcp = $('videoCallPeer'); if (vcp) vcp.textContent = 'In call';
    this._started = Date.now();
    this._updateTimer();
    this._timer = setInterval(this._updateTimer, SECOND_MS);
  },

  _updateTimer() {
    if (!K.calls._started) return;
    const elapsed = Math.floor((Date.now() - K.calls._started) / SECOND_MS);
    const m = String(Math.floor(elapsed / 60)).padStart(2, '0');
    const s = String(elapsed % 60).padStart(2, '0');
    const t = m + ':' + s;
    const vcd = $('videoCallDuration'); if (vcd) vcd.textContent = t;
    const md = $('miniDuration'); if (md) md.textContent = t;
  },

  minimize() {
    const vo = $('videoOverlay'); if (vo) vo.style.display = 'none';
    const vm = $('videoMinimized'); if (vm) vm.style.display = 'flex';
  },

  maximize() {
    const vm = $('videoMinimized'); if (vm) vm.style.display = 'none';
    const vo = $('videoOverlay'); if (vo) vo.style.display = 'flex';
  },

  endCall() {
    clearInterval(K.calls._timer);
    K.calls._timer = null;
    K.calls._started = null;
    if (this._activeCallId) {
      K.api.post(V2 + '/calls/' + this._activeCallId + '/end').catch(() => {});
      this._activeCallId = null;
    }
    const vo = $('videoOverlay'); if (vo) vo.style.display = 'none';
    const vm = $('videoMinimized'); if (vm) vm.style.display = 'none';
    const frame = $('videoFrame');
    if (frame) frame.innerHTML = '<div class="k-loader" style="margin:auto"></div>';
    K.chat.loadList();
  },

  // ── Call history ──
  async load() {
    const list = $('callsList'); if (!list) return;
    list.innerHTML = K.ui.loader();
    try {
      const d = await K.api.get(V2 + '/calls/history');
      if (d.success) {
        const calls = d.data?.calls || [];
        if (!calls.length) { list.innerHTML = '<div class="k-empty"><i class="fas fa-phone-alt"></i><h3>No calls yet</h3></div>'; return; }
        list.innerHTML = calls.map(c => `
          <div class="k-call-item" onclick="K.chat.open('personal',${c.peer_id||c.other_user_id})">
            <div class="k-call-icon"><i class="fas fa-phone-alt"></i></div>
            <div class="k-call-info">
              <div class="k-call-name">${esc(c.peer_name||'Unknown')}</div>
              <div class="k-call-meta">${c.direction==='outgoing'?'Outgoing':'Incoming'} · ${c.status||'ended'} · ${c.duration ? Math.floor(c.duration/60)+'m' : '--'}</div>
            </div>
            <div class="k-call-time">${fmtTime(c.created_at)}</div>
          </div>
        `).join('');
      }
    } catch(e) { list.innerHTML = '<div class="k-empty">Failed to load</div>'; }
  }
};
