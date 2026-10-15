const SETTINGS_SWITCH_DELAY_MS = 100;
const CHAT_LIST_POLL_MS = 15000;
const MESSAGES_POLL_MS = 5000;
const STORIES_POLL_MS = 60000;
const SAVED_POLL_MS = 30000;

K.profile = {
  async save() {
    const name = $('editDisplayName')?.value?.trim();
    const bio = $('editBio')?.value?.trim();
    const isPremium = K.state.user?.is_premium;
    const payload = {display_name: name, bio};
    if (isPremium) {
      let statusEmoji = $('statusEmoji')?.value?.trim() || '';
      if (!statusEmoji) statusEmoji = '\u2b50';
      payload.status_emoji = statusEmoji;
      if (K.state.user) K.state.user.status_emoji = statusEmoji;
    }
    try {
      const d = await K.api.put(V2 + '/profile', payload);
      if (d.success) {
        K.ui.toast('Profile updated', 'success');
        const r = await K.api.get(V2 + '/profile');
        if (r.success && r.data) K.state.user = r.data;
        K.ui.renderUser(); K.modals.close();
      } else K.ui.toast('Failed', 'error');
    } catch(e) { K.ui.toast('Error', 'error'); }
  },
  async uploadAvatar(input) {
    if (!input?.files?.length) return;
    const fd = new FormData(); fd.append('avatar', input.files[0]);
    try {
      const d = await K.api.post(V2 + '/profile/avatar', fd);
      if (d.success) {
        K.ui.toast('Photo updated', 'success');
        if (K.state.user) K.state.user.avatar_url = d.data?.avatar_url;
        K.ui.renderUser();
      }
    } catch(e) { K.ui.toast('Upload failed', 'error'); }
  }
};

document.addEventListener('DOMContentLoaded', async () => {
  document.addEventListener('click', (e) => {
    const dd = $('searchDropdown');
    if (dd && !e.target.closest('.k-search-box')) dd.classList.remove('active');
    const menu = $('chatMenu');
    if (menu && !e.target.closest('#chatMenuBtn') && !e.target.closest('.k-chat-menu')) menu.style.display = 'none';
  });

  const menuBtn = $('menuBtn');
  const sb = $('sidebar');
  const backdrop = $('sidebarBackdrop');
  function closeSidebar() { sb?.classList.remove('open'); menuBtn?.classList.remove('active'); backdrop?.classList.remove('open'); }
  if (menuBtn) {
    menuBtn.addEventListener('click', (e) => { e.stopPropagation(); sb?.classList.toggle('open'); menuBtn.classList.toggle('active'); backdrop?.classList.toggle('open'); });
    backdrop?.addEventListener('click', closeSidebar);
    document.addEventListener('click', (e) => {
      if (sb?.classList.contains('open') && !sb.contains(e.target) && !menuBtn.contains(e.target)) {
        closeSidebar();
      }
    });
  }

  $('sidebar')?.querySelector('.k-sidebar-user')?.addEventListener('click', () => { K.modals.show('editProfile'); });
  document.querySelectorAll('.k-nav-item').forEach(item => {
    item.addEventListener('click', closeSidebar);
  });

  const savedTheme = localStorage.getItem('k_theme');
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  K.settings._applyTheme(savedTheme === 'dark' || (!savedTheme && prefersDark), true);
  const fs = localStorage.getItem('k_font_size') || 'medium';
  K.settings.setFontSize(fs, true);
  const myColor = localStorage.getItem('k_color_my') || '#5e72e4';
  const theirColor = localStorage.getItem('k_color_their') || '#e8e8e8';
  document.documentElement.style.setProperty('--bubble-my', myColor);
  document.documentElement.style.setProperty('--bubble-their', theirColor);
  document.documentElement.style.setProperty('--primary-color', myColor);
  const myInput = $('myColor'); if (myInput) myInput.value = myColor;
  const theirInput = $('theirColor'); if (theirInput) theirInput.value = theirColor;
  const cpMyInput = $('cpMyColor'); if (cpMyInput) cpMyInput.value = myColor;
  const cpTheirInput = $('cpTheirColor'); if (cpTheirInput) cpTheirInput.value = theirColor;
  // Apply liquid glass state early (before server load) without server save
  if (localStorage.getItem('k_liquid_glass') === '1') {
    document.body.classList.add('liquid-glass');
    const cb = $('liquidGlassMode'); if (cb) cb.checked = true;
    const sw = $('themeSwitch'); if (sw) sw.disabled = true;
    const cpSw = $('cpThemeSwitch'); if (cpSw) cpSw.disabled = true;
  }

  await K.auth.init();

  await K.settings.loadFromServer();
  K.settings.loadHero();
  K.settings.renderFolderBar();
  K.state.restoreURL();
  if (K.state._pendingChat) {
    const pc = K.state._pendingChat;
    delete K.state._pendingChat;
    K.chat.open(pc.type, pc.id);
  } else if (K.state._pendingSettings) {
    const ps = K.state._pendingSettings;
    delete K.state._pendingSettings;
    K.views.show('settings');
    setTimeout(() => K.settings.switchTab(ps), SETTINGS_SWITCH_DELAY_MS);
  }

  K._pollIntervals = [
    setInterval(() => K.chat.loadList(), CHAT_LIST_POLL_MS),
    setInterval(() => { if (K.state.activeChat) K.chat.loadMessages(K.state.activeChat.type, K.state.activeChat.id); }, MESSAGES_POLL_MS),
    setInterval(() => K.stories.load(), STORIES_POLL_MS),
    setInterval(() => K.saved.load(), SAVED_POLL_MS)
  ];
});
