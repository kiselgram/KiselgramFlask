'use strict';

/* Kiselgram — Notification module.
 * 1) Stacked toasts (top-right) with type-coloured bar, progress timer and close button.
 * 2) Notification centre (bell in sidebar): persisted list, unread badge, mark read/clear.
 * 3) Realtime 'new-message' events from /notify SocketIO → sound + toast + desktop popup.
 */

const K_NOTIF_MAX = 30;
const K_NOTIF_TOAST_MS = 4000;
const K_NOTIF_LSMKEY = 'k_notifications';
const K_NOTIF_SOUND_KEY = 'k_notif_sound';

K.notify = {
  _items: [],

  init() {
    try { this._items = JSON.parse(localStorage.getItem(K_NOTIF_LSMKEY) || '[]'); } catch (e) { this._items = []; }
    this._updateBadge();
  },

  /* ── Toasts ──────────────────────────────────────────────────────────── */
  toast(msg, type = 'info', opts = {}) {
    const container = $('toastStack');
    if (!container) { console.log('[' + type + ']', msg); return; }
    const icons = { success: 'fa-check-circle', error: 'fa-times-circle', warning: 'fa-exclamation-triangle', info: 'fa-info-circle' };
    const icon = icons[type] || icons.info;

    const toast = document.createElement('div');
    toast.className = 'k-toast2 ' + type;

    const text = document.createElement('span');
    text.className = 'k-toast2-msg';
    text.innerHTML = esc(msg);
    toast.appendChild(text);

    const closeBtn = document.createElement('button');
    closeBtn.className = 'k-toast2-close';
    closeBtn.innerHTML = '&times;';
    toast.appendChild(closeBtn);

    const progress = document.createElement('div');
    progress.className = 'k-toast2-progress';
    toast.appendChild(progress);

    container.appendChild(toast);

    const ms = opts.timeout || K_NOTIF_TOAST_MS;
    progress.style.animationDuration = (ms / 1000) + 's';

    // Cap the stack so it never grows unbounded
    const kids = container.querySelectorAll(':scope > .k-toast2');
    if (kids.length > 6) this._dismiss(kids[0], true);

    const timer = setTimeout(() => this._dismiss(toast), ms);
    closeBtn.onclick = () => { clearTimeout(timer); this._dismiss(toast); };
  },

  _dismiss(toast, instant = false) {
    if (!toast || toast.classList.contains('fade-out')) return;
    toast.classList.add('fade-out');
    const kill = () => toast.remove();
    if (instant) kill();
    else setTimeout(kill, 300);
  },

  /* ── Notification centre ─────────────────────────────────────────────── */
  add(title, body, opts = {}) {
    this._items.unshift({ title, body, ts: Date.now(), read: false, chat_type: opts.chat_type, chat_id: opts.chat_id, from_id: opts.from_id });
    if (this._items.length > K_NOTIF_MAX) this._items.length = K_NOTIF_MAX;
    try { localStorage.setItem(K_NOTIF_LSMKEY, JSON.stringify(this._items)); } catch (e) {}
    this._updateBadge();
  },

  markAllRead() {
    this._items.forEach((n) => { n.read = true; });
    try { localStorage.setItem(K_NOTIF_LSMKEY, JSON.stringify(this._items)); } catch (e) {}
    this._updateBadge();
    this._renderList();
  },

  clearAll() {
    this._items = [];
    try { localStorage.removeItem(K_NOTIF_LSMKEY); } catch (e) {}
    this._updateBadge();
    this._renderList();
  },

  unread() { return this._items.filter((n) => !n.read).length; },

  _updateBadge() {
    const b = $('notifBadge');
    if (!b) return;
    const n = this.unread();
    b.textContent = n > 9 ? '9+' : n;
    b.style.display = n ? 'flex' : 'none';
  },

  open() {
    const o = $('modalOverlay'); if (!o) return;
    o.style.display = 'flex';
    this.markAllRead();
    $('modalContent').innerHTML = `
      <div class="k-modal-header"><h3>Notifications</h3><button class="k-modal-close" onclick="K.modals.close()"><i class="fas fa-times"></i></button></div>
      <div class="k-modal-body">
        <div class="k-notif-actions">
          <button class="k-btn k-btn-secondary k-btn-sm" onclick="K.notify.requestDesktop()" id="notifDesktopBtn"></button>
          <button class="k-btn k-btn-secondary k-btn-sm" onclick="K.notify.toggleSound()" id="notifSoundBtn"></button>
        </div>
        <div class="k-notif-list" id="notifList"></div>
        <div class="k-modal-footer">
          <button class="k-btn k-btn-secondary" onclick="K.notify.clearAll()">Clear all</button>
        </div>
      </div>`;
    this._renderList();
    this._renderActions();
  },

  _renderActions() {
    const db_el = $('notifDesktopBtn');
    if (db_el) {
      if (typeof Notification === 'undefined') { db_el.textContent = 'Desktop: N/A'; db_el.disabled = true; }
      else {
        db_el.textContent = 'Desktop: ' + (Notification.permission === 'granted' ? 'on' : 'off');
        db_el.disabled = Notification.permission === 'denied';
      }
    }
    const sb = $('notifSoundBtn');
    if (sb) sb.textContent = 'Sound: ' + (this.soundOn() ? 'on' : 'off');
  },

  _renderList() {
    const list = $('notifList');
    if (!list) return;
    if (!this._items.length) {
      list.innerHTML = '<div class="k-notif-empty">No notifications yet</div>';
      return;
    }
    list.innerHTML = this._items.map((n) => `
      <div class="k-notif-item ${n.read ? '' : 'unread'}" onclick="K.notify._click(${n.from_id || 'null'} ,'${esc(n.chat_type || '')}',${n.chat_id || 'null'})">
        <div class="k-notif-avatar">${n.title ? esc((n.title)[0] || '?').toUpperCase() : '?'}</div>
        <div class="k-notif-text">
          <div class="k-notif-title">${esc(n.title)}</div>
          <div class="k-notif-body">${esc(n.body)}</div>
        </div>
        <div class="k-notif-time">${this._timeAgo(n.ts)}</div>
      </div>`).join('');
  },

  _click(fromId, chatType, chatId) {
    K.modals.close();
    if (fromId) { try { K.chat.open('personal', fromId); } catch (e) {}
    } else if (chatId && chatType) { try { K.chat.open(chatType, chatId); } catch (e) {} }
  },

  _timeAgo(ts) {
    const s = Math.floor((Date.now() - ts) / 1000);
    if (s < 60) return 'now';
    if (s < 3600) return Math.floor(s / 60) + 'm';
    if (s < 86400) return Math.floor(s / 3600) + 'h';
    return Math.floor(s / 86400) + 'd';
  },

  /* ── Sound & desktop notifications ───────────────────────────────────── */
  soundOn() { try { return localStorage.getItem(K_NOTIF_SOUND_KEY) !== 'off'; } catch (e) { return true; } },

  toggleSound() {
    localStorage.setItem(K_NOTIF_SOUND_KEY, this.soundOn() ? 'off' : 'on');
    this._renderActions();
  },

  sound(kind = 'message') {
    if (!this.soundOn()) return;
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      this._ac = this._ac || new AC();
      const ac = this._ac;
      if (ac.state === 'suspended') { ac.resume(); }
      const o = ac.createOscillator(), g = ac.createGain();
      o.type = 'sine';
      o.connect(g); g.connect(ac.destination);
      if (kind === 'message') { o.frequency.value = 880; g.gain.setValueAtTime(0.001, ac.currentTime); g.gain.exponentialRampToValueAtTime(0.06, ac.currentTime + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, ac.currentTime + 0.25); o.start(); o.stop(ac.currentTime + 0.26); }
    } catch (e) {}
  },

  requestDesktop() {
    if (typeof Notification === 'undefined') { this.toast('Desktop notifications not supported', 'warning'); return; }
    Notification.requestPermission().then((p) => {
      this._renderActions();
      if (p === 'granted') this.toast('Desktop notifications enabled', 'success');
      else if (p === 'denied') this.toast('Desktop notifications blocked', 'error');
    });
  },

  _desktop(title, body, fromId, chatType, chatId) {
    if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return;
    if (document.visibilityState !== 'hidden') return;   // only when tab is hidden
    try {
      const n = new Notification(title, { body, silent: true, tag: 'kiselgram-msg' });
      n.onclick = () => {
        window.focus();
        if (chatType && chatId) K.chat.open(chatType, chatId);
        else if (fromId) K.chat.open('personal', fromId);
        n.close();
      };
    } catch (e) {}
  },

  /* ── Realtime events (from /notify socket) ───────────────────────────── */
  /* Returns true when this event type belongs to this module. */
  handleNotify(d) {
    if (!d || d.type !== 'new-message') return false;
    const me = K.state.user ? K.state.user.user_id : null;
    if (d.from_id === me) return true;   // own message — ignore

    const active = K.state.activeChat;
    const inSameChat = !!active && (
      (d.chat_type === 'personal' && active.type === 'personal' && active.id === d.from_id) ||
      (active.type === d.chat_type && active.id === d.chat_id)
    );

    const title = d.from_username ? '@' + d.from_username : 'New message';
    this.add(title, d.content_preview || '', { chat_type: d.chat_type, chat_id: d.chat_id, from_id: d.chat_type === 'personal' ? d.from_id : null });

    if (document.hidden) {
      this.sound('message');
      this._desktop(title, d.content_preview || '', d.from_id, d.chat_type, d.chat_id);
    } else if (!inSameChat) {
      this.sound('message');
      this.toast((d.chat_type === 'channel' ? '📢 ' : '💬 ') + title + ': ' + (d.content_preview || ''), 'info');
    }
    // Refresh the chat list preview for the affected chat
    if (K.chat && K.chat.loadList && document.visibilityState === 'visible') { try { K.chat.loadList(); } catch (e) {} }
    return true;
  }
};

K.notify.init();
