'use strict';
/* K.misc — Sputnik-style misc (applock, banner, drafts, gestures, auto-wire, etc.). */
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
    box.appendChild(h); box.appendChild(x); box.appendChild(bodyEl);
    ov.appendChild(box);
    ov.onclick = function (e) { if (e.target === ov) ov.remove(); };
    document.body.appendChild(ov);
    return ov;
  }

  const api = {
    cloudSetup: (password, hint, email) => req('/cloud/setup', { method: 'POST', body: JSON.stringify({ password, hint, email }) }),
    cloudVerify: (password) => req('/cloud/verify', { method: 'POST', body: JSON.stringify({ password }) }),
    applockSet: (pin, hint) => req('/applock/set', { method: 'POST', body: JSON.stringify({ pin, hint }) }),
    applockVerify: (pin) => req('/applock/verify', { method: 'POST', body: JSON.stringify({ pin }) }),
    contactsImport: (payload) => req('/contacts/import', { method: 'POST', body: JSON.stringify(payload || {}) }),
    scheduled: () => req('/scheduled'),
    scheduledSendNow: (id) => req('/scheduled/' + id + '/send_now', { method: 'POST' }),
    scheduledDelete: (id) => req('/scheduled/' + id, { method: 'DELETE' }),
    drafts: () => req('/drafts'),
    draftSave: (chat_type, chat_id, text) => req('/drafts/save', { method: 'POST', body: JSON.stringify({ chat_type, chat_id, text }) }),
    bannerGet: (user_id) => req('/profile/banner' + (user_id ? '?user_id=' + user_id : '')),
    bannerSet: (banner_color, banner_image) => req('/profile/banner', { method: 'POST', body: JSON.stringify({ banner_color, banner_image }) }),
    profileMedia: (user_id, filter) => req('/users/' + user_id + '/media' + (filter ? '?filter=' + filter : '')),
    cloudRecover: (email, new_password) => req('/cloud/recover', { method: 'POST', body: JSON.stringify({ email, new_password }) }),
    secretsOff: () => req('/secrets/off', { method: 'POST' }),
  };

  // App-lock overlay.
  function lockScreen() {
    if (document.getElementById('k-sp-lock')) return;
    const ov = el('div', 'k-sp-lock');
    ov.id = 'k-sp-lock';
    const box = el('div', 'k-sp-lock-box');
    box.appendChild(el('div', 'k-sp-lock-title', 'App locked'));
    const inp = el('input', 'k-sp-lock-inp');
    inp.type = 'password'; inp.inputMode = 'numeric'; inp.placeholder = 'PIN'; inp.maxLength = 12;
    const btn = el('button', 'k-sp-btn', 'Unlock');
    btn.onclick = function () {
      api.applockVerify(inp.value).then(function (r) {
        if (r && r.success) ov.remove();
        else inp.value = '';
      });
    };
    inp.onkeydown = function (e) { if (e.key === 'Enter') btn.click(); };
    box.appendChild(inp); box.appendChild(btn);
    ov.appendChild(box);
    document.body.appendChild(ov);
    setTimeout(function () { inp.focus(); }, 50);
  }
  let _idleTimer = 0;
  function idleLock(minutes) {
    if (!minutes || minutes <= 0) { clearTimeout(_idleTimer); return; }
    function arm() { clearTimeout(_idleTimer); _idleTimer = setTimeout(function () { lockScreen(); }, minutes * 60 * 1000); }
    ['click', 'keydown', 'touchstart', 'mousemove'].forEach(function (ev) { document.addEventListener(ev, arm, { passive: true }); });
    arm();
  }

  // Mobile gestures.
  function bindMessageGestures(container, opts) {
    if (!container || container._spBound) return;
    container._spBound = true;
    opts = opts || {};
    let sx = 0, cur = null, timer = 0;
    container.addEventListener('touchstart', function (e) {
      const row = e.target.closest ? e.target.closest('[data-msg-id]') : null;
      cur = row; sx = e.touches[0].clientX; clearTimeout(timer);
      if (row) timer = setTimeout(function () { if (opts.onMenu) opts.onMenu(row.getAttribute('data-msg-id'), row); }, 500);
    }, { passive: true });
    container.addEventListener('touchmove', function (e) {
      if (!cur) return;
      const dx = e.touches[0].clientX - sx;
      if (Math.abs(dx) > 10) clearTimeout(timer);
      if (dx < -60 && opts.onReply) { opts.onReply(cur.getAttribute('data-msg-id'), cur); cur = null; }
    }, { passive: true });
    container.addEventListener('touchend', function () { clearTimeout(timer); cur = null; });
    container.addEventListener('contextmenu', function (e) {
      const row = e.target.closest ? e.target.closest('[data-msg-id]') : null;
      if (row && opts.onMenu) { e.preventDefault(); opts.onMenu(row.getAttribute('data-msg-id'), row); }
    });
  }

  // Draft autosave.
  function bindDraft(input, chatType, chatId) {
    if (!input || !chatId) return;
    let t = 0;
    api.drafts().then(function (r) {
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

  // Banner applier.
  function applyBanner(userId, mount) {
    if (!mount) return;
    api.bannerGet(userId).then(function (r) {
      const d = (r && r.data) || {};
      mount.style.background = d.banner_image ? ('url(' + d.banner_image + ') center/cover') : (d.banner_color || '#2b8d8d');
    }).catch(function () {});
  }

  // Show scheduled messages modal.
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
        row.appendChild(tx); row.appendChild(now); row.appendChild(del);
        list.appendChild(row);
      });
      modal('Scheduled messages', list);
    });
  }

  // Decorate chat messages: video circles, stickers, spoiler/quote/mono tags.
  // Chain-aware: tg.js wraps the same function, so we track applied layers
  // in _spChain — wrapping twice would duplicate players on every autoWire.
  function decorateMessages() {
    if (!window.K || !K.chat || !K.chat._messageHtml) return;
    const fn = K.chat._messageHtml;
    fn._spChain = fn._spChain || [];
    if (fn._spChain.includes('misc')) return;
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
        h = h.replace(/&lt;spoiler&gt;([\s\S]*?)&lt;\/spoiler&gt;/g, '<span class="k-spoiler">$1</span>')
          .replace(/<spoiler>([\s\S]*?)<\/spoiler>/g, '<span class="k-spoiler">$1</span>')
          .replace(/&lt;quote&gt;([\s\S]*?)&lt;\/quote&gt;/g, '<blockquote>$1</blockquote>')
          .replace(/&lt;monoall&gt;([\s\S]*?)&lt;\/monoall&gt;/g, '<pre class="k-copy-code">$1</pre>');
      } catch (e) { /* never break chat rendering */ }
      return h;
    };
    wrapped._spChain = [...fn._spChain, 'misc'];
    wrapped._spWrapped = true;
    K.chat._messageHtml = wrapped;
    if (window._spClickBound) return;
    window._spClickBound = true;
    document.addEventListener('click', function (e) {
      const sp = e.target.closest ? e.target.closest('.k-spoiler') : null;
      if (sp) { sp.classList.toggle('open'); return; }
      const ed = e.target.closest ? e.target.closest('.k-sp-edited') : null;
      if (ed && ed.getAttribute('data-ed')) {
        const extras = window.K && window.K.extras;
        if (extras && extras.showEdits) extras.showEdits(ed.getAttribute('data-ed'));
      }
    });
  }

  // Floating formatting toolbar on text selection in the composer.
  function formatToolbar(inputId) {
    const input = document.getElementById(inputId || 'messageInput');
    if (!input || input._spToolbar) return;
    input._spToolbar = true;
    const bar = el('div', 'k-sp-tools');
    const btns = [['B', '<b>', '</b>'], ['I', '<i>', '</i>'], ['U', '<u>', '</u>'], ['S', '<s>', '</s>'], ['<>', '<code>', '</code>'], ['···', '<spoiler>', '</spoiler>'], ['"', '<quote>', '</quote>'], ['≡', '<monoall>', '</monoall>']];
    btns.forEach(function (b) {
      const btn = el('button', 'k-sp-tool', b[0]);
      btn.type = 'button';
      btn.onmousedown = function (e) { e.preventDefault(); (window.K.extras && K.extras.wrapSelection) ? K.extras.wrapSelection(input, b[1], b[2]) : null; };
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

  // Self-mounting nav section.
  function mountNav() {
    const nav = document.querySelector('.k-nav');
    if (!nav || document.getElementById('k-sp-nav')) return;
    const sec = el('div', '');
    sec.id = 'k-sp-nav';
    const items = [
      ['fa-trash', 'Trash', function () { if (window.K && K.extras) K.extras.showTrash(); }],
      ['fa-clock', 'Scheduled', function () { showScheduled(); }],
      ['fa-compass', 'Discover', function () { if (window.K && K.extras) K.extras.showDiscover(); }],
      ['fa-sticky-note', 'Stickers', function () { if (window.K && K.extras) K.extras.showStickers(); }],
      ['fa-download', 'My data', function () {
        if (window.K && K.extras && K.extras.exportData) {
          K.extras.exportData().then(function (r) {
            if (!r || !r.success) return;
            const blob = new Blob([JSON.stringify(r.data, null, 2)], { type: 'application/json' });
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = 'kiselgram-export.json';
            a.click();
          });
        }
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
    st.onclick = function () { if (window.K && K.extras) K.extras.showStickers({ sendMode: true }); };
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
      if (window.K && K.channelExtras) K.channelExtras.storyShare(s.story_id || s.id).then(function (r) {
        if (window.K && K.ui && K.ui.toast) K.ui.toast(r && r.success ? 'Reposted to my stories' : 'Failed', r && r.success ? 'success' : 'error');
      });
    };
    host.appendChild(btn);
  }

  // Mini message menu for long-press (mobile) — reply / edits / copy.
  function messageMenu(msgId) {
    const body = el('div', 'k-sp-list');
    [['Reply', function () { const t = document.querySelector('[data-msg-id="' + msgId + '"] .k-msg-text'); if (window.K && K.chat && K.chat.reply) K.chat.reply.set(+msgId, (t ? t.textContent : '').substring(0, 40)); }],
     ['Edit history', function () { if (window.K && K.extras) K.extras.showEdits(msgId); }],
     ['Copy', function () { if (window.K && K.chat && K.chat.copy) K.chat.copy(+msgId); }]
    ].forEach(function (it) {
      const b = el('button', 'k-sp-btn', it[0]);
      b.onclick = function () { const m = document.querySelector('.k-sp-modal'); if (m) m.remove(); it[1](); };
      body.appendChild(b);
    });
    modal('Message', body);
  }

  // Auto-wire everything as the SPA changes.
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
      if (_msgObserverOn !== mc) {
        _msgObserverOn = mc;
        let gt = 0;
        new MutationObserver(function () { clearTimeout(gt); gt = setTimeout(function () { if (window.K && K.groupExtras) K.groupExtras.groupAlbums(); }, 400); }).observe(mc, { childList: true });
        if (window.K && K.groupExtras) K.groupExtras.groupAlbums();
      }
    }
    const idleMin = localStorage.getItem('k_sp_idle') || '0';
    if (idleMin !== _idleArmedFor) { _idleArmedFor = idleMin; idleLock(parseInt(idleMin, 10) || 0); }
    const ac = (window.K && K.state && K.state.activeChat) || {};
    const key = (ac.type || '') + ':' + (ac.id == null ? '' : ac.id);
    const input = document.getElementById('messageInput');
    if (input && key && key !== _wiredChatKey) {
      const prev = _wiredChatKey.split(':');
      if (_wiredChatKey && prev.length === 2 && input.value !== undefined && K.misc._draftText !== undefined && K.misc._draftText !== null) {
        api.draftSave(prev[0], prev[1], K.misc._draftText || '');
      }
      _wiredChatKey = key;
      if (!input._spDraftTrack) {
        input._spDraftTrack = true;
        input.addEventListener('input', function () { K.misc._draftText = input.value; });
      }
      api.drafts().then(function (rr) {
        const d = ((rr && rr.data && rr.data.drafts) || []).find(function (x) {
          return String(x.chat_id) === String(ac.id) && x.chat_type === ac.type;
        });
        if (d && d.text && !input.value) { input.value = d.text; K.misc._draftText = d.text; }
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

  window.K = window.K || {};
  window.K.misc = Object.assign({ esc, el, modal, lockScreen, idleLock, bindMessageGestures, bindDraft, applyBanner, showScheduled, decorateMessages, formatToolbar, messageMenu, mountNav, mountComposer, mountStoryShare, autoWire, observe }, api, { _draftText: null });
})();
