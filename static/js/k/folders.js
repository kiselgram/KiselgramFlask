'use strict';
/* K.folders — Sputnik-style folders bar. */
(function () {
  const V2 = (window.V2 || '/api.v2/api');
  const B = V2 + '/sputnik';

  async function req(path, opts) {
    opts = opts || {};
    const res = await fetch(B + path, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts));
    return res.json().catch(() => ({ success: false }));
  }
  function el(tag, cls, html) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }

  const api = {
    folders: () => req('/folders'),
    folderCreate: (name) => req('/folders/create', { method: 'POST', body: JSON.stringify({ name }) }),
    folderSetChats: (id, chats) => req('/folders/' + id + '/chats', { method: 'POST', body: JSON.stringify({ chats }) }),
  };

  function renderFoldersBar(mount, onPick) {
    if (!mount) return Promise.resolve();
    return api.folders().then(function (r) {
      mount.innerHTML = '';
      const all = el('button', 'k-folder-chip active', 'All chats');
      all.onclick = function () {
        mount.querySelectorAll('.k-folder-chip').forEach(function (c) { c.classList.remove('active'); });
        all.classList.add('active');
        if (onPick) onPick(null);
      };
      mount.appendChild(all);
      ((r && r.data && r.data.folders) || []).forEach(function (f) {
        const b = el('button', 'k-folder-chip', '');
        b.textContent = f.name;
        b.onclick = function () {
          mount.querySelectorAll('.k-folder-chip').forEach(function (c) { c.classList.remove('active'); });
          b.classList.add('active');
          if (onPick) onPick(f);
        };
        mount.appendChild(b);
      });
    }).catch(function () {});
  }

  window.K = window.K || {};
  window.K.folders = Object.assign({}, api, { renderFoldersBar });
})();
