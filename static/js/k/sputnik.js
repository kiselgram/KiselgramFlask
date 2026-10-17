'use strict';
/* K.sputnik — Sputnik ideas pack (ported from ilyyagoncharow12/sputnik).
 * Backend: /api.v2/api/sputnik/* (see app/routes/spav2/sputnik.py).
 * Lean helpers: Sputnik-style formatting extras, link preview, trash,
 * folders, stickers, albums, video-circle badge, edit history.
 */
(function () {
  const V2 = (window.V2 || '/api.v2/api');
  const B = V2 + '/sputnik';

  async function req(path, opts) {
    opts = opts || {};
    const res = await fetch(B + path, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts));
    return res.json().catch(() => ({ success: false }));
  }

  // Sputnik-style extras on top of K.markdown: <spoiler>, <quote>, <monoall> + bare links.
  function renderExtra(text) {
    let html = (window.K && K.markdown) ? K.markdown.render(text || '') : String(text || '');
    html = html
      .replace(/<spoiler>([\s\S]*?)<\/spoiler>/g, '<span class="k-spoiler">$1</span>')
      .replace(/<quote>([\s\S]*?)<\/quote>/g, '<blockquote>$1</blockquote>')
      .replace(/<monoall>([\s\S]*?)<\/monoall>/g, '<pre class="k-copy-code">$1</pre>');
    // bare links -> clickable (skip already-linked)
    html = html.replace(/(^|[\s(])((https?:\/\/[^\s<]+))/g, function (m, pre, url) {
      if (m.indexOf('<a') !== -1) return m;
      return pre + '<a href="' + url + '" target="_blank" rel="noopener">' + url + '</a>';
    });
    return html;
  }

  // Wrap a selection with Sputnik tags (toolbar helper for composer).
  function wrapSelection(input, before, after) {
    if (!input || typeof input.selectionStart !== 'number') return;
    const s = input.selectionStart, e = input.selectionEnd, v = input.value;
    const sel = v.slice(s, e) || 'text';
    input.value = v.slice(0, s) + before + sel + after + v.slice(e);
    input.focus();
  }

  const api = {
    // edits / trash
    editWithHistory: (id, content) => req('/messages/' + id + '/edit', { method: 'POST', body: JSON.stringify({ content }) }),
    edits: (id) => req('/messages/' + id + '/edits'),
    trashList: () => req('/trash'),
    trashMove: (id) => req('/messages/' + id + '/trash', { method: 'POST' }),
    trashRestore: (id) => req('/trash/restore', { method: 'POST', body: JSON.stringify({ message_id: id }) }),
    trashClear: () => req('/trash/clear', { method: 'POST' }),
    // preview / views
    preview: (url) => req('/link_preview?url=' + encodeURIComponent(url)),
    view: (id) => req('/messages/' + id + '/view', { method: 'POST' }),
    // albums / circles / stickers
    albumCreate: (ids) => req('/albums/create', { method: 'POST', body: JSON.stringify({ message_ids: ids }) }),
    albumGet: (aid) => req('/albums/' + encodeURIComponent(aid)),
    albumReorder: (aid, ids) => req('/albums/' + encodeURIComponent(aid) + '/reorder', { method: 'POST', body: JSON.stringify({ message_ids: ids }) }),
    roundSend: (chat_id, file_path, duration, caption) => req('/round/send', { method: 'POST', body: JSON.stringify({ chat_id, file_path, duration, caption }) }),
    stickers: (fav) => req('/stickers' + (fav ? '?favorite=1' : '')),
    stickerUpload: (file_path, emoji) => req('/stickers/upload', { method: 'POST', body: JSON.stringify({ file_path, emoji }) }),
    stickerFav: (id, favorite) => req('/stickers/' + id + '/favorite', { method: 'POST', body: JSON.stringify({ favorite }) }),
    stickerFromMessage: (message_id, emoji) => req('/stickers/from_message', { method: 'POST', body: JSON.stringify({ message_id, emoji }) }),
    stickerSend: (sticker_id, chat_id) => req('/stickers/send', { method: 'POST', body: JSON.stringify({ sticker_id, chat_id }) }),
    // folders / secrets / accounts / misc
    folders: () => req('/folders'),
    folderCreate: (name) => req('/folders/create', { method: 'POST', body: JSON.stringify({ name }) }),
    folderSetChats: (id, chats) => req('/folders/' + id + '/chats', { method: 'POST', body: JSON.stringify({ chats }) }),
    cloudSetup: (password, hint, email) => req('/cloud/setup', { method: 'POST', body: JSON.stringify({ password, hint, email }) }),
    cloudVerify: (password) => req('/cloud/verify', { method: 'POST', body: JSON.stringify({ password }) }),
    applockSet: (pin, hint) => req('/applock/set', { method: 'POST', body: JSON.stringify({ pin, hint }) }),
    applockVerify: (pin) => req('/applock/verify', { method: 'POST', body: JSON.stringify({ pin }) }),
    contactsImport: (payload) => req('/contacts/import', { method: 'POST', body: JSON.stringify(payload || {}) }),
    // NOTE: multi-account lives client-side in K.auth.accounts (localStorage);
    // no server-side linking table (SputnikLinkedAccount removed as duplicate).
    scheduled: () => req('/scheduled'),
    scheduledSendNow: (id) => req('/scheduled/' + id + '/send_now', { method: 'POST' }),
    scheduledDelete: (id) => req('/scheduled/' + id, { method: 'DELETE' }),
    // wave 2
    pollClose: (id) => req('/polls/' + id + '/close', { method: 'POST' }),
    pollResults: (id) => req('/polls/' + id + '/results'),
    drafts: () => req('/drafts'),
    draftSave: (chat_type, chat_id, text) => req('/drafts/save', { method: 'POST', body: JSON.stringify({ chat_type, chat_id, text }) }),
    bannerGet: (user_id) => req('/profile/banner' + (user_id ? '?user_id=' + user_id : '')),
    bannerSet: (banner_color, banner_image) => req('/profile/banner', { method: 'POST', body: JSON.stringify({ banner_color, banner_image }) }),
    profileMedia: (user_id, filter) => req('/users/' + user_id + '/media' + (filter ? '?filter=' + filter : '')),
    discover: (kind) => req('/discover' + (kind ? '?kind=' + kind : '')),
    joinRequest: (chat_id) => req('/groups/' + chat_id + '/request', { method: 'POST' }),
    joinRequests: (chat_id) => req('/groups/' + chat_id + '/requests'),
    joinApprove: (chat_id, user_id) => req('/groups/' + chat_id + '/approve', { method: 'POST', body: JSON.stringify({ user_id }) }),
    joinReject: (chat_id, user_id) => req('/groups/' + chat_id + '/reject', { method: 'POST', body: JSON.stringify({ user_id }) }),
    memberPerms: (chat_id, user_id) => req('/groups/' + chat_id + '/members/' + user_id + '/perms'),
    memberPermsSet: (chat_id, user_id, perms) => req('/groups/' + chat_id + '/members/' + user_id + '/perms', { method: 'POST', body: JSON.stringify({ perms }) }),
    restrict: (chat_id, kind, user_id, extra) => req('/groups/' + chat_id + '/restrict', { method: 'POST', body: JSON.stringify(Object.assign({ kind, user_id }, extra || {})) }),
    unrestrict: (chat_id, kind, user_id) => req('/groups/' + chat_id + '/unrestrict', { method: 'POST', body: JSON.stringify({ kind, user_id }) }),
    restricted: (chat_id) => req('/groups/' + chat_id + '/restricted'),
    storyShare: (story_id) => req('/stories/' + story_id + '/share', { method: 'POST' }),
    storyReplace: (story_id, patch) => req('/stories/' + story_id + '/replace', { method: 'POST', body: JSON.stringify(patch || {}) }),
    exportData: () => req('/export', { method: 'POST' }),
    // wave 3
    uploadImage: (formData) => fetch(B + '/upload', { method: 'POST', body: formData }).then((r) => r.json().catch(() => ({ success: false }))),
    joinDirect: (chat_id) => req('/groups/' + chat_id + '/join', { method: 'POST' }),
    cloudRecover: (email, new_password) => req('/cloud/recover', { method: 'POST', body: JSON.stringify({ email, new_password }) }),
    channelSub: (chat_id) => fetch(V2 + '/channels/' + chat_id + '/subscribe', { method: 'POST', headers: { 'Content-Type': 'application/json' } }).then((r) => r.json().catch(() => ({ success: false }))),
    albumLookup: (ids) => req('/albums/lookup', { method: 'POST', body: JSON.stringify({ message_ids: ids }) }),
    stickerSendToActive: function (sticker_id) {
      const ac = (window.K && K.state && K.state.activeChat) || {};
      if (!ac.type || ac.id == null) return Promise.resolve({ success: false });
      const body = ac.type === 'personal'
        ? { sticker_id, chat_type: 'personal', peer_id: ac.id }
        : { sticker_id, chat_id: ac.id };
      return req('/stickers/send', { method: 'POST', body: JSON.stringify(body) });
    },
  };

  window.K = window.K || {};
  K.sputnik = Object.assign({ renderExtra, wrapSelection }, api);

  /* ---- Sputnik UI pack: folders bar, modals, applock, gestures, drafts ---- */

  function el(tag, cls, html) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }

  // Folders bar (Sputnik folders.js idea): renders chips, filters chat list.
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

  // Generic modal shell (text set via textContent — XSS-safe).
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

  function showScheduled() {
    return api.scheduled().then(function (r) {
      const list = el('div', 'k-sp-list');
      const items = (r && r.data && r.data.scheduled) || [];
      if (!items.length) list.appendChild(el('div', 'k-sp-empty', 'No scheduled messages'));
      items.forEach(function (m) {
        const row = el('div', 'k-sp-row');
        const tx = el('span', 'k-sp-text', '');
        tx.textContent = (m.send_at || '') + ' — ' + (m.content || '');
        const now = el('button', 'k-sp-btn', 'Send now');
        now.onclick = function () { api.scheduledSendNow(m.message_id).then(function () { row.remove(); }); };
        const del = el('button', 'k-sp-btn danger', 'Delete');
        del.onclick = function () { api.scheduledDelete(m.message_id).then(function () { row.remove(); }); };
        row.appendChild(tx);
        row.appendChild(now);
        row.appendChild(del);
        list.appendChild(row);
      });
      modal('Scheduled messages', list);
    });
  }

  // App-lock overlay (Sputnik PIN idea): blocks UI until PIN verified.
  function lockScreen() {
    if (document.getElementById('k-sp-lock')) return;
    const ov = el('div', 'k-sp-lock');
    ov.id = 'k-sp-lock';
    const box = el('div', 'k-sp-lock-box');
    box.appendChild(el('div', 'k-sp-lock-title', 'App locked'));
    const inp = el('input', 'k-sp-lock-inp');
    inp.type = 'password';
    inp.inputMode = 'numeric';
    inp.placeholder = 'PIN';
    inp.maxLength = 12;
    const btn = el('button', 'k-sp-btn', 'Unlock');
    btn.onclick = function () {
      api.applockVerify(inp.value).then(function (r) {
        if (r && r.success) ov.remove();
        else inp.value = '';
      });
    };
    inp.onkeydown = function (e) { if (e.key === 'Enter') btn.click(); };
    box.appendChild(inp);
    box.appendChild(btn);
    ov.appendChild(box);
    document.body.appendChild(ov);
    setTimeout(function () { inp.focus(); }, 50);
  }

  // Mobile gestures (Sputnik gestures.js idea): swipe-left = reply, long-press = menu.
  function bindMessageGestures(container, opts) {
    if (!container || container._spBound) return;
    container._spBound = true;
    opts = opts || {};
    let sx = 0, cur = null, timer = 0;
    container.addEventListener('touchstart', function (e) {
      const row = e.target.closest ? e.target.closest('[data-msg-id]') : null;
      cur = row;
      sx = e.touches[0].clientX;
      clearTimeout(timer);
      if (row) timer = setTimeout(function () {
        if (opts.onMenu) opts.onMenu(row.getAttribute('data-msg-id'), row);
      }, 500);
    }, { passive: true });
    container.addEventListener('touchmove', function (e) {
      if (!cur) return;
      const dx = e.touches[0].clientX - sx;
      if (Math.abs(dx) > 10) clearTimeout(timer);
      if (dx < -60 && opts.onReply) { // swipe left -> reply
        opts.onReply(cur.getAttribute('data-msg-id'), cur);
        cur = null;
      }
    }, { passive: true });
    container.addEventListener('touchend', function () { clearTimeout(timer); cur = null; });
    container.addEventListener('contextmenu', function (e) { // desktop right-click
      const row = e.target.closest ? e.target.closest('[data-msg-id]') : null;
      if (row && opts.onMenu) { e.preventDefault(); opts.onMenu(row.getAttribute('data-msg-id'), row); }
    });
  }

  // Draft autosave binder (Sputnik drafts idea): saves composer text debounced.
  function bindDraft(input, chatType, chatId) {
    if (!input || !chatId) return;
    let t = 0;
    // restore
    api.draftSave && K.sputnik.drafts().then(function (r) {
      const d = ((r && r.data && r.data.drafts) || []).find(function (x) {
        return String(x.chat_id) === String(chatId) && x.chat_type === chatType;
      });
      if (d && d.text && !input.value) input.value = d.text;
    }).catch(function () {});
    input.addEventListener('input', function () {
      clearTimeout(t);
      t = setTimeout(function () { api.draftSave(chatType, chatId, input.value); }, 800);
    });
  }

  // Banner applier (Sputnik banner idea).
  function applyBanner(userId, mount) {
    if (!mount) return;
    api.bannerGet(userId).then(function (r) {
      const d = (r && r.data) || {};
      mount.style.background = d.banner_image ? ('url(' + d.banner_image + ') center/cover') : (d.banner_color || '#2b8d8d');
    }).catch(function () {});
  }

  Object.assign(K.sputnik, {
    renderFoldersBar, showEdits, showTrash, showScheduled, showModal: modal,
    lockScreen, bindMessageGestures, bindDraft, applyBanner,
  });

  /* ---- wave 3 UI: message decorator, toolbar, nav, discover, stickers, idle-lock ---- */

  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // Wrap chat rendering: video circles, stickers, spoiler/quote/mono tags.
  // Chain-aware: tg.js wraps the same function, so we track applied layers
  // in _spChain — wrapping twice would duplicate players on every autoWire.
  function decorateMessages() {
    if (!window.K || !K.chat || !K.chat._messageHtml) return;
    const fn = K.chat._messageHtml;
    fn._spChain = fn._spChain || [];
    if (fn._spChain.includes('sputnik')) return;
    const orig = fn;
    const wrapped = function (m, isOwn, consecutive) {
      let h = orig.call(this, m, isOwn, consecutive);
      try {
        const url = m && (m.file_url || m.file_path);
        const attRe = /<div class="(?:k-msg-attachment|k-msg-file)">[\s\S]*?<\/div>/;
        if (m && m.file_type === 'round' && url) {
          const player = '<div class="k-sp-round"><video src="' + esc(url) + '" playsinline preload="metadata" onclick="this.paused?this.play():this.pause()"></video><span class="k-sp-round-badge">circle</span></div>';
          h = attRe.test(h) ? h.replace(attRe, player) : h.replace(/(data-msg-id="[^"]+">)/, '$1' + player);
          h = h.replace('class="k-msg ', 'class="k-msg k-sp-has-round ');
        } else if (m && m.file_type === 'sticker' && url) {
          h = h.replace(/<div class="k-msg-file">[\s\S]*?<\/div>/, '<div class="k-sp-sticker"><img src="' + esc(url) + '" alt="sticker"></div>');
        }
        if (m && m.edited_at) {
          const mid = m.message_id || m.id;
          h = h.replace('<div class="k-msg-actions">', '<span class="k-sp-edited" data-ed="' + mid + '" title="Edit history">edited</span><div class="k-msg-actions">');
        }
        // Sputnik tags may arrive HTML-escaped from markdown: unwrap them.
        h = h.replace(/&lt;spoiler&gt;([\s\S]*?)&lt;\/spoiler&gt;/g, '<span class="k-spoiler">$1</span>')
          .replace(/<spoiler>([\s\S]*?)<\/spoiler>/g, '<span class="k-spoiler">$1</span>')
          .replace(/&lt;quote&gt;([\s\S]*?)&lt;\/quote&gt;/g, '<blockquote>$1</blockquote>')
          .replace(/&lt;monoall&gt;([\s\S]*?)&lt;\/monoall&gt;/g, '<pre class="k-copy-code">$1</pre>');
      } catch (e) { /* never break chat rendering */ }
      return h;
    };
    wrapped._spChain = [...fn._spChain, 'sputnik'];
    wrapped._spWrapped = true;
    K.chat._messageHtml = wrapped;
    if (window._spClickBound) return;
    window._spClickBound = true;
    // spoiler tap-to-reveal + edit-history marker (delegated, works for all messages)
    document.addEventListener('click', function (e) {
      const sp = e.target.closest ? e.target.closest('.k-spoiler') : null;
      if (sp) { sp.classList.toggle('open'); return; }
      const ed = e.target.closest ? e.target.closest('.k-sp-edited') : null;
      if (ed && ed.getAttribute('data-ed')) showEdits(ed.getAttribute('data-ed'));
    });
  }

  // Floating formatting toolbar on text selection in the composer.
  function formatToolbar(inputId) {
    const input = document.getElementById(inputId || 'messageInput');
    if (!input || input._spToolbar) return;
    input._spToolbar = true;
    const bar = el('div', 'k-sp-tools');
    const btns = [
      ['B', '<b>', '</b>'], ['I', '<i>', '</i>'], ['U', '<u>', '</u>'],
      ['S', '<s>', '</s>'], ['<>', '<code>', '</code>'], ['···', '<spoiler>', '</spoiler>'],
      ['”', '<quote>', '</quote>'], ['≡', '<monoall>', '</monoall>'],
    ];
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

  // Self-mounting nav section (Sputnik menu ideas): trash, scheduled, discover, stickers, export.
  function mountNav() {
    const nav = document.querySelector('.k-nav');
    if (!nav || document.getElementById('k-sp-nav')) return;
    const sec = el('div', '');
    sec.id = 'k-sp-nav';
    const items = [
      ['fa-trash', 'Trash', function () { showTrash(); }],
      ['fa-clock', 'Scheduled', function () { showScheduled(); }],
      ['fa-compass', 'Discover', function () { showDiscover(); }],
      ['fa-sticky-note', 'Stickers', function () { showStickers(); }],
      ['fa-download', 'My data', function () {
        api.exportData().then(function (r) {
          if (!r || !r.success) return;
          const blob = new Blob([JSON.stringify(r.data, null, 2)], { type: 'application/json' });
          const a = document.createElement('a');
          a.href = URL.createObjectURL(blob);
          a.download = 'kiselgram-export.json';
          a.click();
        });
      }],
    ];
    items.forEach(function (it) {
      const a = el('a', 'k-nav-item');
      a.innerHTML = '<i class="fas ' + it[0] + '"></i><span>' + it[1] + '</span>';
      a.onclick = it[2];
      sec.appendChild(a);
    });
    nav.appendChild(sec);
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

  // Sticker editor (Sputnik idea): upload -> zoom/crop on canvas -> emoji overlay -> save.
  function stickerEditor() {
    const wrap = el('div', 'k-sp-editor');
    const file = document.createElement('input');
    file.type = 'file';
    file.accept = 'image/*';
    const canvas = document.createElement('canvas');
    canvas.width = 256; canvas.height = 256;
    canvas.className = 'k-sp-canvas';
    const zoom = document.createElement('input');
    zoom.type = 'range'; zoom.min = '50'; zoom.max = '300'; zoom.value = '100';
    const emo = document.createElement('input');
    emo.placeholder = 'Emoji (optional)';
    emo.maxLength = 8;
    emo.className = 'k-sp-inp';
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
    // touch drag
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
    wrap.appendChild(file);
    wrap.appendChild(canvas);
    wrap.appendChild(zoom);
    wrap.appendChild(emo);
    wrap.appendChild(save);
    draw();
    modal('Create sticker', wrap);
  }

  // Idle auto-lock (Sputnik applock idea): lock screen after N idle minutes.
  let _idleTimer = 0;
  function idleLock(minutes) {
    if (!minutes || minutes <= 0) { clearTimeout(_idleTimer); return; }
    function arm() {
      clearTimeout(_idleTimer);
      _idleTimer = setTimeout(function () { lockScreen(); }, minutes * 60 * 1000);
    }
    ['click', 'keydown', 'touchstart', 'mousemove'].forEach(function (ev) {
      document.addEventListener(ev, arm, { passive: true });
    });
    arm();
  }

  Object.assign(K.sputnik, {
    decorateMessages, formatToolbar, mountNav, showDiscover, showStickers,
    stickerEditor, idleLock, mountComposer, groupAlbums, mountStoryShare, autoWire,
  });

  /* ---- wave 4 UI: albums grid, composer buttons, auto-wire, story share ---- */

  // Group album members into one gallery grid (Sputnik albums idea).
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

  // Composer buttons: scheduled list + sticker picker (self-mounting).
  function mountComposer() {
    const input = document.getElementById('messageInput');
    if (!input || document.getElementById('k-sp-clock')) return;
    const bar = input.parentElement;
    if (!bar) return;
    const clock = el('button', 'k-icon-btn', '<i class="fas fa-clock"></i>');
    clock.id = 'k-sp-clock';
    clock.title = 'Scheduled';
    clock.onclick = function () { showScheduled(); };
    const st = el('button', 'k-icon-btn', '<i class="fas fa-sticky-note"></i>');
    st.id = 'k-sp-sticker-btn';
    st.title = 'Stickers';
    st.onclick = function () { showStickers({ sendMode: true }); };
    bar.insertBefore(st, bar.firstChild);
    bar.insertBefore(clock, bar.firstChild);
  }

  // Story share button in the viewer actions (self-mounting).
  function mountStoryShare() {
    const like = document.getElementById('storyLikeCount');
    const host = like && like.closest ? like.closest('div') : null;
    if (!host || document.getElementById('k-sp-share')) return;
    const btn = el('button', 'k-story-btn', '<i class="fas fa-share"></i>');
    btn.id = 'k-sp-share';
    btn.title = 'Share to self';
    btn.onclick = function () {
      const s = window.K && K.stories && K.stories._activeStory;
      if (!s) return;
      api.storyShare(s.story_id || s.id).then(function (r) {
        if (window.K && K.ui && K.ui.toast) K.ui.toast(r && r.success ? 'Reposted to my stories' : 'Failed', r && r.success ? 'success' : 'error');
      });
    };
    host.appendChild(btn);
  }

  // Mini message menu for long-press (mobile) — reply / edits / copy.
  function messageMenu(msgId) {
    const body = el('div', 'k-sp-list');
    [['Reply', function () { const t = document.querySelector('[data-msg-id="' + msgId + '"] .k-msg-text'); if (window.K && K.chat && K.chat.reply) K.chat.reply.set(+msgId, (t ? t.textContent : '').substring(0, 40)); }],
     ['Edit history', function () { showEdits(msgId); }],
     ['Copy', function () { if (window.K && K.chat && K.chat.copy) K.chat.copy(+msgId); }]
    ].forEach(function (it) {
      const b = el('button', 'k-sp-btn', it[0]);
      b.onclick = function () { const m = document.querySelector('.k-sp-modal'); if (m) m.remove(); it[1](); };
      body.appendChild(b);
    });
    modal('Message', body);
  }

  // Auto-wire everything as the SPA changes: gestures, drafts, toolbar, composer, albums.
  let _wiredChatKey = '';
  let _idleArmedFor = '';
  let _msgObserverOn = null;
  function autoWire() {
    mountNav();
    decorateMessages();
    mountComposer();
    mountStoryShare();
    formatToolbar();
    const mc = document.getElementById('messagesContainer');
    if (mc) {
      bindMessageGestures(mc, { onReply: function (id) { if (window.K && K.chat && K.chat.reply) { const t = document.querySelector('[data-msg-id="' + id + '"] .k-msg-text'); K.chat.reply.set(+id, (t ? t.textContent : '').substring(0, 40)); } }, onMenu: messageMenu });
      if (_msgObserverOn !== mc) { // album regroup only when message list mutates (debounced)
        _msgObserverOn = mc;
        let gt = 0;
        new MutationObserver(function () { clearTimeout(gt); gt = setTimeout(groupAlbums, 400); }).observe(mc, { childList: true });
        groupAlbums();
      }
    }
    const idleMin = localStorage.getItem('k_sp_idle') || '0';
    if (idleMin !== _idleArmedFor) { _idleArmedFor = idleMin; idleLock(parseInt(idleMin, 10) || 0); }
    // per-chat draft restore on chat switch (saves previous first)
    const ac = (window.K && K.state && K.state.activeChat) || {};
    const key = (ac.type || '') + ':' + (ac.id == null ? '' : ac.id);
    const input = document.getElementById('messageInput');
    if (input && key && key !== _wiredChatKey) {
      const prev = _wiredChatKey.split(':');
      if (_wiredChatKey && prev.length === 2 && input.value !== undefined && K.sputnik._draftText !== undefined && K.sputnik._draftText !== null) {
        api.draftSave(prev[0], prev[1], K.sputnik._draftText || '');
      }
      _wiredChatKey = key;
      if (!input._spDraftTrack) {
        input._spDraftTrack = true;
        input.addEventListener('input', function () { K.sputnik._draftText = input.value; });
      }
      K.sputnik.drafts().then(function (rr) {
        const d = ((rr && rr.data && rr.data.drafts) || []).find(function (x) {
          return String(x.chat_id) === String(ac.id) && x.chat_type === ac.type;
        });
        if (d && d.text && !input.value) { input.value = d.text; K.sputnik._draftText = d.text; }
      }).catch(function () {});
    }
    if (input && !input._spDraftSaver) {
      input._spDraftSaver = true;
      let t = 0;
      input.addEventListener('input', function () {
        clearTimeout(t);
        t = setTimeout(function () {
          const a2 = (window.K && K.state && K.state.activeChat) || {};
          if (a2.type && a2.id != null) api.draftSave(a2.type, a2.id, input.value);
        }, 1500);
      });
    }
  }

  // Auto-init on SPA load + observe SPA view changes.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { autoWire(); observe(); });
  } else {
    autoWire(); observe();
  }
  function observe() {
    if (window._spObserver) return;
    const ob = new MutationObserver(function () { autoWire(); });
    ob.observe(document.body, { childList: true, subtree: true });
    window._spObserver = ob;
  }
})();
