'use strict';
/* K.groupExtras — Sputnik-style group extras (join requests, member perms, restrictions, albums). */
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
  function modal(title, bodyEl) {
    const ov = el('div', 'k-sp-modal');
    const box = el('div', 'k-sp-modal-box');
    const h = el('div', 'k-sp-modal-title', '');
    h.textContent = title;
    const x = el('button', 'k-sp-modal-x', '×');
    x.onclick = function () { ov.remove(); };
    box.appendChild(h); box.appendChild(x); box.appendChild(bodyEl);
    ov.appendChild(box);
    ov.onclick = function (e) { if (e.target === ov) ov.remove(); };
    document.body.appendChild(ov);
    return ov;
  }

  const api = {
    joinDirect: (chat_id) => req('/groups/' + chat_id + '/join', { method: 'POST' }),
    joinRequest: (chat_id) => req('/groups/' + chat_id + '/request', { method: 'POST' }),
    joinRequests: (chat_id) => req('/groups/' + chat_id + '/requests'),
    joinApprove: (chat_id, user_id) => req('/groups/' + chat_id + '/approve', { method: 'POST', body: JSON.stringify({ user_id }) }),
    joinReject: (chat_id, user_id) => req('/groups/' + chat_id + '/reject', { method: 'POST', body: JSON.stringify({ user_id }) }),
    memberPerms: (chat_id, user_id) => req('/groups/' + chat_id + '/members/' + user_id + '/perms'),
    memberPermsSet: (chat_id, user_id, perms) => req('/groups/' + chat_id + '/members/' + user_id + '/perms', { method: 'POST', body: JSON.stringify({ perms }) }),
    restrict: (chat_id, kind, user_id, extra) => req('/groups/' + chat_id + '/restrict', { method: 'POST', body: JSON.stringify(Object.assign({ kind, user_id }, extra || {})) }),
    unrestrict: (chat_id, kind, user_id) => req('/groups/' + chat_id + '/unrestrict', { method: 'POST', body: JSON.stringify({ kind, user_id }) }),
    restricted: (chat_id) => req('/groups/' + chat_id + '/restricted'),
    albumLookup: (ids) => req('/albums/lookup', { method: 'POST', body: JSON.stringify({ message_ids: ids }) }),
  };

  function groupAlbums() {
    const mc = document.getElementById('messagesContainer');
    if (!mc) return Promise.resolve();
    const nodes = Array.prototype.slice.call(mc.querySelectorAll('[data-msg-id]'));
    const ids = nodes.map(function (n) { return +n.getAttribute('data-msg-id'); }).filter(Boolean);
    if (!ids.length) return Promise.resolve();
    return api.albumLookup(ids).then(function (r) {
      const map = (r && r.data && r.data.albums) || {};
      const seen = {};
      Object.keys(map).forEach(function (mid) {
        const a = map[mid];
        if (seen[a.album_id] || !a.members || a.members.length < 2) return;
        const memberNodes = a.members
          .map(function (id) { return mc.querySelector('[data-msg-id="' + id + '"]'); })
          .filter(Boolean);
        if (memberNodes.length < 2) return;
        seen[a.album_id] = true;
        const first = memberNodes[0];
        const grid = document.createElement('div');
        grid.className = 'k-sp-album';
        memberNodes.forEach(function (node, i) {
          if (i > 0) node.style.display = 'none';
          const media = node.querySelector('.k-msg-attachment img, .k-msg-attachment video, .k-sp-round video, .k-sp-sticker img, .k-msg-file a');
          if (media) {
            const c = media.cloneNode(true);
            c.removeAttribute('onclick');
            c.onclick = function () {
              const o = media;
              if (o.tagName === 'VIDEO') { o.paused ? o.play() : o.pause(); }
              else if (o.tagName === 'A') window.open(o.href, '_blank');
              else if (o.tagName === 'IMG') {
                const src = o.currentSrc || o.src;
                if (window.K && K.features && K.features.showMediaViewer) K.features.showMediaViewer([{ file_url: src, file_type: 'image', file_name: '' }], 0);
                else window.open(src, '_blank');
              }
            };
            grid.appendChild(c);
          }
        });
        const old = first.querySelector('.k-msg-attachment, .k-sp-round, .k-sp-sticker');
        if (old) old.style.display = 'none';
        const bubble = first.querySelector('.k-msg-bubble');
        if (bubble) bubble.parentNode.insertBefore(grid, bubble);
        else first.appendChild(grid);
      });
    }).catch(function () {});
  }

  window.K = window.K || {};
  window.K.groupExtras = Object.assign({}, api, { groupAlbums });
})();
