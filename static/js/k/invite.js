'use strict';
/* K.invite — handle public invite links (#join-<type>-<id>-<code>).
 * Landing pages (/join/<code>, /c/<code>) point here. Flow: stash the
 * invite, wait for login (showing the picker if needed), call the join
 * API, then open the chat. Safe to load anywhere after init.js. */
(function () {
  function parse() {
    const h = (window.location.hash || '').replace(/^#/, '');
    const m = h.match(/^join-(group|channel)-(\d+)-(.+)$/);
    if (!m) return null;
    return { type: m[1], id: parseInt(m[2], 10), code: m[3] };
  }

  function loggedIn() {
    return !!(window.K && K.state && K.state.user);
  }

  async function accept(inv) {
    const V2 = (window.V2 || '/api.v2/api');
    try {
      if (inv.type === 'group') {
        await K.api.get(V2 + '/join_group/' + encodeURIComponent(inv.code));
      } else {
        await K.api.post(V2 + '/channels/' + inv.id + '/subscribe', {});
      }
    } catch (e) {
      if (window.K && K.ui && K.ui.toast) {
        K.ui.toast('Could not join: ' + (e.body?.error?.message || e.message || 'error'), 'error');
      }
      return false;
    }
    if (window.K && K.ui && K.ui.toast) K.ui.toast('Joined!', 'success');
    try { window.history.replaceState(null, '', window.location.pathname); } catch (e) {}
    try { sessionStorage.removeItem('k_pending_invite'); } catch (e) {}
    if (window.K && K.chat) K.chat.open(inv.type, inv.id);
    return true;
  }

  async function watch() {
    // referral code (?ref=) — stashed until registration completes
    try {
      const ref = new URLSearchParams(window.location.search).get('ref');
      if (ref) sessionStorage.setItem('k_pending_ref', ref.trim());
    } catch (e) {}
    let inv = parse();
    if (inv) {
      try { sessionStorage.setItem('k_pending_invite', JSON.stringify(inv)); } catch (e) {}
      try { window.history.replaceState(null, '', window.location.pathname); } catch (e) {}
    } else {
      try { inv = JSON.parse(sessionStorage.getItem('k_pending_invite') || 'null'); } catch (e) { inv = null; }
    }
    if (!inv) return;
    let pickerShown = false;
    const iv = setInterval(async () => {
      if (loggedIn()) {
        clearInterval(iv);
        await accept(inv);
      } else if (!pickerShown && window.K && K.loginV3) {
        pickerShown = true;
        try { K.loginV3.showPicker(); } catch (e) {}
      }
    }, 1000);
  }

  window.K = window.K || {};
  K.invite = { parse, accept, watch, pendingRef, applyReferral };

  function pendingRef() {
    try { return (sessionStorage.getItem('k_pending_ref') || '').trim() || null; }
    catch (e) { return null; }
  }

  // Call right after registration with the new user's id. Grants the
  // inviter +30d premium; safe to call without a ref (no-op).
  async function applyReferral(userId) {
    const ref = pendingRef();
    if (!ref || !userId) return null;
    try { sessionStorage.removeItem('k_pending_ref'); } catch (e) {}
    try {
      const V2 = (window.V2 || '/api.v2/api');
      const d = await K.api.post(V2 + '/referrals/use', { ref, user_id: userId });
      if (d && d.success && !d.data?.already_applied && window.K && K.ui && K.ui.toast) {
        K.ui.toast('Inviter earned 30 days of Premium!', 'success');
      }
      return d;
    } catch (e) { return null; }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', watch);
  } else {
    setTimeout(watch, 500);
  }
})();
