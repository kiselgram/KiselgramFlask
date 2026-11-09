const TOAST_TIMEOUT = 2500;
const FOCUS_DELAY = 100;

K.ui = {
  toast(msg, type='info') {
    // Delegates to the stacked toast system in notify.js (single fallback if missing)
    if (K.notify && K.notify.toast) { K.notify.toast(msg, type); return; }
    const t = $('toast'); if (!t) return;
    t.textContent = msg; t.className = 'k-toast show';
    clearTimeout(t._t); t._t = setTimeout(() => t.classList.remove('show'), TOAST_TIMEOUT);
  },
  confirm(msg) { return new Promise(resolve => {
    const o = $('modalOverlay'); o.style.display = 'flex';
    $('modalContent').innerHTML = `
      <div class="k-modal-header"><h3>Confirm</h3></div>
      <div class="k-modal-body"><p>${esc(msg)}</p></div>
      <div class="k-modal-footer">
        <button class="k-btn k-btn-secondary" onclick="K.modals.close();K.ui._confirmRes(false)">Cancel</button>
        <button class="k-btn k-btn-danger" onclick="K.modals.close();K.ui._confirmRes(true)">Confirm</button>
      </div>`;
    K.ui._confirmRes = resolve;
  })},
  prompt(msg, defaultValue='') { return new Promise(resolve => {
    const o = $('modalOverlay'); o.style.display = 'flex';
    const mid = 'uiPrompt_' + Date.now();
    $('modalContent').innerHTML = `
      <div class="k-modal-header"><h3>${esc(msg)}</h3><button class="k-modal-close" onclick="K.modals.close();K.ui._promptRes()"><i class="fas fa-times"></i></button></div>
      <div class="k-modal-body">
        <input class="k-input" id="${mid}" value="${esc(defaultValue)}" placeholder="${esc(msg)}" autocomplete="off">
      </div>
      <div class="k-modal-footer">
        <button class="k-btn k-btn-secondary" onclick="K.modals.close();K.ui._promptRes()">Cancel</button>
        <button class="k-btn k-btn-primary" onclick="K.ui._promptRes(document.getElementById('${mid}')?.value||'')">OK</button>
      </div>`;
    setTimeout(() => document.getElementById(mid)?.focus(), FOCUS_DELAY);
    K.ui._promptRes = resolve;
  })},
  formatSize(bytes) { if (!bytes || bytes <= 0) return ''; const u = ['B','KB','MB','GB']; let i = 0; let s = bytes; while (s >= 1024 && i < u.length-1) { s /= 1024; i++; } return s.toFixed(i===0?0:1) + ' ' + u[i]; },
  loader() { return '<div class="k-loader"></div>'; },
  avatar(name='?', url='', isBot=false) {
    if (url) return `<img src="${esc(url)}" alt="" style="width:100%;height:100%;object-fit:cover" onerror="K.ui._avatarFallback(this,'${esc(name)}',${isBot})">`;
    if (isBot) return `<span style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;border-radius:50%;color:white;font-weight:600;background:linear-gradient(135deg,#6c5ce7,#a29bfe);font-size:20px"><i class="fas fa-robot"></i></span>`;
    const l = (name||'?')[0].toUpperCase();
    return `<span style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;border-radius:50%;color:white;font-weight:600;background:linear-gradient(135deg,var(--accent-blue),var(--accent-green))">${l}</span>`;
  },
  _avatarFallback(img, name, isBot) {
    if (!img || img._fb) return; img._fb = true;
    const p = img.parentElement;
    if (!p) return;
    img.style.display = 'none';
    if (isBot) {
      p.innerHTML = '<i class="fas fa-robot" style="font-size:20px"></i>';
      p.style.background = 'linear-gradient(135deg,#6c5ce7,#a29bfe)';
    } else {
      const l = (name||'?')[0].toUpperCase();
      p.textContent = l;
      p.style.background = 'linear-gradient(135deg,var(--accent-blue),var(--accent-green))';
    }
  },
  renderUser() {
    const u = K.state.user; if (!u) return;
    const av = $('sidebarAvatar'); if (av) av.innerHTML = K.ui.avatar(u.username, u.avatar_url);
    const nm = $('sidebarName'); if (nm) nm.innerHTML = esc(u.display_name || u.username) + (u.is_premium ? ' <img src="/static/img/img.png" alt="" style="width:18px;height:18px;vertical-align:middle;display:inline-block" title="Premium status">' : '');
    const un = $('sidebarUsername'); if (un) un.textContent = '@' + u.username;
  }
};
