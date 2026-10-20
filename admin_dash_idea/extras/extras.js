/* Kiselgram admin — extras layer.
 * Load AFTER admin-boot.js. Adds: command palette (Ctrl+K),
 * keyboard shortcuts, live pulse on stat change, sparklines,
 * sound design, undo toasts, confetti. Zero changes to admin-page.js.
 */
'use strict';

(function () {
  if (window._adminExtrasLoaded) return;
  window._adminExtrasLoaded = true;

  // ---------------------------------------------------------------
  // 1. SOUND (Web Audio, no files)
  // ---------------------------------------------------------------
  const Snd = {
    _ctx: null,
    _enabled: JSON.parse(localStorage.getItem('k_admin_sound') ?? 'true'),
    ctx() { if (!this._ctx) this._ctx = new (window.AudioContext || window.webkitAudioContext)(); return this._ctx; },
    tone(freq, dur = 0.08, type = 'sine', gain = 0.04) {
      if (!this._enabled) return;
      try {
        const c = this.ctx();
        const o = c.createOscillator();
        const g = c.createGain();
        o.type = type; o.frequency.value = freq;
        g.gain.value = gain;
        g.gain.exponentialRampToValueAtTime(0.0001, c.currentTime + dur);
        o.connect(g).connect(c.destination);
        o.start(); o.stop(c.currentTime + dur);
      } catch (_) {}
    },
    tick()   { this.tone(880, 0.04, 'sine', 0.02); },
    ok()     { this.tone(660, 0.06); setTimeout(() => this.tone(990, 0.09), 60); },
    err()    { this.tone(220, 0.14, 'sawtooth', 0.05); },
    alert()  { this.tone(520, 0.06); setTimeout(() => this.tone(520, 0.06), 120); },
    toggle() {
      this._enabled = !this._enabled;
      localStorage.setItem('k_admin_sound', JSON.stringify(this._enabled));
      K.ui.toast('Sound ' + (this._enabled ? 'on' : 'off'), 'info');
    },
  };

  // ---------------------------------------------------------------
  // 2. UNDO TOAST (destructive actions get an Undo button)
  // ---------------------------------------------------------------
  const Undo = {
    show(msg, undoFn, seconds = 6) {
      const host = document.getElementById('toast') || (() => {
        const d = document.createElement('div');
        d.id = 'toast'; d.className = 'k-toast';
        document.body.appendChild(d);
        return d;
      })();
      host.innerHTML = `<span>${escapeHtml(msg)}</span>
        <button class="k-undo-btn" style="margin-left:12px;padding:3px 10px;border-radius:6px;
          border:1px solid currentColor;background:transparent;color:inherit;
          cursor:pointer;font-size:11px;font-weight:600;letter-spacing:.06em">UNDO</button>`;
      host.classList.add('show');
      host._t = setTimeout(() => { host.classList.remove('show'); host.innerHTML = ''; }, seconds * 1000);
      host.querySelector('.k-undo-btn').onclick = () => {
        clearTimeout(host._t);
        host.classList.remove('show');
        host.innerHTML = '';
        try { undoFn && undoFn(); } catch (_) {}
        K.ui.toast('Reverted', 'success');
      };
    },
  };

  // ---------------------------------------------------------------
  // 3. CONFETTI
  // ---------------------------------------------------------------
  function confetti(count = 60) {
    const cvs = document.createElement('canvas');
    cvs.style.cssText = 'position:fixed;inset:0;z-index:99999;pointer-events:none';
    document.body.appendChild(cvs);
    const ctx = cvs.getContext('2d');
    const dpr = Math.min(devicePixelRatio || 1, 2);
    let W = innerWidth, H = innerHeight;
    cvs.width = W * dpr; cvs.height = H * dpr;
    cvs.style.width = W + 'px'; cvs.style.height = H + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const colors = ['#00e5ff', '#a855f7', '#4ade80', '#ffb020', '#ff4d9d', '#22e6a0'];
    const parts = Array.from({ length: count }, () => ({
      x: W / 2 + (Math.random() - 0.5) * 120,
      y: H / 3,
      vx: (Math.random() - 0.5) * 12,
      vy: -4 - Math.random() * 10,
      g: 0.35 + Math.random() * 0.2,
      r: 3 + Math.random() * 5,
      c: colors[Math.floor(Math.random() * colors.length)],
      rot: Math.random() * Math.PI,
      vr: (Math.random() - 0.5) * 0.3,
      life: 1,
    }));

    let raf;
    function frame() {
      ctx.clearRect(0, 0, W, H);
      let alive = 0;
      for (const p of parts) {
        p.vy += p.g; p.x += p.vx; p.y += p.vy;
        p.vx *= 0.995; p.rot += p.vr; p.life -= 0.008;
        if (p.life > 0 && p.y < H + 40) {
          alive++;
          ctx.save();
          ctx.globalAlpha = Math.max(0, p.life);
          ctx.translate(p.x, p.y); ctx.rotate(p.rot);
          ctx.fillStyle = p.c;
          ctx.fillRect(-p.r / 2, -p.r / 2, p.r, p.r * 1.6);
          ctx.restore();
        }
      }
      if (alive) raf = requestAnimationFrame(frame);
      else { cancelAnimationFrame(raf); cvs.remove(); }
    }
    frame();
  }

  // ---------------------------------------------------------------
  // 4. COMMAND PALETTE (Ctrl+K / Cmd+K)
  // ---------------------------------------------------------------
  const Palette = {
    _el: null, _input: null, _list: null, _items: [], _filtered: [], _idx: 0,

    commands() {
      return [
        { label: 'Reports',          hint: 'Go to',       icon: 'fa-flag',          run: () => clickTab('reports') },
        { label: 'Users',            hint: 'Go to',       icon: 'fa-users',         run: () => clickTab('users') },
        { label: 'Chats',            hint: 'Go to',       icon: 'fa-comments',      run: () => clickTab('chats') },
        { label: 'Mail accounts',    hint: 'Go to',       icon: 'fa-envelope',      run: () => clickTab('mail') },
        { label: 'Promo codes',      hint: 'Go to',       icon: 'fa-tags',          run: () => clickTab('promo') },
        { label: '2FA overview',     hint: 'Go to',       icon: 'fa-shield-alt',    run: () => clickTab('twofa') },
        { label: 'Terminal',         hint: 'Go to',       icon: 'fa-terminal',      run: () => clickTab('terminal') },
        { label: 'Add user',         hint: 'Action',      icon: 'fa-user-plus',     run: () => K.adminPage.openAddUser() },
        { label: 'Create channel',   hint: 'Action',      icon: 'fa-bullhorn',      run: () => K.adminPage.openCreateChannel() },
        { label: 'Generate promo',   hint: 'Action',      icon: 'fa-plus',          run: () => K.adminPage.openGeneratePromo() },
        { label: 'Add mail account', hint: 'Action',      icon: 'fa-plus',          run: () => K.adminPage.openAddMailAccount() },
        { label: 'Refresh all',      hint: 'Action',      icon: 'fa-sync-alt',      run: () => { K.adminPage.loadDashboard(); K.adminPage.loadReports(); K.adminPage.loadUsers(); } },
        { label: 'Cleanup expired OTPs',      hint: 'Danger', icon: 'fa-trash-alt',  run: () => K.adminPage.cleanupOtps() },
        { label: 'Cleanup email codes',       hint: 'Danger', icon: 'fa-trash-alt',  run: () => K.adminPage.cleanupEmailVerifications() },
        { label: 'Cleanup QR tokens',         hint: 'Danger', icon: 'fa-trash-alt',  run: () => K.adminPage.cleanupQrTokens() },
        { label: 'Toggle sound',     hint: 'System',      icon: 'fa-volume-up',     run: () => Snd.toggle() },
        { label: 'Toggle accent color', hint: 'System',   icon: 'fa-palette',       run: cycleAccent },
        { label: 'Logout',           hint: 'Danger',      icon: 'fa-sign-out-alt',  run: () => { window.location.href = '/api/admin/logout'; } },
      ];
    },

    open() {
      if (this._el) return this._el.style.display = 'flex';
      this._build();
      this._el.style.display = 'flex';
      this._input.value = '';
      this._input.focus();
      this._render('');
    },

    close() {
      if (this._el) this._el.style.display = 'none';
    },

    _build() {
      const el = document.createElement('div');
      el.className = 'k-palette';
      el.innerHTML = `
        <div class="k-palette-box">
          <div class="k-palette-input-row">
            <i class="fas fa-search"></i>
            <input class="k-palette-input" placeholder="Search commands…" autocomplete="off">
            <kbd>ESC</kbd>
          </div>
          <div class="k-palette-list"></div>
          <div class="k-palette-footer">
            <span><kbd>↑</kbd><kbd>↓</kbd> navigate</span>
            <span><kbd>↵</kbd> run</span>
          </div>
        </div>`;
      el.onclick = (e) => { if (e.target === el) this.close(); };
      document.body.appendChild(el);

      this._el = el;
      this._input = el.querySelector('.k-palette-input');
      this._list = el.querySelector('.k-palette-list');
      this._input.addEventListener('input', () => this._render(this._input.value));
      this._input.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowDown') { e.preventDefault(); this._idx = Math.min(this._filtered.length - 1, this._idx + 1); this._paint(); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); this._idx = Math.max(0, this._idx - 1); this._paint(); }
        else if (e.key === 'Enter') { e.preventDefault(); this._run(); }
        else if (e.key === 'Escape') { this.close(); }
      });
    },

    _render(q) {
      const all = this.commands();
      const query = (q || '').toLowerCase().trim();
      if (!query) this._filtered = all;
      else this._filtered = all.filter(c => fuzzyMatch(query, (c.hint + ' ' + c.label).toLowerCase()));
      this._idx = 0;
      this._list.innerHTML = this._filtered.map((c, i) => `
        <div class="k-palette-item ${i === 0 ? 'sel' : ''}" data-idx="${i}">
          <i class="fas ${c.icon}"></i>
          <span class="k-palette-label">${escapeHtml(c.label)}</span>
          <span class="k-palette-hint">${escapeHtml(c.hint)}</span>
        </div>`).join('') || '<div class="k-palette-empty">No matches</div>';
      this._list.querySelectorAll('.k-palette-item').forEach(el => {
        el.onclick = () => { this._idx = +el.dataset.idx; this._run(); };
        el.onmouseenter = () => { this._idx = +el.dataset.idx; this._paint(); };
      });
    },

    _paint() {
      this._list.querySelectorAll('.k-palette-item').forEach((el, i) =>
        el.classList.toggle('sel', i === this._idx));
    },

    _run() {
      const c = this._filtered[this._idx];
      this.close();
      if (c) { Snd.tick(); setTimeout(() => c.run(), 30); }
    },
  };

  // ---------------------------------------------------------------
  // 5. LIVE PULSE + SPARKLINES on stat cards
  // ---------------------------------------------------------------
  const Live = {
    history: {},   // label -> [values]
    maxPoints: 30,

    patch() {
      const orig = K.adminPage.loadDashboard.bind(K.adminPage);
      K.adminPage.loadDashboard = async function () {
        await orig();
        Live.afterRender();
      };
      // First call
      setTimeout(() => K.adminPage.loadDashboard(), 500);
      // Poll every 30s
      setInterval(() => K.adminPage.loadDashboard(), 30000);
    },

    afterRender() {
      const cards = document.querySelectorAll('#stats .stat');
      cards.forEach((card) => {
        const labelEl = card.querySelector('.stat-label');
        const valEl = card.querySelector('.stat-value');
        if (!labelEl || !valEl) return;
        const key = labelEl.textContent.trim();
        const v = valEl.textContent.trim();

        // Pulse if changed
        if (this.history[key] && this.history[key].length) {
          const prev = this.history[key][this.history[key].length - 1];
          if (prev !== v) {
            valEl.classList.add('k-pulse');
            setTimeout(() => valEl.classList.remove('k-pulse'), 700);
          }
        }

        // Push to history
        if (!this.history[key]) this.history[key] = [];
        const numeric = parseFloat(String(v).replace(/[^\d.-]/g, ''));
        if (!isNaN(numeric)) {
          this.history[key].push(numeric);
          if (this.history[key].length > this.maxPoints) this.history[key].shift();
        }

        // Ensure a canvas exists
        let cvs = card.querySelector('.k-spark');
        if (!cvs) {
          cvs = document.createElement('canvas');
          cvs.className = 'k-spark';
          cvs.style.cssText = 'width:100%;height:26px;margin-top:6px;display:block;opacity:.85';
          card.appendChild(cvs);
        }
        this._draw(cvs, this.history[key]);
      });
    },

    _draw(cvs, data) {
      if (!data || data.length < 2) { cvs.width = cvs.height = 0; return; }
      const rect = cvs.getBoundingClientRect();
      const dpr = Math.min(devicePixelRatio || 1, 2);
      cvs.width = rect.width * dpr;
      cvs.height = rect.height * dpr;
      const ctx = cvs.getContext('2d');
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const W = rect.width, H = rect.height;
      const min = Math.min(...data), max = Math.max(...data);
      const span = max - min || 1;
      const x = (i) => (i / (data.length - 1)) * W;
      const y = (v) => H - 2 - ((v - min) / span) * (H - 4);

      const accent = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#00e5ff';
      const rgb = getComputedStyle(document.documentElement).getPropertyValue('--accent-rgb').trim() || '0,229,255';

      ctx.beginPath();
      ctx.moveTo(x(0), y(data[0]));
      for (let i = 1; i < data.length; i++) ctx.lineTo(x(i), y(data[i]));
      ctx.strokeStyle = accent;
      ctx.lineWidth = 1.4;
      ctx.stroke();

      // area
      ctx.lineTo(W, H); ctx.lineTo(0, H); ctx.closePath();
      const grad = ctx.createLinearGradient(0, 0, 0, H);
      grad.addColorStop(0, `rgba(${rgb},.25)`);
      grad.addColorStop(1, `rgba(${rgb},0)`);
      ctx.fillStyle = grad;
      ctx.fill();
    },
  };

  // ---------------------------------------------------------------
  // 6. KEYBOARD SHORTCUTS
  // ---------------------------------------------------------------
  let _lastKey = '', _lastKeyAt = 0;
  document.addEventListener('keydown', (e) => {
    // Ctrl/Cmd + K -> palette
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      Palette.open();
      return;
    }
    // Ignore when typing
    const t = e.target;
    const typing = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable);
    if (typing) return;

    if (e.key === '?') {
      showShortcutsHelp();
      return;
    }

    // g r / g u / g c / g m / g p / g t / g 2
    const now = Date.now();
    if (_lastKey === 'g' && now - _lastKeyAt < 1200) {
      const map = { r: 'reports', u: 'users', c: 'chats', m: 'mail', p: 'promo', t: 'terminal', '2': 'twofa' };
      if (map[e.key]) { e.preventDefault(); clickTab(map[e.key]); _lastKey = ''; return; }
    }
    if (e.key === 'g') { _lastKey = 'g'; _lastKeyAt = now; }
  });

  // ---------------------------------------------------------------
  // 7. HOOKS — sound + confetti on destructive actions
  // ---------------------------------------------------------------
  function wrapWithFeedback(obj, methods, { sound = 'ok', celebrate = false } = {}) {
    methods.forEach((name) => {
      const orig = obj[name];
      if (typeof orig !== 'function' || orig._wrapped) return;
      const wrapped = async function (...args) {
        try {
          const r = await orig.apply(this, args);
          if (sound) Snd[sound]?.();
          if (celebrate) confetti(40);
          return r;
        } catch (e) {
          Snd.err();
          throw e;
        }
      };
      wrapped._wrapped = true;
      obj[name] = wrapped;
    });
  }

  // ---------------------------------------------------------------
  // 8. HELP OVERLAY
  // ---------------------------------------------------------------
  function showShortcutsHelp() {
    const html = `
      <div class="k-shortcuts">
        <h3><i class="fas fa-keyboard"></i> Shortcuts</h3>
        <div class="k-shortcut-grid">
          <div><kbd>⌘</kbd><kbd>K</kbd> Command palette</div>
          <div><kbd>G</kbd><kbd>R</kbd> Reports</div>
          <div><kbd>G</kbd><kbd>U</kbd> Users</div>
          <div><kbd>G</kbd><kbd>C</kbd> Chats</div>
          <div><kbd>G</kbd><kbd>M</kbd> Mail</div>
          <div><kbd>G</kbd><kbd>P</kbd> Promo</div>
          <div><kbd>G</kbd><kbd>2</kbd> 2FA</div>
          <div><kbd>G</kbd><kbd>T</kbd> Terminal</div>
          <div><kbd>?</kbd> This help</div>
        </div>
        <button class="k-btn" onclick="this.closest('.k-shortcuts').parentElement.remove()">Close</button>
      </div>`;
    const ov = document.createElement('div');
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(4,7,14,.8);z-index:100000;display:grid;place-items:center;backdrop-filter:blur(6px)';
    ov.innerHTML = html;
    ov.onclick = (e) => { if (e.target === ov) ov.remove(); };
    document.body.appendChild(ov);
  }

  // ---------------------------------------------------------------
  // HELPERS
  // ---------------------------------------------------------------
  function clickTab(name) {
    const btn = document.querySelector(`.tab[data-tab="${name}"]`);
    if (btn) btn.click();
  }

  function cycleAccent() {
    const picker = document.getElementById('accentPicker');
    if (!picker) return;
    const btns = [...picker.querySelectorAll('button')];
    const cur = btns.findIndex(b => b.classList.contains('on'));
    const next = (cur + 1) % btns.length;
    btns[next].click();
  }

  function escapeHtml(s) {
    const d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }

  function fuzzyMatch(query, target) {
    let qi = 0;
    for (let i = 0; i < target.length && qi < query.length; i++) {
      if (target[i] === query[qi]) qi++;
    }
    return qi === query.length;
  }

  // ---------------------------------------------------------------
  // BOOT
  // ---------------------------------------------------------------
  document.addEventListener('DOMContentLoaded', function () {
    if (!window.K || !K.adminPage) return;

    // Patch dashboard for live updates
    Live.patch();

    // Wrap destructive actions for sound + confetti
    wrapWithFeedback(K.adminPage, [
      'resolveReport', 'deleteUser', 'toggleAdmin', 'saveAddUser',
      'savePassword', 'setUserPassword', 'saveEditUser',
      'cleanupOtps', 'cleanupEmailVerifications', 'cleanupQrTokens',
      'saveGeneratePromo', 'togglePromo', 'deleteMailAccount',
    ], { sound: 'ok' });

    // Confetti specifically for cleanup + creation success
    ['cleanupOtps', 'cleanupEmailVerifications', 'cleanupQrTokens'].forEach((name) => {
      const orig = K.adminPage[name];
      if (typeof orig !== 'function') return;
      K.adminPage[name] = async function (...a) {
        const r = await orig.apply(this, a);
        confetti(60);
        return r;
      };
    });

    // Tab switch sound
    document.querySelectorAll('.tab').forEach(t => t.addEventListener('click', () => Snd.tick()));

    // Refresh dashboard stats after any of these resolve
    setTimeout(() => K.adminPage.loadDashboard(), 200);
  });

  // Expose for console / hooks
  window.K.adminExtras = { Snd, Undo, Palette, confetti, Live, showShortcutsHelp };
})();