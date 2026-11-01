'use strict';
/* K.extras — Sputnik-style extras (ported from ilyyagoncharow12/sputnik).
 * Backend: /api.v2/api/sputnik/* (see app/routes/spav2/sputnik.py).
 */
(function () {
  const V2 = (window.V2 || '/api.v2/api');
  const B = V2 + '/sputnik';

  async function req(path, opts) {
    opts = opts || {};
    const res = await fetch(B + path, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts));
    return res.json().catch(() => ({ success: false }));
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
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
    box.appendChild(h);
    box.appendChild(x);
    box.appendChild(bodyEl);
    ov.appendChild(box);
    ov.onclick = function (e) { if (e.target === ov) ov.remove(); };
    document.body.appendChild(ov);
    return ov;
  }

  function renderExtra(text) {
    let html = (window.K && K.markdown) ? K.markdown.render(text || '') : String(text || '');
    html = html
      .replace(/<spoiler>([\s\S]*?)<\/spoiler>/g, '<span class="k-spoiler">$1</span>')
      .replace(/<quote>([\s\S]*?)<\/quote>/g, '<blockquote>$1</blockquote>')
      .replace(/<monoall>([\s\S]*?)<\/monoall>/g, '<pre class="k-copy-code">$1</pre>');
    html = html.replace(/(^|[\s(])((https?:\/\/[^\s<]+))/g, function (m, pre, url) {
      if (m.indexOf('<a') !== -1) return m;
      return pre + '<a href="' + url + '" target="_blank" rel="noopener">' + url + '</a>';
    });
    return html;
  }
  function wrapSelection(input, before, after) {
    if (!input || typeof input.selectionStart !== 'number') return;
    const s = input.selectionStart, e = input.selectionEnd, v = input.value;
    const sel = v.slice(s, e) || 'text';
    input.value = v.slice(0, s) + before + sel + after + v.slice(e);
    input.focus();
  }

  const api = {
    editWithHistory: (id, content) => req('/messages/' + id + '/edit', { method: 'POST', body: JSON.stringify({ content }) }),
    edits: (id) => req('/messages/' + id + '/edits'),
    trashList: () => req('/trash'),
    trashMove: (id) => req('/messages/' + id + '/trash', { method: 'POST' }),
    trashRestore: (id) => req('/trash/restore', { method: 'POST', body: JSON.stringify({ message_id: id }) }),
    trashClear: () => req('/trash/clear', { method: 'POST' }),
    preview: (url) => req('/link_preview?url=' + encodeURIComponent(url)),
    view: (id) => req('/messages/' + id + '/view', { method: 'POST' }),
    albumCreate: (ids) => req('/albums/create', { method: 'POST', body: JSON.stringify({ message_ids: ids }) }),
    albumGet: (aid) => req('/albums/' + encodeURIComponent(aid)),
    albumReorder: (aid, ids) => req('/albums/' + encodeURIComponent(aid) + '/reorder', { method: 'POST', body: JSON.stringify({ message_ids: ids }) }),
    roundSend: (chat_id, file_path, duration, caption) => req('/round/send', { method: 'POST', body: JSON.stringify({ chat_id, file_path, duration, caption }) }),
    stickers: (fav) => req('/stickers' + (fav ? '?favorite=1' : '')),
    stickerUpload: (file_path, emoji) => req('/stickers/upload', { method: 'POST', body: JSON.stringify({ file_path, emoji }) }),
    stickerFav: (id, favorite) => req('/stickers/' + id + '/favorite', { method: 'POST', body: JSON.stringify({ favorite }) }),
    stickerFromMessage: (message_id, emoji) => req('/stickers/from_message', { method: 'POST', body: JSON.stringify({ message_id, emoji }) }),
    stickerSend: (sticker_id, chat_id) => req('/stickers/send', { method: 'POST', body: JSON.stringify({ sticker_id, chat_id }) }),
    pollClose: (id) => req('/polls/' + id + '/close', { method: 'POST' }),
    pollResults: (id) => req('/polls/' + id + '/results'),
    exportData: () => req('/export', { method: 'POST' }),
    uploadImage: (formData) => fetch(B + '/upload', { method: 'POST', body: formData }).then((r) => r.json().catch(() => ({ success: false }))),
    albumLookup: (ids) => req('/albums/lookup', { method: 'POST', body: JSON.stringify({ message_ids: ids }) }),
  };

  function showEdits(messageId) {
    return api.edits(messageId).then(function (r) {
      const list = el('div', 'k-sp-list');
      const edits = (r && r.data && r.data.edits) || [];
      if (!edits.length) list.appendChild(el('div', 'k-sp-empty', 'No edits yet'));
      edits.forEach(function (e) {
        const row = el('div', 'k-sp-row');
        const from = el('div', 'k-sp-old', '');
        from.textContent = e.old_text || '';
        const to = el('div', 'k-sp-new', '');
        to.textContent = '→ ' + (e.new_text || '');
        row.appendChild(from);
        row.appendChild(to);
        list.appendChild(row);
      });
      modal('Edit history', list);
    });
  }
  function showTrash(onRestore) {
    return api.trashList().then(function (r) {
      const list = el('div', 'k-sp-list');
      const items = (r && r.data && r.data.trash) || [];
      if (!items.length) list.appendChild(el('div', 'k-sp-empty', 'Trash is empty'));
      items.forEach(function (t) {
        const row = el('div', 'k-sp-row');
        const tx = el('span', 'k-sp-text', '');
        tx.textContent = t.snapshot || ('#' + t.message_id);
        const btn = el('button', 'k-sp-btn', 'Restore');
        btn.onclick = function () {
          api.trashRestore(t.message_id).then(function () {
            row.remove();
            if (onRestore) onRestore(t.message_id);
          });
        };
        row.appendChild(tx);
        row.appendChild(btn);
        list.appendChild(row);
      });
      const foot = el('div', 'k-sp-foot');
      const clear = el('button', 'k-sp-btn danger', 'Empty trash');
      clear.onclick = function () { api.trashClear().then(function () { list.innerHTML = ''; }); };
      const wrap = el('div', '');
      wrap.appendChild(list);
      foot.appendChild(clear);
      wrap.appendChild(foot);
      modal('Trash', wrap);
    });
  }
  function showDiscover(kind) {
    return api.discover(kind || 'all').then(function (r) {
      const list = el('div', 'k-sp-list');
      const chats = (r && r.data && r.data.chats) || [];
      if (!chats.length) list.appendChild(el('div', 'k-sp-empty', 'No public chats yet'));
      chats.forEach(function (c) {
        const row = el('div', 'k-sp-row');
        const tx = el('span', 'k-sp-text', '');
        tx.textContent = (c.name || '?') + ' · ' + (c.members || 0);
        row.appendChild(tx);
        if (!c.joined && !c.request_pending) {
          const isGroup = c.chat_type === 'group';
          const btn = el('button', 'k-sp-btn', isGroup ? 'Join' : 'Subscribe');
          btn.onclick = function () {
            const p = isGroup ? api.joinDirect(c.chat_id) : api.channelSub(c.chat_id);
            p.then(function () { btn.textContent = 'Done'; btn.disabled = true; });
          };
          row.appendChild(btn);
        } else {
          const st = el('span', 'k-sp-muted', c.joined ? "You're in" : 'Request sent');
          row.appendChild(st);
        }
        list.appendChild(row);
      });
      modal('Discover', list);
    });
  }
  function showStickers(opts) {
    opts = opts || {};
    return api.stickers().then(function (r) {
      const grid = el('div', 'k-sp-grid');
      const items = (r && r.data && r.data.stickers) || [];
      if (!items.length) grid.appendChild(el('div', 'k-sp-empty', 'No stickers yet — create the first one'));
      items.forEach(function (s) {
        const cell = el('div', 'k-sp-cell');
        const img = document.createElement('img');
        img.src = '/uploads/' + s.file_path;
        img.loading = 'lazy';
        if (opts.sendMode) {
          img.style.cursor = 'pointer';
          img.title = 'Send to current chat';
          cell.onclick = function () {
            api.stickerSendToActive(s.id).then(function (rr) {
              if (window.K && K.ui && K.ui.toast) K.ui.toast(rr && rr.success ? 'Sticker sent' : 'Open a chat', rr && rr.success ? 'success' : 'error');
              if (rr && rr.success) { const m = document.querySelector('.k-sp-modal'); if (m) m.remove(); if (window.K && K.chat && K.state && K.state.activeChat) K.chat.loadMessages(K.state.activeChat.type, K.state.activeChat.id); }
            });
          };
        }
        const fav = el('button', 'k-sp-fav', s.is_favorite ? '★' : '☆');
        fav.title = 'Favorite';
        fav.onclick = function (e) {
          e.stopPropagation();
          api.stickerFav(s.id).then(function (rr) {
            if (rr && rr.success) fav.textContent = rr.data.is_favorite ? '★' : '☆';
          });
        };
        cell.appendChild(img);
        cell.appendChild(fav);
        grid.appendChild(cell);
      });
      const wrap = el('div', '');
      wrap.appendChild(grid);
      const foot = el('div', 'k-sp-foot');
      const create = el('button', 'k-sp-btn', 'Create sticker');
      create.onclick = function () { stickerEditor(); };
      foot.appendChild(create);
      wrap.appendChild(foot);
      modal('My stickers', wrap);
    });
  }
  function stickerEditor() {
    const wrap = el('div', 'k-sp-editor');
    const file = document.createElement('input');
    file.type = 'file'; file.accept = 'image/*';
    const canvas = document.createElement('canvas');
    canvas.width = 256; canvas.height = 256; canvas.className = 'k-sp-canvas';
    const zoom = document.createElement('input');
    zoom.type = 'range'; zoom.min = '50'; zoom.max = '300'; zoom.value = '100';
    const emo = document.createElement('input');
    emo.placeholder = 'Emoji (optional)'; emo.maxLength = 8; emo.className = 'k-sp-inp';
    const save = el('button', 'k-sp-btn', 'Save sticker');
    const img = new Image();
    let loaded = false, z = 1, dx = 0, dy = 0, drag = null;
    function draw() {
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, 256, 256);
      if (loaded) {
        const s = Math.max(256 / img.width, 256 / img.height) * z;
        const w = img.width * s, hh = img.height * s;
        ctx.drawImage(img, (256 - w) / 2 + dx, (256 - hh) / 2 + dy, w, hh);
      }
      if (emo.value) { ctx.font = '64px serif'; ctx.fillText(emo.value, 180, 230); }
    }
    file.onchange = function () {
      const f = file.files[0];
      if (!f) return;
      img.onload = function () { loaded = true; draw(); };
      img.src = URL.createObjectURL(f);
    };
    zoom.oninput = function () { z = zoom.value / 100; draw(); };
    emo.oninput = draw;
    canvas.onmousedown = function (e) { drag = { x: e.clientX - dx, y: e.clientY - dy }; };
    window.addEventListener('mouseup', function () { drag = null; });
    canvas.onmousemove = function (e) { if (drag) { dx = e.clientX - drag.x; dy = e.clientY - drag.y; draw(); } };
    canvas.ontouchstart = function (e) { const t = e.touches[0]; drag = { x: t.clientX - dx, y: t.clientY - dy }; };
    canvas.ontouchmove = function (e) { if (drag) { const t = e.touches[0]; dx = t.clientX - drag.x; dy = t.clientY - drag.y; draw(); } };
    canvas.ontouchend = function () { drag = null; };
    save.onclick = function () {
      if (!loaded) return;
      canvas.toBlob(function (blob) {
        const fd = new FormData();
        fd.append('file', blob, 'sticker.png');
        api.uploadImage(fd).then(function (r) {
          if (r && r.success) api.stickerUpload(r.data.file_path, emo.value).then(function () { showStickers(); });
        });
      }, 'image/png');
    };
    wrap.appendChild(file); wrap.appendChild(canvas); wrap.appendChild(zoom); wrap.appendChild(emo); wrap.appendChild(save);
    draw();
    modal('Create sticker', wrap);
  }
  function formatToolbar(inputId) {
    const input = document.getElementById(inputId || 'messageInput');
    if (!input || input._spToolbar) return;
    input._spToolbar = true;
    const bar = el('div', 'k-sp-tools');
    const btns = [['B', '<b>', '</b>'], ['I', '<i>', '</i>'], ['U', '<u>', '</u>'], ['S', '<s>', '</s>'], ['<>', '<code>', '</code>'], ['···', '<spoiler>', '</spoiler>'], ['"', '<quote>', '</quote>'], ['≡', '<monoall>', '</monoall>']];
    btns.forEach(function (b) {
      const btn = el('button', 'k-sp-tool', b[0]);
      btn.type = 'button';
      btn.onmousedown = function (e) { e.preventDefault(); wrapSelection(input, b[1], b[2]); };
      bar.appendChild(btn);
    });
    bar.style.display = 'none';
    document.body.appendChild(bar);
    function place() {
      try {
        if (typeof input.selectionStart !== 'number' || input.selectionStart === input.selectionEnd) { bar.style.display = 'none'; return; }
        const r = input.getBoundingClientRect();
        bar.style.display = 'flex';
        bar.style.left = Math.max(8, r.left + window.scrollX) + 'px';
        bar.style.top = (r.top + window.scrollY - bar.offsetHeight - 8) + 'px';
      } catch (e) { bar.style.display = 'none'; }
    }
    input.addEventListener('select', place);
    input.addEventListener('keyup', place);
    input.addEventListener('blur', function () { setTimeout(function () { bar.style.display = 'none'; }, 200); });
  }

  window.K = window.K || {};
  window.K.extras = Object.assign({ renderExtra, wrapSelection }, api, {
    showEdits, showTrash, showDiscover, showStickers, stickerEditor, formatToolbar,
  });
})();
