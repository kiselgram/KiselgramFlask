'use strict';
/* K.otpWidget — OTP verification widget for Kiselgram login/registration.
 * Interaction design ported from tmp/OTP Verification/ (MIT, CodeByGaurav).
 * Differences from the demo: configurable digit count (Kiselgram codes are
 * 5 digits), REAL server-side verification via opts.verify(code) instead of
 * the demo's Math.random(), real resend via opts.resend(), Russian texts.
 *
 * Usage:
 *   K.otpWidget.mount(el, {
 *     digits: 5,
 *     subtitle: '...',
 *     verify: async (code) => ({ ok: true }),   // or { ok:false, error:'...' }
 *     resend: async () => {},
 *     onSuccess: () => {},
 *   });
 */
(function () {
  const EN = {
    title: 'Verification code',
    loadingTitle: 'Verifying...',
    loadingSubtitle: 'Checking the code with the server.',
    successTitle: 'Access granted',
    successSubtitle: 'Welcome!',
    errorTitle: 'Wrong code',
    badge: 'OK',
    errorText: 'Wrong code. Please try again.',
    resend: 'Didn\'t get it? <span>Resend</span>',
    resendWait: 'Didn\'t get it? <span>Wait…</span>',
  };

  function el(tag, cls, html) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }

  // Long cinematic timings (user request: animation should feel longer).
  const ORBIT_MS = 2600;
  const LOAD_MIN_MS = 1800;
  const SUCCESS_DELAY_MS = 1800;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));

  function mount(container, opts) {
    opts = opts || {};
    const digits = Math.min(8, Math.max(4, opts.digits || 5));
    const T = Object.assign({}, EN, opts.texts || {});
    if (opts.title) T.title = opts.title;
    if (opts.subtitle) T.subtitle = opts.subtitle;

    container.innerHTML = '';
    const card = el('div', 'k-otp-card');
    if (opts.bare) card.classList.add('k-otp-bare');
    const title = el('h1', 'k-otp-title', '');
    title.textContent = T.title;
    const sub = el('p', 'k-otp-sub', '');
    sub.textContent = T.subtitle || '';
    const arena = el('div', 'k-otp-arena');
    const stage = el('div', 'k-otp-stage');
    const inputs = [];
    for (let i = 0; i < digits; i++) {
      const inp = document.createElement('input');
      inp.type = 'text';
      inp.className = 'k-otp-pill';
      inp.maxLength = 1;
      inp.inputMode = 'numeric';
      inp.autocomplete = 'one-time-code';
      inp.setAttribute('aria-label', 'Digit ' + (i + 1));
      stage.appendChild(inp);
      inputs.push(inp);
    }
    const orbit = el('div', 'k-otp-orbit');
    const ring = el('div', 'k-otp-ring');
    orbit.appendChild(ring);
    const load = el('div', 'k-otp-load');
    load.innerHTML = '<div class="k-otp-core"><div class="k-otp-loadring"></div><div class="k-otp-pulse"></div><div class="k-otp-pct">0</div></div>';
    const pct = load.querySelector('.k-otp-pct');
    const ok = el('div', 'k-otp-ok');
    ok.innerHTML = '<div class="k-otp-flash"></div><div class="k-otp-bubble"></div><div class="k-otp-bubble"></div><div class="k-otp-bubble"></div>' +
      '<div class="k-otp-vault"><svg class="k-otp-check" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"></polyline></svg></div>' +
      '<div class="k-otp-badge"></div>';
    ok.querySelector('.k-otp-badge').textContent = T.badge;
    arena.appendChild(stage);
    arena.appendChild(orbit);
    arena.appendChild(load);
    arena.appendChild(ok);
    const err = el('div', 'k-otp-err', '');
    const resend = el('button', 'k-otp-resend', T.resend);
    resend.type = 'button';
    card.appendChild(title);
    card.appendChild(sub);
    card.appendChild(arena);
    card.appendChild(err);
    card.appendChild(resend);
    container.appendChild(card);

    let state = 'idle';
    const timers = [];
    let resetTimer = 0;
    function later(fn, ms) { timers.push(setTimeout(fn, ms)); }
    function clearTimers() { timers.forEach(clearTimeout); timers.length = 0; clearTimeout(resetTimer); }

    function setTexts(t, s) { title.textContent = t; if (s !== undefined) sub.textContent = s; }

    function collect() { return inputs.map((i) => i.value).join(''); }

    function reset(full) {
      clearTimers();
      state = 'idle';
      card.classList.remove('k-otp-shake', 'k-otp-tint');
      err.classList.remove('k-otp-show');
      setTexts(T.title, T.subtitle);
      orbit.classList.remove('k-otp-on');
      ring.classList.remove('k-otp-spin');
      ring.innerHTML = '';
      load.classList.remove('k-otp-on');
      pct.textContent = '0';
      ok.classList.remove('k-otp-on');
      ok.querySelectorAll('.k-otp-confetti').forEach((c) => c.remove());
      inputs.forEach((i) => { i.value = ''; i.classList.remove('k-otp-error', 'k-otp-filled'); i.disabled = false; });
      stage.style.display = '';
      stage.classList.remove('k-otp-hidden');
      resend.style.display = '';
      if (full !== false) setTimeout(() => inputs[0] && inputs[0].focus(), 50);
    }

    function fail(msg) {
      state = 'error';
      load.classList.remove('k-otp-on');
      card.classList.add('k-otp-shake');
      err.textContent = msg || T.errorText;
      err.classList.add('k-otp-show');
      setTexts(T.errorTitle, T.subtitle);
      inputs.forEach((i) => { i.classList.add('k-otp-error'); i.disabled = false; });
      stage.style.display = '';
      stage.classList.remove('k-otp-hidden');
      later(() => card.classList.remove('k-otp-shake'), 500);
      resetTimer = setTimeout(() => { if (state === 'error') reset(false); }, 2500);
    }

    function win() {
      state = 'success';
      load.classList.remove('k-otp-on');
      splash(ok);
      ok.classList.add('k-otp-on');
      card.classList.add('k-otp-tint');
      resend.style.display = 'none';
      later(() => setTexts(T.successTitle, T.successSubtitle), 400);
      later(() => { if (opts.onSuccess) opts.onSuccess(); }, SUCCESS_DELAY_MS);
    }

    function splash(host) {
      host.querySelectorAll('.k-otp-confetti').forEach((c) => c.remove());
      const colors = ['#10b981', '#34d399', '#6ee7b7', '#6366f1', '#a78bfa', '#fbbf24', '#f472b6', '#22d3ee'];
      for (let i = 0; i < 24; i++) {
        const a = (i / 24) * Math.PI * 2 + (Math.random() - 0.5) * 0.25;
        const d = 90 + Math.random() * 70;
        const dot = el('div', 'k-otp-confetti');
        dot.style.background = colors[i % colors.length];
        dot.style.setProperty('--cx', Math.cos(a) * d + 'px');
        dot.style.setProperty('--cy', Math.sin(a) * d + 'px');
        dot.style.animationDelay = (0.1 + Math.random() * 0.15) + 's';
        const s = 6 + Math.random() * 10;
        dot.style.width = s + 'px';
        dot.style.height = s + 'px';
        dot.style.borderRadius = i % 3 === 0 ? '2px' : '50%';
        host.appendChild(dot);
      }
    }

    function orbitPlay() {
      ring.innerHTML = '';
      const radius = 34 + digits * 6;
      const vals = inputs.map((i) => i.value);
      for (let i = 0; i < digits; i++) {
        const a = (i / digits) * Math.PI * 2 - Math.PI / 2;
        const n = el('div', 'k-otp-node', '');
        n.textContent = vals[i] || '';
        n.style.setProperty('--dx', Math.cos(a) * radius + 'px');
        n.style.setProperty('--dy', Math.sin(a) * radius + 'px');
        n.style.animationDelay = (i * 90) + 'ms';
        ring.appendChild(n);
      }
      orbit.classList.add('k-otp-on');
      void ring.offsetWidth;
      ring.classList.add('k-otp-spin');
      ring.querySelectorAll('.k-otp-node').forEach((n) => n.classList.add('k-otp-fly'));
    }

    async function submit(code) {
      if (state === 'loading' || state === 'success') return;
      state = 'loading';
      clearTimers();
      inputs.forEach((i) => { i.disabled = true; });
      stage.classList.add('k-otp-hidden');
      orbitPlay();
      setTexts(T.loadingTitle, T.loadingSubtitle);
      later(() => {
        orbit.classList.remove('k-otp-on');
        ring.classList.remove('k-otp-spin');
        ring.innerHTML = '';
        stage.style.display = 'none';
        load.classList.add('k-otp-on');
        const t0 = performance.now();
        (function tick(now) {
          const p = Math.min((now - t0) / LOAD_MIN_MS, 1);
          pct.textContent = Math.round((1 - Math.pow(1 - p, 2.2)) * 100);
          if (p < 1 && state === 'loading') requestAnimationFrame(tick);
        })(t0);
      }, ORBIT_MS);
      let res;
      try {
        // Real server check, but never faster than the loading cinematic.
        const out = await Promise.all([
          opts.verify ? opts.verify(code) : { ok: true },
          wait(ORBIT_MS + LOAD_MIN_MS),
        ]);
        res = out[0];
      } catch (e) {
        res = { ok: false, error: 'Network error' };
      }
      if (state !== 'loading') return;
      if (res && res.ok) win();
      else fail(res && res.error);
    }

    inputs.forEach((input, index) => {
      input.addEventListener('input', (e) => {
        if (state === 'loading' || state === 'success') return;
        if (state === 'error') reset(false);
        const v = e.target.value.replace(/[^0-9]/g, '').slice(-1);
        e.target.value = v;
        e.target.classList.toggle('k-otp-filled', !!v);
        if (v && index < inputs.length - 1) inputs[index + 1].focus();
        else if (v && collect().length === digits) submit(collect());
      });
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Backspace' && !e.target.value && index > 0) inputs[index - 1].focus();
      });
      input.addEventListener('focus', () => input.select());
      input.addEventListener('paste', (e) => {
        e.preventDefault();
        const text = ((e.clipboardData || window.clipboardData).getData('text') || '').replace(/[^0-9]/g, '');
        if (!text) return;
        for (let k = 0; k < digits; k++) {
          inputs[k].value = text[k] || '';
          inputs[k].classList.toggle('k-otp-filled', !!inputs[k].value);
        }
        if (collect().length === digits) submit(collect());
        else inputs[Math.min(text.length, digits - 1)].focus();
      });
    });

    let resendCd = 0;
    resend.addEventListener('click', async () => {
      if (resendCd > 0 || state === 'loading' || state === 'success') return;
      resendCd = opts.resendCooldown || 30;
      resend.disabled = true;
      resend.innerHTML = T.resendWait;
      const iv = setInterval(() => {
        resendCd -= 1;
        if (resendCd <= 0) {
          clearInterval(iv);
          resend.disabled = false;
          resend.innerHTML = T.resend;
        }
      }, 1000);
      try { if (opts.resend) await opts.resend(); } catch (e) { /* toast left to caller */ }
      reset(true);
    });

    setTimeout(() => inputs[0] && inputs[0].focus(), 300);
    return { reset, focus: () => inputs[0] && inputs[0].focus(), element: card };
  }

  window.K = window.K || {};
  K.otpWidget = { mount };
})();
