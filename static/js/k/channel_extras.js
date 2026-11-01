'use strict';
/* K.channelExtras — Sputnik-style channel/story extras. */
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
    storyShare: (story_id) => req('/stories/' + story_id + '/share', { method: 'POST' }),
    storyReplace: (story_id, patch) => req('/stories/' + story_id + '/replace', { method: 'POST', body: JSON.stringify(patch || {}) }),
    channelSub: (chat_id) => fetch(V2 + '/channels/' + chat_id + '/subscribe', { method: 'POST', headers: { 'Content-Type': 'application/json' } }).then((r) => r.json().catch(() => ({ success: false }))),
    stickerSendToActive: function (sticker_id) {
      const ac = (window.K && K.state && K.state.activeChat) || {};
      if (!ac.type || ac.id == null) return Promise.resolve({ success: false });
      const body = ac.type === 'personal'
        ? { sticker_id, chat_type: 'personal', peer_id: ac.id }
        : { sticker_id, chat_id: ac.id };
      return req('/stickers/send', { method: 'POST', body: JSON.stringify(body) });
    },
  };

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

  window.K = window.K || {};
  window.K.channelExtras = Object.assign({}, api, { mountStoryShare });
})();
