'use strict';
/* K.tg — Telegram parity pack frontend (topics, dice, geo, voice, etc.).
 * Backend: /api.v2/api/tg/* (see app/routes/spav2/telegram.py).
 * Self-mounting helpers; safe to load after chat.js/sputnik.js.
 */
(function () {
  const V2 = (window.V2 || '/api.v2/api');
  const B = V2 + '/tg';

  async function req(path, opts) {
    opts = opts || {};
    const res = await fetch(B + path, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts));
    return res.json().catch(() => ({ success: false }));
  }

  const api = {
    // topics
    topics: (chat_id) => req('/groups/' + chat_id + '/topics'),
    topicCreate: (chat_id, title, icon) => req('/groups/' + chat_id + '/topics', { method: 'POST', body: JSON.stringify({ title, icon }) }),
    topicUpdate: (tid, patch) => req('/topics/' + tid, { method: 'POST', body: JSON.stringify(patch || {}) }),
    topicDelete: (tid) => req('/topics/' + tid, { method: 'DELETE' }),
    topicSend: (tid, content) => req('/topics/' + tid + '/send', { method: 'POST', body: JSON.stringify({ content }) }),
    topicMessages: (tid, limit) => req('/topics/' + tid + '/messages' + (limit ? '?limit=' + limit : '')),
    // slowmode
    slowGet: (chat_id) => req('/groups/' + chat_id + '/slowmode'),
    slowSet: (chat_id, seconds) => req('/groups/' + chat_id + '/slowmode', { method: 'POST', body: JSON.stringify({ seconds }) }),
    // quiz / dice / geo
    quizSet: (poll_id, answer, explanation) => req('/polls/' + poll_id + '/quiz', { method: 'POST', body: JSON.stringify({ answer, explanation }) }),
    quizAnswer: (poll_id) => req('/polls/' + poll_id + '/answer'),
    dice: (ref) => req('/dice', { method: 'POST', body: JSON.stringify(ref || {}) }),
    geoShare: (ref) => req('/geo/share', { method: 'POST', body: JSON.stringify(ref || {}) }),
    geoUpdate: (mid, lat, lon) => req('/geo/' + mid + '/update', { method: 'POST', body: JSON.stringify({ lat, lon }) }),
    geoStop: (mid) => req('/geo/' + mid + '/stop', { method: 'POST' }),
    geoLive: (chat_id) => req('/geo/live' + (chat_id ? '?chat_id=' + chat_id : '')),
    // stories archive / voice
    storyArchive: () => req('/stories/archive'),
    voiceStart: (chat_id) => req('/voice/start', { method: 'POST', body: JSON.stringify({ chat_id }) }),
    voiceActive: (chat_id) => req('/voice/active' + (chat_id ? '?chat_id=' + chat_id : '')),
    voiceEnd: (room_id) => req('/voice/' + room_id + '/end', { method: 'POST' }),
    // discussion / protect / saved / members / bots
    discLink: (cid, group_id) => req('/channels/' + cid + '/link', { method: 'POST', body: JSON.stringify({ group_id }) }),
    discUnlink: (cid) => req('/channels/' + cid + '/link', { method: 'DELETE' }),
    commentAdd: (channel_message_id, content) => req('/comments', { method: 'POST', body: JSON.stringify({ channel_message_id, content }) }),
    commentList: (mid) => req('/comments/' + mid),
    protect: (chat_id, no_forwards) => req('/chats/' + chat_id + '/protect', { method: 'POST', body: JSON.stringify({ no_forwards }) }),
    savedTag: (message_id, tag) => req('/saved/tag', { method: 'POST', body: JSON.stringify({ message_id, tag }) }),
    savedList: (tag) => req('/saved' + (tag ? '?tag=' + encodeURIComponent(tag) : '')),
    savedTags: () => req('/saved/tags'),
    members: (chat_id) => req('/groups/' + chat_id + '/members'),
    setVisibility: (chat_id, hide_members) => req('/groups/' + chat_id + '/visibility', { method: 'POST', body: JSON.stringify({ hide_members }) }),
    botCmdSet: (command, description) => req('/bots/commands', { method: 'POST', body: JSON.stringify({ command, description }) }),
    botCmdList: (bot_id) => req('/bots/' + bot_id + '/commands'),
    // collectibles
    collectClaim: (username) => req('/collectibles/claim', { method: 'POST', body: JSON.stringify({ username }) }),
    collectMine: () => req('/collectibles/mine'),
    collectShowcase: () => req('/collectibles/showcase'),
    collectTransfer: (username, to) => req('/collectibles/transfer', { method: 'POST', body: JSON.stringify({ username, to_user_id: to }) }),
    collectSell: (username, price) => req('/collectibles/sell', { method: 'POST', body: JSON.stringify({ username, price }) }),
    collectBuy: (username) => req('/collectibles/buy', { method: 'POST', body: JSON.stringify({ username }) }),
    collectWear: (username) => req('/collectibles/wear', { method: 'POST', body: JSON.stringify({ username }) }),
    // round recording
    roundUpload: (blob) => { const fd = new FormData(); fd.append('file', blob, 'round.webm'); return fetch(B + '/round/upload', { method: 'POST', body: fd }).then((r) => r.json().catch(() => ({ success: false }))); },
    roundSendRef: (ref) => fetch((window.V2 || '/api.v2/api') + '/sputnik/round/send', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(ref || {}) }).then((r) => r.json().catch(() => ({ success: false }))),
  };

  function el(tag, cls, html) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }
  function toast(msg, kind) {
    if (window.K && K.ui && K.ui.toast) K.ui.toast(msg, kind || 'info');
  }
  function activeChat() { return (window.K && K.state && K.state.activeChat) || {}; }

  // Dice roller modal (Telegram dice idea) — sends to the open chat.
  const FACES = ['⚀', '⚁', '⚂', '⚃', '⚄', '⚅'];
  function diceModal() {
    const ac = activeChat();
    if (!ac.type || ac.id == null) { toast('Open a chat', 'error'); return; }
    const wrap = el('div', 'k-tg-dice');
    const face = el('div', 'k-tg-face', '🎲');
    const btn = el('button', 'k-sp-btn', 'Roll');
    btn.onclick = function () {
      face.textContent = '🎲';
      const ref = ac.type === 'personal' ? { chat_type: 'personal', peer_id: ac.id } : { chat_id: ac.id };
      api.dice(ref).then(function (r) {
        if (r && r.success) {
          face.textContent = FACES[r.data.value - 1];
          if (window.K && K.chat) K.chat.loadMessages(ac.type, ac.id);
        } else toast((r && r.error) || 'Failed', 'error');
      });
    };
    wrap.appendChild(face);
    wrap.appendChild(btn);
    if (window.K && K.sputnik && K.sputnik.showModal) K.sputnik.showModal('Dice', wrap);
    else { document.body.appendChild(wrap); }
  }

  // Forum topic bar above the message list (groups with topics).
  function renderTopicBar(mount, chatId, onPick) {
    if (!mount) return Promise.resolve();
    return api.topics(chatId).then(function (r) {
      const topics = (r && r.data && r.data.topics) || [];
      mount.innerHTML = '';
      if (!topics.length) { mount.style.display = 'none'; return; }
      mount.style.display = '';
      mount.className = 'k-tg-topics';
      const all = el('button', 'k-folder-chip active', 'General');
      all.onclick = function () {
        mount.querySelectorAll('.k-folder-chip').forEach((c) => c.classList.remove('active'));
        all.classList.add('active');
        if (onPick) onPick(null);
      };
      mount.appendChild(all);
      topics.forEach(function (t) {
        const b = el('button', 'k-folder-chip', '');
        b.textContent = (t.icon ? t.icon + ' ' : '') + t.title + (t.messages ? ' · ' + t.messages : '');
        b.title = t.is_closed ? 'Closed' : '';
        b.onclick = function () {
          mount.querySelectorAll('.k-folder-chip').forEach((c) => c.classList.remove('active'));
          b.classList.add('active');
          if (onPick) onPick(t);
        };
        mount.appendChild(b);
      });
      const add = el('button', 'k-folder-chip', '+ Topic');
      add.onclick = function () {
        const title = window.prompt ? window.prompt('Topic name:') : null;
        if (!title) return;
        api.topicCreate(chatId, title).then(() => renderTopicBar(mount, chatId, onPick));
      };
      mount.appendChild(add);
    }).catch(function () {});
  }

  // Decorate chat messages: big dice, geo links. Chain-aware like sputnik
  // (shared _spChain — each layer applies exactly once).
  function decorate() {
    if (!window.K || !K.chat || !K.chat._messageHtml) return;
    const fn = K.chat._messageHtml;
    fn._spChain = fn._spChain || [];
    if (fn._spChain.includes('tg')) return;
    const orig = fn;
    const wrapped = function (m, isOwn, consecutive) {
      let h = orig.call(this, m, isOwn, consecutive);
      try {
        const attRe2 = /<div class="(?:k-msg-attachment|k-msg-file)">[\s\S]*?<\/div>/;
        const textRe = /<div class="k-msg-text">[\s\S]*?<\/div>/;
        if (m && m.file_type === 'dice') {
          const v = parseInt(m.content, 10);
          const val = (isNaN(v) || v < 1 || v > 6) ? 1 : v;
          const others = [1, 2, 3, 4, 5, 6].filter((x) => x !== val);
          // front + top show the rolled value, the rest fill the cube
          const faces = [val, 7 - val, others[0], others[1], val, others[2]];
          const cube = '<div class="k-tg-cube k-tg-roll">' + faces.map((n, i) =>
            '<div class="k-tg-face k-tg-f' + i + '">' + n + '</div>').join('') + '</div>';
          const cubeHtml = '<div class="k-tg-dice-msg">' + cube + '</div>';
          h = attRe2.test(h) ? h.replace(attRe2, cubeHtml) : h.replace(textRe, cubeHtml);
        } else if (m && m.file_type === 'geo' && m.content) {
          const parts = String(m.content).split(',');
          if (parts.length === 2) {
            const url = 'https://www.openstreetmap.org/?mlat=' + encodeURIComponent(parts[0].trim()) + '&mlon=' + encodeURIComponent(parts[1].trim()) + '#map=15/' + encodeURIComponent(parts[0].trim()) + '/' + encodeURIComponent(parts[1].trim());
            const geo = '<div class="k-tg-geo"><a href="' + url + '" target="_blank" rel="noopener">📍 ' + esc(parts[0].trim()) + ', ' + esc(parts[1].trim()) + '</a></div>';
            h = attRe2.test(h) ? h.replace(attRe2, geo) : h.replace(textRe, geo);
          }
        }
      } catch (e) { /* never break chat */ }
      return h;
    };
    wrapped._spChain = [...fn._spChain, 'tg'];
    wrapped._tgWrapped = true;
    K.chat._messageHtml = wrapped;
  }

  // Saved-with-tags modal.
  function showSaved() {
    api.savedTags().then(function (r) {
      const tags = (r && r.data && r.data.tags) || [];
      const list = el('div', 'k-sp-list');
      function load(tag) {
        api.savedList(tag).then(function (rr) {
          list.innerHTML = '';
          const items = (rr && rr.data && rr.data.saved) || [];
          if (!items.length) list.appendChild(el('div', 'k-sp-empty', 'Empty'));
          items.forEach(function (s) {
            const row = el('div', 'k-sp-row');
            const tx = el('span', 'k-sp-text', '');
            tx.textContent = '#' + s.message_id + (s.tag ? ' · ' + s.tag : '');
            row.appendChild(tx);
            list.appendChild(row);
          });
        });
      }
      const bar = el('div', 'k-tg-topics');
      const all = el('button', 'k-folder-chip active', 'All');
      all.onclick = function () { bar.querySelectorAll('.k-folder-chip').forEach((c) => c.classList.remove('active')); all.classList.add('active'); load(''); };
      bar.appendChild(all);
      tags.forEach(function (t) {
        const b = el('button', 'k-folder-chip', '');
        b.textContent = t.tag + ' · ' + t.count;
        b.onclick = function () { bar.querySelectorAll('.k-folder-chip').forEach((c) => c.classList.remove('active')); b.classList.add('active'); load(t.tag); };
        bar.appendChild(b);
      });
      const wrap = el('div', '');
      wrap.appendChild(bar);
      wrap.appendChild(list);
      load('');
      if (window.K && K.sputnik && K.sputnik.showModal) K.sputnik.showModal('Tagged', wrap);
    });
  }

  // Wire: dice composer button + topic bar on chat switch + nav entry.
  let _lastKey = '';
  function autoWire() {
    decorate();
    const input = document.getElementById('messageInput');
    if (input && input.parentElement && !document.getElementById('k-tg-round-btn')) {
      const rb = el('button', 'k-icon-btn', '📹');
      rb.id = 'k-tg-round-btn';
      rb.title = 'Video circle';
      rb.onclick = recordRound;
      input.parentElement.insertBefore(rb, input.parentElement.firstChild);
    }
    if (input && input.parentElement && !document.getElementById('k-tg-dice-btn')) {
      const b = el('button', 'k-icon-btn', '🎲');
      b.id = 'k-tg-dice-btn';
      b.title = 'Dice';
      b.onclick = diceModal;
      input.parentElement.insertBefore(b, input.parentElement.firstChild);
    }
    const nav = document.querySelector('.k-nav');
    if (nav && !document.getElementById('k-tg-nav')) {
      const sec = el('div', '');
      sec.id = 'k-tg-nav';
      const a = el('a', 'k-nav-item');
      a.innerHTML = '<i class="fas fa-tags"></i><span>Tags</span>';
      a.onclick = showSaved;
      sec.appendChild(a);
      const c = el('a', 'k-nav-item');
      c.innerHTML = '<i class="fas fa-crown"></i><span>Names</span>';
      c.onclick = showCollectibles;
      sec.appendChild(c);
      nav.appendChild(sec);
    }
    const ac = activeChat();
    const key = (ac.type || '') + ':' + (ac.id == null ? '' : ac.id);
    const mc = document.getElementById('messagesContainer');
    if (mc && key !== _lastKey) {
      _lastKey = key;
      const old = document.getElementById('k-tg-topicbar');
      if (old) old.remove();
      if (ac.type === 'group' && ac.id != null) {
        const bar = el('div', '');
        bar.id = 'k-tg-topicbar';
        mc.parentNode.insertBefore(bar, mc);
        renderTopicBar(bar, ac.id, function (t) {
          if (!t) { K.chat.loadMessages(ac.type, ac.id); return; }
          api.topicMessages(t.topic_id).then(function (r) {
            const msgs = (r && r.data && r.data.messages) || [];
            mc.innerHTML = msgs.map((m) => K.chat.renderMessage(m)).join('');
          });
        });
      }
    }
  }

  window.K = window.K || {};
  K.tg = Object.assign({}, api, { diceModal, renderTopicBar, decorate, showSaved, autoWire, recordRound, showCollectibles });

  /* ---- video circles recorder + collectibles showcase ---- */

  // Record a 1-60s video circle from camera (Telegram circles idea).
  function recordRound() {
    const ac = activeChat();
    if (!ac.type || ac.id == null) { toast('Open a chat', 'error'); return; }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { toast('Camera unavailable (HTTPS required)', 'error'); return; }
    const wrap = el('div', 'k-tg-rec');
    const vid = document.createElement('video');
    vid.muted = true; vid.playsInline = true;
    vid.className = 'k-tg-rec-view';
    const timer = el('div', 'k-tg-rec-timer', '0:00');
    const row = el('div', 'k-sp-row');
    const recBtn = el('button', 'k-sp-btn', '● Record');
    const flipBtn = el('button', 'k-sp-btn', '↺ Camera');
    const sendBtn = el('button', 'k-sp-btn', 'Send');
    sendBtn.disabled = true;
    row.appendChild(recBtn); row.appendChild(flipBtn); row.appendChild(sendBtn);
    wrap.appendChild(vid); wrap.appendChild(timer); wrap.appendChild(row);
    const show = (window.K && K.sputnik && K.sputnik.showModal) ? K.sputnik.showModal('Circle', wrap) : null;
    if (!show) document.body.appendChild(wrap);
    let stream = null, rec = null, chunks = [], secs = 0, tick = 0, facing = 'user', blob = null;
    function stopTracks() { if (stream) stream.getTracks().forEach((t) => t.stop()); stream = null; }
    async function startCam() {
      stopTracks();
      try { stream = await navigator.mediaDevices.getUserMedia({ video: { width: 480, facingMode: facing }, audio: true }); }
      catch (e) { toast('No camera access', 'error'); return; }
      vid.srcObject = stream;
      vid.play().catch(function () {});
    }
    flipBtn.onclick = function () { facing = facing === 'user' ? 'environment' : 'user'; startCam(); };
    recBtn.onclick = function () {
      if (rec && rec.state !== 'inactive') { rec.stop(); return; }
      if (!stream) return;
      chunks = []; secs = 0; blob = null; sendBtn.disabled = true;
      const mime = MediaRecorder.isTypeSupported('video/webm;codecs=vp9') ? 'video/webm;codecs=vp9' : 'video/webm';
      rec = new MediaRecorder(stream, { mimeType: mime });
      rec.ondataavailable = function (e) { if (e.data.size) chunks.push(e.data); };
      rec.onstop = function () {
        clearInterval(tick);
        blob = new Blob(chunks, { type: 'video/webm' });
        vid.srcObject = null;
        vid.src = URL.createObjectURL(blob);
        vid.controls = true;
        sendBtn.disabled = false;
        recBtn.textContent = '● Record';
      };
      rec.start();
      recBtn.textContent = '■ Stop';
      tick = setInterval(function () {
        secs += 1;
        timer.textContent = Math.floor(secs / 60) + ':' + String(secs % 60).padStart(2, '0');
        if (secs >= 60 && rec) rec.stop();
      }, 1000);
    };
    sendBtn.onclick = function () {
      if (!blob) return;
      sendBtn.disabled = true;
      api.roundUpload(blob).then(function (u) {
        if (!u || !u.success) { toast('Upload failed', 'error'); sendBtn.disabled = false; return; }
        const ref = ac.type === 'personal'
          ? { chat_type: 'personal', peer_id: ac.id, file_path: u.data.file_path, duration: Math.max(1, secs) }
          : { chat_id: ac.id, file_path: u.data.file_path, duration: Math.max(1, secs) };
        return api.roundSendRef(ref);
      }).then(function (r) {
        stopTracks();
        const m = document.querySelector('.k-sp-modal'); if (m) m.remove(); else wrap.remove();
        if (r && r.success) { toast('Circle sent', 'success'); if (window.K && K.chat) K.chat.loadMessages(ac.type, ac.id); }
        else if (r) toast("Wasn't sent", 'error');
      });
    };
    startCam();
  }

  // Collectibles showcase: buy, claim, wear, sell.
  function showCollectibles() {
    const wrap = el('div', '');
    const list = el('div', 'k-sp-list');
    const foot = el('div', 'k-sp-foot');
    const claimBtn = el('button', 'k-sp-btn', 'Claim name');
    claimBtn.onclick = function () {
      const name = window.prompt ? window.prompt('Name 3-32 [a-z0-9_]:') : null;
      if (!name) return;
      api.collectClaim(name.trim()).then(function (r) {
        toast(r && r.success ? 'Claimed!' : ((r && r.error) || 'Failed'), r && r.success ? 'success' : 'error');
        refresh();
      });
    };
    foot.appendChild(claimBtn);
    wrap.appendChild(list);
    wrap.appendChild(foot);
    function row(tx, btnLabel, onBtn) {
      const r = el('div', 'k-sp-row');
      const t = el('span', 'k-sp-text', '');
      t.textContent = tx;
      r.appendChild(t);
      if (btnLabel) { const b = el('button', 'k-sp-btn', btnLabel); b.onclick = onBtn; r.appendChild(b); }
      list.appendChild(r);
    }
    function refresh() {
      list.innerHTML = '';
      api.collectMine().then(function (m) {
        const d = (m && m.data) || {};
        row('Your handle: @' + (d.wearing || '?'));
        ((d && d.collectibles) || []).forEach(function (c) {
          row('@' + c.username + (c.for_sale ? ' · for sale' + (c.price ? ' for ' + c.price + '★' : '') : ''), 'Wear', function () {
            api.collectWear(c.username).then(function (r) { toast(r && r.success ? "You're now @" + c.username : ((r && r.error) || 'Failed'), r && r.success ? 'success' : 'error'); refresh(); });
          });
        });
      });
      api.collectShowcase().then(function (s) {
        (((s && s.data) || {}).for_sale || []).forEach(function (c) {
          row('@' + c.username + ' · ' + (c.price || '?') + '★ · ' + (c.owner || ''), 'Buy', function () {
            api.collectBuy(c.username).then(function (r) { toast(r && r.success ? 'Bought!' : ((r && r.error) || 'Failed'), r && r.success ? 'success' : 'error'); refresh(); });
          });
        });
      });
    }
    refresh();
    if (window.K && K.sputnik && K.sputnik.showModal) K.sputnik.showModal('Names', wrap);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { autoWire(); observe(); });
  } else { autoWire(); observe(); }
  function observe() {
    if (window._tgObserver) return;
    new MutationObserver(function () { autoWire(); }).observe(document.body, { childList: true, subtree: true });
    window._tgObserver = true;
  }
})();
