'use strict';

document.addEventListener('DOMContentLoaded', function () {
  if (window.K && K.adminPage) {
    K.adminPage.init();
    K.adminPage.initTabs();
  }

  (function () {
    const picker = document.getElementById('accentPicker');
    if (!picker) return;
    picker.addEventListener('click', function (e) {
      const btn = e.target.closest('button');
      if (!btn) return;
      picker.querySelectorAll('button').forEach(b => b.classList.remove('on'));
      btn.classList.add('on');
      const root = document.documentElement.style;
      root.setProperty('--accent', btn.dataset.accent);
      root.setProperty('--accent-rgb', btn.dataset.rgb);
      root.setProperty('--accent2', btn.dataset.accent2);
    });
  })();

  (function () {
    const cvs = document.getElementById('bg-canvas');
    if (!cvs) return;
    const ctx = cvs.getContext('2d');
    let W = 0, H = 0, parts = [];

    function accentRgb() {
      return getComputedStyle(document.documentElement)
        .getPropertyValue('--accent-rgb').trim() || '0,229,255';
    }

    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = window.innerWidth;
      H = window.innerHeight;
      cvs.width = W * dpr;
      cvs.height = H * dpr;
      cvs.style.width = W + 'px';
      cvs.style.height = H + 'px';
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      const count = Math.min(80, Math.floor(W * H / 22000));
      parts = Array.from({ length: count }, () => ({
        x: Math.random() * W,
        y: Math.random() * H,
        vx: (Math.random() - 0.5) * 0.3,
        vy: (Math.random() - 0.5) * 0.3,
        r: 0.6 + Math.random() * 1.2
      }));
    }

    function frame() {
      ctx.clearRect(0, 0, W, H);
      const rgb = accentRgb();

      for (const p of parts) {
        p.x += p.vx;
        p.y += p.vy;
        if (p.x < 0) p.x = W;
        if (p.x > W) p.x = 0;
        if (p.y < 0) p.y = H;
        if (p.y > H) p.y = 0;
      }

      for (let i = 0; i < parts.length; i++) {
        const a = parts[i];
        for (let j = i + 1; j < parts.length; j++) {
          const b = parts[j];
          const dx = a.x - b.x, dy = a.y - b.y;
          const d2 = dx * dx + dy * dy;
          if (d2 < 16000) {
            const alpha = (1 - d2 / 16000) * 0.4;
            ctx.strokeStyle = `rgba(${rgb},${alpha * 0.35})`;
            ctx.lineWidth = 0.6;
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.stroke();
          }
        }
      }

      for (const p of parts) {
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, 7);
        ctx.fillStyle = `rgba(${rgb},.55)`;
        ctx.fill();
      }

      requestAnimationFrame(frame);
    }

    window.addEventListener('resize', resize);
    resize();
    requestAnimationFrame(frame);
  })();
});
