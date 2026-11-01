/* Kiselgram admin — extras: guesser UI, clustering, bulk, notes,
 * action log, sessions, SSE feed, palette, debug, easter eggs. */
'use strict';

(function () {
  if (window._adminExtrasLoaded) return;
  window._adminExtrasLoaded = true;

  const SEV_RANK = { high: 3, medium: 2, low: 1 };
  const SEV_COLOR = { high: '#ff4d6d', medium: '#ffb020', low: '#22e6a0' };
  const SEV_EMOJI = { high: '🔴', medium: '🟡', low: '🟢' };

  // ==========================================================
  // 1. SOUND
  // ==========================================================
  const Snd = {
    _ctx: null,
    _on: JSON.parse(localStorage.getItem('k_admin_sound') ?? 'true'),
    _c() { if (!this._ctx) this._ctx = new (window.AudioContext || window.webkitAudioContext)(); return this._ctx; },
    _tone(f, d = 0.08, type = 'sine', g = 0.04) {
      if (!this._on) return;
      try {
        const c = this._c(), o = c.createOscillator(), gain = c.createGain();
        o.type = type; o.frequency.value = f; gain.gain.value = g;
        gain.gain.exponentialRampToValueAtTime(0.0001, c.currentTime + d);
        o.connect(gain).connect(c.destination); o.start(); o.stop(c.currentTime + d);
      } catch (_) {}
    },
    tick() { this._tone(880, 0.04, 'sine', 0.02); },
    ok() { this._tone(660); setTimeout(() => this._tone(990, 0.09), 60); },
    err() { this._tone(220, 0.14, 'sawtooth', 0.05); },
    toggle() {
      this._on = !this._on;
      localStorage.setItem('k_admin_sound', JSON.stringify(this._on));
      K.ui.toast('Sound ' + (this._on ? 'on' : 'off'), 'info');
    },
  };

  // ==========================================================
  // 2. CONFETTI
  // ==========================================================
  function confetti(count = 60) {
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const cvs = document.createElement('canvas');
    cvs.style.cssText = 'position:fixed;inset:0;z-index:99999;pointer-events:none';
    document.body.appendChild(cvs);
    const ctx = cvs.getContext('2d');
    const dpr = Math.min(devicePixelRatio || 1, 2);
    let W = innerWidth, H = innerHeight;
    cvs.width = W * dpr; cvs.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const colors = ['#00e5ff', '#a855f7', '#4ade80', '#ffb020', '#ff4d9d'];
    const parts = Array.from({ length: count }, () => ({
      x: W / 2 + (Math.random() - 0.5) * 120, y: H / 3,
      vx: (Math.random() - 0.5) * 12, vy: -4 - Math.random() * 10,
      g: 0.35 + Math.random() * 0.2, r: 3 + Math.random() * 5,
      c: colors[Math.floor(Math.random() * colors.length)],
      rot: Math.random() * Math.PI, vr: (Math.random() - 0.5) * 0.3, life: 1,
    }));
    let raf, alive = 0;
    (function frame() {
      ctx.clearRect(0, 0, W, H); alive = 0;
      for (const p of parts) {
        p.vy += p.g; p.x += p.vx; p.y += p.vy;
        p.vx *= 0.995; p.rot += p.vr; p.life -= 0.008;
        if (p.life > 0 && p.y < H + 40) {
          alive++;
          ctx.save(); ctx.globalAlpha = Math.max(0, p.life);
          ctx.translate(p.x, p.y); ctx.rotate(p.rot);
          ctx.fillStyle = p.c;
          ctx.fillRect(-p.r / 2, -p.r / 2, p.r, p.r * 1.6);
          ctx.restore();
        }
      }
      if (alive) raf = requestAnimationFrame(frame);
      else cvs.remove();
    })();
  }

  // ==========================================================
  // 3. UNDO TOAST
  // ==========================================================
  const Undo = {
    show(msg, undoFn, seconds = 6) {
      const host = document.getElementById('toast');
      if (!host) return;
      host.innerHTML = `<span>${esc(msg)}</span>
        <button class="k-undo-btn">UNDO</button>`;
      host.classList.add('show');
      clearTimeout(host._ut);
      host._ut = setTimeout(() => {
        host.classList.remove('show'); host.innerHTML = '';
      }, seconds * 1000);
      host.querySelector('.k-undo-btn').onclick = async () => {
        clearTimeout(host._ut);
        host.classList.remove('show'); host.innerHTML = '';
        try { await undoFn(); } catch (_) { K.ui.toast('Undo failed', 'error'); }
      };
    },
  };

  // ==========================================================
  // 4. CURSOR GLOW
  // ==========================================================
  function installCursorGlow() {
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const halo = document.createElement('div');
    halo.className = 'k-cursor-halo';
    document.body.appendChild(halo);
    let tx = 0, ty = 0, cx = 0, cy = 0;
    document.addEventListener('mousemove', (e) => { tx = e.clientX; ty = e.clientY; });
    (function frame() {
      cx += (tx - cx) * 0.14; cy += (ty - cy) * 0.14;
      halo.style.transform = `translate(${cx - 150}px, ${cy - 150}px)`;
      requestAnimationFrame(frame);
    })();
  }

  // ==========================================================
  // 5. RELATIVE TIMESTAMPS (ticking)
  // ==========================================================
  function relTime(iso) {
    if (!iso) return '';
    const t = new Date(iso).getTime(); const now = Date.now();
    const s = Math.floor((now - t) / 1000);
    if (s < 5) return 'now';
    if (s < 60) return s + 's ago';
    if (s < 3600) return Math.floor(s / 60) + 'm ago';
    if (s < 86400) return Math.floor(s / 3600) + 'h ago';
    return Math.floor(s / 86400) + 'd ago';
  }
  function refreshTimestamps() {
    document.querySelectorAll('[data-rel-time]').forEach(el => {
      el.textContent = relTime(el.dataset.relTime);
    });
  }
  setInterval(refreshTimestamps, 30000);

  // ==========================================================
  // 6. DEBUG DRAWER (press `)
  // ==========================================================
  const Debug = (() => {
    const log = [];
    let panel = null;
    const origFetch = K.api._fetch.bind(K.api);
    K.api._fetch = async function (url, opts) {
      const t0 = performance.now();
      try {
        const r = await origFetch(url, opts);
        log.unshift({ url, method: (opts && opts.method) || 'GET', status: 200,
                      ms: Math.round(performance.now() - t0), ok: true,
                      at: new Date().toISOString() });
        if (log.length > 60) log.length = 60;
        return r;
      } catch (e) {
        log.unshift({ url, method: (opts && opts.method) || 'GET', status: e.status || 0,
                      ms: Math.round(performance.now() - t0), ok: false,
                      error: e.message, at: new Date().toISOString() });
        if (log.length > 60) log.length = 60;
        throw e;
      }
    };
    function toggle() {
      if (panel) { panel.remove(); panel = null; return; }
      panel = document.createElement('div');
      panel.className = 'k-debug-drawer';
      panel.innerHTML = `<div class="k-debug-head">
          <strong>API LOG · ${log.length}</strong>
          <button class="k-debug-close">✕</button>
        </div>
        <div class="k-debug-list">${
          log.map(r => `<div class="k-debug-row ${r.ok ? 'ok' : 'err'}">
            <span class="k-debug-method">${r.method}</span>
            <span class="k-debug-url">${esc(r.url.split('?')[0])}</span>
            <span class="k-debug-meta">${r.ms}ms · ${new Date(r.at).toLocaleTimeString()}</span>
            ${r.error ? `<span class="k-debug-err">${esc(r.error)}</span>` : ''}
          </div>`).join('') || '<div class="k-debug-empty">No requests yet</div>'
        }</div>`;
      panel.querySelector('.k-debug-close').onclick = toggle;
      document.body.appendChild(panel);
    }
    return { toggle, log };
  })();

  // ==========================================================
  // 7. COMMAND PALETTE
  // ==========================================================
  const Palette = (() => {
    let el, input, list, items = [], filtered = [], idx = 0;

    function commands() {
      return [
        { label: 'Reports', hint: 'Go to', icon: 'fa-flag', run: () => clickTab('reports') },
        { label: 'Users', hint: 'Go to', icon: 'fa-users', run: () => clickTab('users') },
        { label: 'Chats', hint: 'Go to', icon: 'fa-comments', run: () => clickTab('chats') },
        { label: 'Mail', hint: 'Go to', icon: 'fa-envelope', run: () => clickTab('mail') },
        { label: 'Promo', hint: 'Go to', icon: 'fa-tags', run: () => clickTab('promo') },
        { label: '2FA', hint: 'Go to', icon: 'fa-shield-alt', run: () => clickTab('twofa') },
        { label: 'Terminal', hint: 'Go to', icon: 'fa-terminal', run: () => clickTab('terminal') },
        { label: 'Add user', hint: 'Action', icon: 'fa-user-plus', run: () => K.adminPage.openAddUser() },
        { label: 'Create channel', hint: 'Action', icon: 'fa-bullhorn', run: () => K.adminPage.openCreateChannel() },
        { label: 'Generate promo', hint: 'Action', icon: 'fa-plus', run: () => K.adminPage.openGeneratePromo() },
        { label: 'Add mail account', hint: 'Action', icon: 'fa-plus', run: () => K.adminPage.openAddMailAccount() },
        { label: 'Refresh all', hint: 'Action', icon: 'fa-sync-alt', run: () => {
            K.adminPage.loadDashboard(); K.adminPage.loadReports(); K.adminPage.loadUsers();
        }},
        { label: 'Cleanup OTPs', hint: 'Danger', icon: 'fa-trash-alt', run: () => K.adminPage.cleanupOtps() },
        { label: 'Cleanup email codes', hint: 'Danger', icon: 'fa-trash-alt', run: () => K.adminPage.cleanupEmailVerifications() },
        { label: 'Cleanup QR tokens', hint: 'Danger', icon: 'fa-trash-alt', run: () => K.adminPage.cleanupQrTokens() },
        { label: 'Toggle sound', hint: 'System', icon: 'fa-volume-up', run: () => Snd.toggle() },
        { label: 'Toggle debug log', hint: 'System', icon: 'fa-bug', run: () => Debug.toggle() },
        { label: 'Toggle accent', hint: 'System', icon: 'fa-palette', run: cycleAccent },
        { label: 'Logout', hint: 'Danger', icon: 'fa-sign-out-alt', run: () => { window.location.href = '/api/admin/logout'; } },
      ];
    }

    function open() {
      if (el) return (el.style.display = 'flex', input.value = '', input.focus(), render(''));
      build();
      el.style.display = 'flex';
      input.value = ''; input.focus(); render('');
    }
    function close() { if (el) el.style.display = 'none'; }
    function build() {
      el = document.createElement('div');
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
      el.onclick = (e) => { if (e.target === el) close(); };
      document.body.appendChild(el);
      input = el.querySelector('.k-palette-input');
      list = el.querySelector('.k-palette-list');
      input.addEventListener('input', () => render(input.value));
      input.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowDown') { e.preventDefault(); idx = Math.min(filtered.length - 1, idx + 1); paint(); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); idx = Math.max(0, idx - 1); paint(); }
        else if (e.key === 'Enter') { e.preventDefault(); runCmd(); }
        else if (e.key === 'Escape') close();
      });
    }
    function render(q) {
      items = commands();
      const query = (q || '').toLowerCase().trim();
      filtered = !query ? items : items.filter(c => fuzzy(query, (c.hint + ' ' + c.label).toLowerCase()));
      idx = 0;
      list.innerHTML = filtered.map((c, i) =>
        `<div class="k-palette-item ${i === 0 ? 'sel' : ''}" data-i="${i}">
          <i class="fas ${c.icon}"></i>
          <span class="k-palette-label">${esc(c.label)}</span>
          <span class="k-palette-hint">${esc(c.hint)}</span>
        </div>`).join('') || '<div class="k-palette-empty">No matches</div>';
      list.querySelectorAll('.k-palette-item').forEach(el2 => {
        el2.onclick = () => { idx = +el2.dataset.i; runCmd(); };
        el2.onmouseenter = () => { idx = +el2.dataset.i; paint(); };
      });
    }
    function paint() {
      list.querySelectorAll('.k-palette-item').forEach((el2, i) =>
        el2.classList.toggle('sel', i === idx));
    }
    function runCmd() {
      const c = filtered[idx]; close();
      if (c) { Snd.tick(); setTimeout(() => c.run(), 30); }
    }
    return { open, close };
  })();

  // ==========================================================
  // 8. LIVE STATS (pulse + sparkline)
  // ==========================================================
  const Live = {
    history: {}, max: 30,
    patch() {
      const orig = K.adminPage.loadDashboard.bind(K.adminPage);
      K.adminPage.loadDashboard = async function () {
        await orig();
        Live.draw();
      };
      setInterval(() => K.adminPage.loadDashboard(), 30000);
    },
    draw() {
      document.querySelectorAll('#stats .stat').forEach((card) => {
        const labEl = card.querySelector('.stat-label');
        const valEl = card.querySelector('.stat-value');
        if (!labEl || !valEl) return;
        const key = labEl.textContent.trim();
        const v = valEl.textContent.trim();

        if (this.history[key] && this.history[key].length) {
          const prev = this.history[key][this.history[key].length - 1];
          if (prev !== v) {
            valEl.classList.add('k-pulse');
            setTimeout(() => valEl.classList.remove('k-pulse'), 700);
          }
        }
        if (!this.history[key]) this.history[key] = [];
        const n = parseFloat(String(v).replace(/[^\d.-]/g, ''));
        if (!isNaN(n)) {
          this.history[key].push(n);
          if (this.history[key].length > this.max) this.history[key].shift();
        }
        let cvs = card.querySelector('.k-spark');
        if (!cvs) {
          cvs = document.createElement('canvas');
          cvs.className = 'k-spark';
          card.appendChild(cvs);
        }
        this.render(cvs, this.history[key]);
      });
    },
    render(cvs, data) {
      if (!data || data.length < 2) { cvs.width = 0; cvs.height = 0; return; }
      const rect = cvs.getBoundingClientRect();
      const dpr = Math.min(devicePixelRatio || 1, 2);
      cvs.width = rect.width * dpr; cvs.height = rect.height * dpr;
      const ctx = cvs.getContext('2d');
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const W = rect.width, H = rect.height;
      const min = Math.min(...data), max = Math.max(...data);
      const span = max - min || 1;
      const x = (i) => (i / (data.length - 1)) * W;
      const y = (v) => H - 2 - ((v - min) / span) * (H - 4);
      const accent = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#00e5ff';
      const rgb = getComputedStyle(document.documentElement).getPropertyValue('--accent-rgb').trim() || '0,229,255';
      ctx.beginPath(); ctx.moveTo(x(0), y(data[0]));
      for (let i = 1; i < data.length; i++) ctx.lineTo(x(i), y(data[i]));
      ctx.strokeStyle = accent; ctx.lineWidth = 1.4; ctx.stroke();
      ctx.lineTo(W, H); ctx.lineTo(0, H); ctx.closePath();
      const grad = ctx.createLinearGradient(0, 0, 0, H);
      grad.addColorStop(0, `rgba(${rgb},.25)`);
      grad.addColorStop(1, `rgba(${rgb},0)`);
      ctx.fillStyle = grad; ctx.fill();
    },
  };

  // ==========================================================
  // 9. REPORTS OVERRIDE — clustering, guesser, bulk
  // ==========================================================
  let _selectedReportIds = new Set();
  let _currentReportFilter = 'pending';
  let _currentReportSort = 'severity';

  function installReportsOverride() {
    K.adminPage.loadReports = async function (status) {
      if (status) _currentReportFilter = status;
      const el = document.getElementById('reportsBody');
      if (!el) return;

      // Ensure toolbar exists (select filter + sort + bulk bar)
      ensureReportToolbar();

      el.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:18px;color:var(--muted)">Loading…</td></tr>';
      try {
        const d = await K.api.get(
          `/api/admin/reports/grouped?status=${_currentReportFilter}&sort=${_currentReportSort}`
        );
        if (!d.success) throw new Error('failed');
        renderGrouped(d.data);
        paintBulkBar();
      } catch (e) {
        el.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:18px;color:var(--red)">Error loading reports</td></tr>';
      }
    };
  }

  function ensureReportToolbar() {
    const host = document.querySelector('#reports-tab .section-header .toolbar');
    if (!host) return;
    const sel = host.querySelector('#reportStatus');
    if (sel && !sel.dataset.enhanced) {
      sel.dataset.enhanced = '1';
      sel.innerHTML = `
        <option value="pending">Pending</option>
        <option value="resolved">Resolved</option>
        <option value="dismissed">Dismissed</option>
        <option value="actioned_banned">Banned</option>
        <option value="actioned_deleted">Deleted</option>`;
    }
    if (!host.querySelector('#reportSort')) {
      const sort = document.createElement('select');
      sort.id = 'reportSort';
      sort.innerHTML = '<option value="severity">Sort: Severity</option><option value="date">Sort: Date</option>';
      sort.onchange = () => { _currentReportSort = sort.value; K.adminPage.loadReports(); };
      host.appendChild(sort);
    }
  }

  function renderGrouped(data) {
    const el = document.getElementById('reportsBody');
    const groups = data.groups || [];
    const singles = data.singles || [];
    const parts = [];

    if (!groups.length && !singles.length) {
      el.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:18px;color:var(--muted)">No reports</td></tr>';
      return;
    }

    // Grouped section (message-clustered)
    groups.forEach((g) => {
      const ids = g.reports.map(r => r.id);
      const checked = ids.every(id => _selectedReportIds.has(id));
      const sev = g.severity || 'medium';
      parts.push(`
        <tr class="k-report-group" data-ids="${ids.join(',')}">
          <td colspan="6">
            <div class="k-cluster">
              <div class="k-cluster-head">
                <label class="k-cluster-check">
                  <input type="checkbox" class="k-report-cb" data-group="1" ${checked ? 'checked' : ''}>
                </label>
                <span class="k-sev-badge" style="--sev:${SEV_COLOR[sev]}">
                  ${SEV_EMOJI[sev]} ${sev.toUpperCase()}
                </span>
                <span class="k-cluster-count">${g.count} reports</span>
                <span class="k-cluster-cat">${esc(g.category || 'unknown')}</span>
                <span class="k-cluster-sender">
                  on @${esc(g.sender_username || 'unknown')}
                </span>
              </div>
              ${g.message_content ? `<div class="k-cluster-msg">"${esc(g.message_content.slice(0, 200))}${g.message_content.length > 200 ? '…' : ''}"</div>` : ''}
              <div class="k-cluster-actions">
                <button class="btn btn-sm btn-success" onclick="K.adminExtras.bulkAction([${ids.join(',')}],'delete_messages')">
                  <i class="fas fa-trash"></i> Delete messages
                </button>
                <button class="btn btn-sm btn-danger" onclick="K.adminExtras.bulkAction([${ids.join(',')}],'ban_senders')">
                  <i class="fas fa-ban"></i> Ban senders
                </button>
                <button class="btn btn-sm btn-outline" onclick="K.adminExtras.bulkAction([${ids.join(',')}],'resolve')">
                  <i class="fas fa-check"></i> Resolve all
                </button>
                <button class="btn btn-sm btn-outline" onclick="K.adminExtras.bulkAction([${ids.join(',')}],'dismiss')">
                  <i class="fas fa-times"></i> Dismiss all
                </button>
              </div>
            </div>
          </td>
        </tr>`);
    });

    // Singles (un-clustered reports)
    singles.forEach((r) => {
      const sev = r.guess.severity;
      const checked = _selectedReportIds.has(r.id);
      const matchers = (r.guess.matched_keywords || []).join(', ');
      parts.push(`
        <tr data-report-id="${r.id}">
          <td><input type="checkbox" class="k-report-cb" data-id="${r.id}" ${checked ? 'checked' : ''}></td>
          <td>
            <div class="k-report-cell">
              <span class="k-sev-badge" style="--sev:${SEV_COLOR[sev]}">${SEV_EMOJI[sev]} ${sev}</span>
              <span class="k-report-id">#${r.id}</span>
            </div>
          </td>
          <td>@${esc((r.reporter_id ? 'user_' + r.reporter_id : '—'))}</td>
          <td>@${esc((r.reported_user_id ? 'user_' + r.reported_user_id : '—'))}</td>
          <td>
            <div class="k-report-reason">${esc(r.reason || '')}</div>
            ${matchers ? `<div class="k-report-hint">guessed from: <em>${esc(matchers)}</em></div>` : ''}
          </td>
          <td>
            <div class="btn-group">
              <button class="btn btn-sm" onclick="K.adminPage.resolveReport(${r.id})" title="Resolve"><i class="fas fa-check"></i></button>
              <button class="btn btn-sm btn-outline" onclick="K.adminPage.dismissReport(${r.id})" title="Dismiss"><i class="fas fa-times"></i></button>
            </div>
          </td>
        </tr>`);
    });

    el.innerHTML = parts.join('');
    refreshTimestamps();

    // Wire checkboxes
    el.querySelectorAll('.k-report-cb').forEach(cb => {
      cb.onchange = () => {
        if (cb.dataset.group) {
          const ids = cb.closest('tr').dataset.ids.split(',').map(Number);
          ids.forEach(id => cb.checked ? _selectedReportIds.add(id) : _selectedReportIds.delete(id));
        } else {
          const id = +cb.dataset.id;
          cb.checked ? _selectedReportIds.add(id) : _selectedReportIds.delete(id);
        }
        paintBulkBar();
      };
    });
  }

  function paintBulkBar() {
    let bar = document.getElementById('k-bulk-bar');
    if (_selectedReportIds.size === 0) {
      if (bar) bar.remove();
      return;
    }
    if (!bar) {
      bar = document.createElement('div');
      bar.id = 'k-bulk-bar';
      bar.className = 'k-bulk-bar';
      document.body.appendChild(bar);
    }
    bar.innerHTML = `
      <span class="k-bulk-count">${_selectedReportIds.size} selected</span>
      <button class="btn btn-sm btn-success" onclick="K.adminExtras.bulkAction([...K.adminExtras._selected()],'resolve')"><i class="fas fa-check"></i> Resolve</button>
      <button class="btn btn-sm btn-outline" onclick="K.adminExtras.bulkAction([...K.adminExtras._selected()],'dismiss')"><i class="fas fa-times"></i> Dismiss</button>
      <button class="btn btn-sm btn-warning" onclick="K.adminExtras.bulkAction([...K.adminExtras._selected()],'delete_messages')"><i class="fas fa-trash"></i> Delete msgs</button>
      <button class="btn btn-sm btn-danger" onclick="K.adminExtras.bulkAction([...K.adminExtras._selected()],'ban_senders')"><i class="fas fa-ban"></i> Ban senders</button>
      <button class="btn btn-sm btn-outline" onclick="K.adminExtras.clearSelection()"><i class="fas fa-times"></i></button>`;
  }

  // ==========================================================
  // 10. USER ROW OVERRIDE — add Panel button
  // ==========================================================
  function installUserRowOverride() {
    const orig = K.adminPage._renderUsers.bind(K.adminPage);
    K.adminPage._renderUsers = function (users) {
      orig(users);
      // Post-render: append a "Panel" button to each row's actions
      const body = document.getElementById('usersBody');
      if (!body) return;
      body.querySelectorAll('tr').forEach((row, i) => {
        const u = users[i];
        if (!u) return;
        const actions = row.querySelector('.btn-group');
        if (!actions || actions.querySelector('.k-user-panel-btn')) return;
        const btn = document.createElement('button');
        btn.className = 'btn btn-sm btn-outline k-user-panel-btn';
        btn.title = 'Notes & history';
        btn.innerHTML = '<i class="fas fa-clipboard-list"></i>';
        btn.onclick = () => openUserPanel(u.id, u.username);
        actions.appendChild(btn);
      });
    };
  }

  // ==========================================================
  // 11. USER PANEL — Notes / History / Sessions
  // ==========================================================
  async function openUserPanel(userId, username) {
    const html = `
      <div class="k-modal-overlay k-up" id="k-user-panel">
        <div class="k-up-box">
          <div class="k-up-header">
            <h3>@${esc(username)} <span class="k-up-id">#${userId}</span></h3>
            <button class="k-up-close">✕</button>
          </div>
          <div class="k-up-tabs">
            <button class="k-up-tab active" data-tab="notes">Notes</button>
            <button class="k-up-tab" data-tab="history">History</button>
            <button class="k-up-tab" data-tab="sessions">Sessions</button>
          </div>
          <div class="k-up-body">
            <div class="k-up-pane active" data-pane="notes">
              <div class="k-up-compose">
                <textarea class="k-up-input" placeholder="Add a note only admins can see..."></textarea>
                <button class="btn btn-sm" onclick="K.adminExtras.addNote(${userId})">Save</button>
              </div>
              <div class="k-up-list"></div>
            </div>
            <div class="k-up-pane" data-pane="history"><div class="k-up-list">Loading…</div></div>
            <div class="k-up-pane" data-pane="sessions"><div class="k-up-list">Loading…</div></div>
          </div>
        </div>
      </div>`;
    document.body.insertAdjacentHTML('beforeend', html);
    const root = document.getElementById('k-user-panel');
    root.querySelector('.k-up-close').onclick = () => root.remove();
    root.onclick = (e) => { if (e.target === root) root.remove(); };

    root.querySelectorAll('.k-up-tab').forEach(t => {
      t.onclick = () => {
        root.querySelectorAll('.k-up-tab').forEach(x => x.classList.toggle('active', x === t));
        root.querySelectorAll('.k-up-pane').forEach(p =>
          p.classList.toggle('active', p.dataset.pane === t.dataset.tab));
        if (t.dataset.tab === 'history') loadNotesHistory(userId);
        if (t.dataset.tab === 'sessions') loadSessions(userId);
      };
    });
    loadNotes(userId);
  }

  async function loadNotes(userId) {
    const list = document.querySelector('#k-user-panel .k-up-pane[data-pane="notes"] .k-up-list');
    if (!list) return;
    try {
      const d = await K.api.get(`/api/admin/users/${userId}/notes`);
      const notes = d.data?.notes || [];
      list.innerHTML = notes.length ? notes.map(n => `
        <div class="k-note">
          <div class="k-note-meta">@${esc(n.author_username || '?')} · ${relTime(n.created_at)}</div>
          <div class="k-note-body">${esc(n.body)}</div>
        </div>`).join('') : '<div class="k-up-empty">No notes yet</div>';
      refreshTimestamps();
    } catch (e) { list.innerHTML = '<div class="k-up-empty">Failed</div>'; }
  }

  async function loadNotesHistory(userId) {
    const list = document.querySelector('#k-user-panel .k-up-pane[data-pane="history"] .k-up-list');
    if (!list) return;
    try {
      const d = await K.api.get(`/api/admin/users/${userId}/action-log`);
      const actions = d.data?.actions || [];
      list.innerHTML = actions.length ? actions.map(a => `
        <div class="k-hist-row">
          <span class="k-hist-action">${esc(a.action)}</span>
          <span class="k-hist-actor">by @${esc(a.actor_username || 'system')}</span>
          <span class="k-hist-time" data-rel-time="${a.created_at}">${relTime(a.created_at)}</span>
        </div>`).join('') : '<div class="k-up-empty">No admin actions</div>';
      refreshTimestamps();
    } catch (e) { list.innerHTML = '<div class="k-up-empty">Failed</div>'; }
  }

  async function loadSessions(userId) {
    const list = document.querySelector('#k-user-panel .k-up-pane[data-pane="sessions"] .k-up-list');
    if (!list) return;
    try {
      const d = await K.api.get(`/api/admin/users/${userId}/sessions`);
      const s = d.data?.sessions || [];
      list.innerHTML = s.length ? s.map(x => `
        <div class="k-session-row">
          <div class="k-session-info">
            <div><strong>${esc(x.ip || '?')}</strong></div>
            <div class="k-session-ua">${esc((x.user_agent || '').slice(0, 60))}</div>
            <div class="k-session-time" data-rel-time="${x.last_active || x.created_at}">${relTime(x.last_active || x.created_at)}</div>
          </div>
          <button class="btn btn-sm btn-outline" onclick="K.adminExtras.revokeSession(${userId},${x.id})">Revoke</button>
        </div>`).join('') : '<div class="k-up-empty">No active sessions</div>';
    } catch (e) { list.innerHTML = '<div class="k-up-empty">Failed</div>'; }
  }

  // ==========================================================
  // 12. ACTIVITY FEED (SSE)
  // ==========================================================
  function installActivityFeed() {
    const panel = document.querySelector('.admin-main');
    if (!panel || document.getElementById('k-activity-feed')) return;
    const feed = document.createElement('aside');
    feed.id = 'k-activity-feed';
    feed.className = 'k-activity-feed';
    feed.innerHTML = `<div class="k-af-head"><i class="fas fa-bolt"></i> LIVE ACTIVITY</div>
      <div class="k-af-list" id="k-af-list"><div class="k-af-empty">Waiting for events…</div></div>`;
    panel.appendChild(feed);

    fetch('/api/admin/activity/recent', { headers: K.api._headers() })
      .then(r => r.json())
      .then(d => {
        const list = document.getElementById('k-af-list');
        list.innerHTML = '';
        (d.data?.events || []).slice(0, 15).forEach(pushEvent);
      }).catch(() => {});

    try {
      const es = new EventSource('/api/admin/activity/stream');
      es.onmessage = (msg) => {
        try { pushEvent(JSON.parse(msg.data)); } catch (_) {}
      };
    } catch (_) {}

    function pushEvent(e) {
      const list = document.getElementById('k-af-list');
      if (!list) return;
      if (list.querySelector('.k-af-empty')) list.innerHTML = '';
      const row = document.createElement('div');
      row.className = 'k-af-row';
      row.innerHTML = `
        <span class="k-af-actor">@${esc(e.actor || 'system')}</span>
        <span class="k-af-action">${esc(e.action)}</span>
        ${e.target_type ? `<span class="k-af-target">${e.target_type}#${e.target_id}</span>` : ''}
        <span class="k-af-time" data-rel-time="${e.created_at}">${relTime(e.created_at)}</span>`;
      list.prepend(row);
      while (list.children.length > 30) list.lastChild.remove();
    }
  }

  // ==========================================================
  // 13. KEYBOARD SHORTCUTS + KONAMI
  // ==========================================================
  let _lastKey = '', _lastKeyAt = 0;
  const KONAMI = ['ArrowUp','ArrowUp','ArrowDown','ArrowDown','ArrowLeft','ArrowRight','ArrowLeft','ArrowRight','b','a'];
  let _konamiIdx = 0;

  document.addEventListener('keydown', (e) => {
    // Konami
    if (e.key === KONAMI[_konamiIdx]) {
      _konamiIdx++;
      if (_konamiIdx === KONAMI.length) {
        _konamiIdx = 0;
        document.body.classList.toggle('k-crt');
        K.ui.toast('CRT mode toggled', 'info');
        Snd.ok();
      }
    } else {
      _konamiIdx = (e.key === KONAMI[0]) ? 1 : 0;
    }

    // Debug drawer
    if (e.key === '`' && !['INPUT','TEXTAREA'].includes(e.target.tagName) && !e.target.isContentEditable) {
      e.preventDefault(); Debug.toggle(); return;
    }
    // Palette
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault(); Palette.open(); return;
    }
    if (['INPUT','TEXTAREA'].includes(e.target.tagName) || e.target.isContentEditable) return;

    if (e.key === '?') { showShortcuts(); return; }

    const now = Date.now();
    if (_lastKey === 'g' && now - _lastKeyAt < 1200) {
      const map = { r: 'reports', u: 'users', c: 'chats', m: 'mail', p: 'promo', t: 'terminal', '2': 'twofa' };
      if (map[e.key]) { e.preventDefault(); clickTab(map[e.key]); _lastKey = ''; return; }
    }
    if (e.key === 'g') { _lastKey = 'g'; _lastKeyAt = now; }
  });

  function showShortcuts() {
    const ov = document.createElement('div');
    ov.className = 'k-shortcuts-overlay';
    ov.innerHTML = `
      <div class="k-shortcuts">
        <h3><i class="fas fa-keyboard"></i> Shortcuts</h3>
        <div class="k-sc-grid">
          <div><kbd>⌘</kbd><kbd>K</kbd> Palette</div>
          <div><kbd>G</kbd><kbd>R</kbd> Reports</div>
          <div><kbd>G</kbd><kbd>U</kbd> Users</div>
          <div><kbd>G</kbd><kbd>C</kbd> Chats</div>
          <div><kbd>G</kbd><kbd>M</kbd> Mail</div>
          <div><kbd>G</kbd><kbd>P</kbd> Promo</div>
          <div><kbd>G</kbd><kbd>2</kbd> 2FA</div>
          <div><kbd>G</kbd><kbd>T</kbd> Terminal</div>
          <div><kbd>`</kbd> Debug log</div>
          <div><kbd>?</kbd> This help</div>
          <div><kbd>↑↑↓↓←→←→BA</kbd> ???</div>
        </div>
        <button class="btn" onclick="this.closest('.k-shortcuts-overlay').remove()">Close</button>
      </div>`;
    ov.onclick = (e) => { if (e.target === ov) ov.remove(); };
    document.body.appendChild(ov);
  }

  // ==========================================================
  // 14. SORTABLE COLUMNS
  // ==========================================================
  function installSortable() {
    document.querySelectorAll('table').forEach(tbl => {
      const ths = tbl.querySelectorAll('thead th');
      ths.forEach((th, ci) => {
        if (!th.textContent.trim()) return;
        th.style.cursor = 'pointer';
        th.onclick = () => {
          const tbody = tbl.querySelector('tbody');
          if (!tbody) return;
          const rows = [...tbody.querySelectorAll('tr')];
          const isAsc = th.dataset.sort !== 'asc';
          ths.forEach(t => delete t.dataset.sort);
          th.dataset.sort = isAsc ? 'asc' : 'desc';
          rows.sort((a, b) => {
            const av = (a.children[ci]?.textContent || '').trim().toLowerCase();
            const bv = (b.children[ci]?.textContent || '').trim().toLowerCase();
            const na = parseFloat(av), nb = parseFloat(bv);
            if (!isNaN(na) && !isNaN(nb)) return isAsc ? na - nb : nb - na;
            return isAsc ? av.localeCompare(bv) : bv.localeCompare(av);
          });
          rows.forEach(r => tbody.appendChild(r));
        };
      });
    });
  }

  // ==========================================================
  // 15. TERMINAL EASTER EGGS
  // ==========================================================
  function installTerminalEggs() {
    const input = document.getElementById('terminal-input');
    const output = document.getElementById('terminal-output');
    if (!input || !output) return;

    const origKeydown = input.onkeydown;
    input.addEventListener('keydown', async (e) => {
      if (e.key !== 'Enter') return;
      const cmd = input.value.trim().toLowerCase();
      if (!['sudo', 'coffee', 'hire-me', 'hireme', 'matrix'].includes(cmd)) return;

      e.preventDefault();
      e.stopImmediatePropagation();
      input.value = '';
      const append = (html) => { output.insertAdjacentHTML('beforeend', html); output.scrollTop = output.scrollHeight; };

      if (cmd === 'sudo') {
        append('<div class="t-muted">[sudo] password for admin: ****</div>');
        await new Promise(r => setTimeout(r, 700));
        append('<div class="t-success">You are already root, @admin.</div>');
      } else if (cmd === 'coffee') {
        append(`<pre class="t-info" style="font-size:11px;line-height:1.2">      ( (
       ) )
    ........
    |      |]
    \\      /
     \\____/
    ☕  brewing...</pre>`);
      } else if (cmd === 'hire-me' || cmd === 'hireme') {
        append(`<pre class="t-success" style="font-size:11px;line-height:1.2">
   _____ _    _ _____  ______
  / ____| |  | |  __ \\|  ____|
 | (___ | |__| | |__) | |__
  \\___ \\|  __  |  _  /|  __|
  ____) | |  | | | \\ \\| |____
 |_____/|_|  |_|_|  \\_\\______|
        </pre><div class="t-info">Nice try 😉</div>`);
      } else if (cmd === 'matrix') {
        append('<div class="t-success">Entering the Matrix… (10s)</div>');
        triggerMatrix(10);
      }
    }, true);
  }

  function triggerMatrix(seconds = 6) {
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const cvs = document.createElement('canvas');
    cvs.style.cssText = 'position:fixed;inset:0;z-index:99998;pointer-events:none;opacity:.9';
    document.body.appendChild(cvs);
    const ctx = cvs.getContext('2d');
    const dpr = Math.min(devicePixelRatio || 1, 2);
    let W = innerWidth, H = innerHeight;
    cvs.width = W * dpr; cvs.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const cols = Math.floor(W / 18);
    const drops = Array.from({ length: cols }, () => Math.random() * -50);
    const chars = 'アイウエオカキクケコサシスセソタチツテトナニヌネノabcdefghijklmnopqrstuvwxyz0123456789';
    const started = Date.now();
    let raf;
    function frame() {
      ctx.fillStyle = 'rgba(4,7,14,.08)';
      ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = '#00e5ff';
      ctx.font = '14px monospace';
      for (let i = 0; i < cols; i++) {
        const ch = chars[Math.floor(Math.random() * chars.length)];
        ctx.fillText(ch, i * 18, drops[i] * 18);
        if (drops[i] * 18 > H && Math.random() > 0.975) drops[i] = 0;
        drops[i] += 0.5;
      }
      if (Date.now() - started < seconds * 1000) raf = requestAnimationFrame(frame);
      else cvs.remove();
    }
    frame();
  }

  // ==========================================================
  // HELPERS
  // ==========================================================
  function esc(s) {
    if (s == null) return '';
    const d = document.createElement('div');
    d.textContent = String(s);
    return d.innerHTML;
  }
  function clickTab(name) {
    const b = document.querySelector(`.tab[data-tab="${name}"]`);
    if (b) b.click();
  }
  function cycleAccent() {
    const btns = [...document.querySelectorAll('#accentPicker button')];
    if (!btns.length) return;
    const cur = btns.findIndex(b => b.classList.contains('on'));
    btns[(cur + 1) % btns.length].click();
  }
  function fuzzy(q, t) {
    let qi = 0;
    for (let i = 0; i < t.length && qi < q.length; i++) if (t[i] === q[qi]) qi++;
    return qi === q.length;
  }

  // ==========================================================
  // PUBLIC API (for inline handlers in tables)
  // ==========================================================
  window.K = window.K || {};
  K.adminExtras = {
    Snd, Undo, Debug, Palette, confetti, Live,
    _selected: () => _selectedReportIds,
    clearSelection: () => { _selectedReportIds.clear(); K.adminPage.loadReports(); },
    async bulkAction(ids, action) {
      if (!ids || !ids.length) return;
      if (!confirm(`${action} ${ids.length} report(s)?`)) return;
      try {
        const d = await K.api.post('/api/admin/reports/bulk', { ids, action });
        if (d.success) {
          Snd.ok();
          if (action === 'ban_senders' || action === 'delete_messages') confetti(50);
          Undo.show(`${action}: ${ids.length} applied`, async () => {
            // Undo via restore endpoints
            for (const id of ids) {
              try { await K.api.post(`/api/admin/reports/${id}/restore`); } catch (_) {}
            }
            K.adminPage.loadReports();
          });
          _selectedReportIds.clear();
          K.adminPage.loadReports();
        } else {
          K.ui.toast(d.error?.message || 'Failed', 'error');
          Snd.err();
        }
      } catch (e) {
        K.ui.toast('Error', 'error'); Snd.err();
      }
    },
    async addNote(userId) {
      const ta = document.querySelector('#k-user-panel .k-up-compose textarea');
      const body = (ta?.value || '').trim();
      if (!body) return;
      try {
        const d = await K.api.post(`/api/admin/users/${userId}/notes`, { body });
        if (d.success) { ta.value = ''; loadNotes(userId); Snd.ok(); }
      } catch (e) { K.ui.toast('Failed', 'error'); }
    },
    async revokeSession(userId, sessionId) {
      if (!confirm('Revoke this session?')) return;
      try {
        await K.api.post(`/api/admin/users/${userId}/sessions/${sessionId}/revoke`);
        Snd.ok();
        loadSessions(userId);
      } catch (e) { K.ui.toast('Failed', 'error'); }
    },
    showShortcuts,
  };

  // Expose internal helpers used by loaders above
  window._kAdminNotesLoader = loadNotes;
  window._kAdminSessionsLoader = loadSessions;
  window._kAdminHistoryLoader = loadNotesHistory;

  // ==========================================================
  // BOOT
  // ==========================================================
  document.addEventListener('DOMContentLoaded', () => {
    if (!window.K || !K.adminPage) return;

    installCursorGlow();
    installReportsOverride();
    installUserRowOverride();
    installSortable();
    installActivityFeed();
    installTerminalEggs();
    Live.patch();

    // Tab click sound
    document.querySelectorAll('.tab').forEach(t =>
      t.addEventListener('click', () => Snd.tick()));

    // Initial reports render via overridden method
    setTimeout(() => K.adminPage.loadReports(), 300);

    // Keep relative timestamps fresh
    refreshTimestamps();
  });
})();