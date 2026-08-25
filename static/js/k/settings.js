const PERCENT = 100;
const QR_IMAGE_SIZE = 200;

K.settings = {
  _isDark() { return document.documentElement.getAttribute('data-theme') === 'dark'; },
  toggleTheme() {
    const isDark = !K.settings._isDark();
    K.settings._applyTheme(isDark);
  },
  setTheme(t) {
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    if (t === 'auto') {
      isDark = prefersDark;
    } else {
      isDark = t === 'dark';
    }
    K.settings._applyTheme(isDark);
  },
  _applyTheme(isDark, skipSave) {
    if (isDark) document.documentElement.setAttribute('data-theme', 'dark');
    else document.documentElement.removeAttribute('data-theme');
    localStorage.setItem('k_theme', isDark ? 'dark' : 'light');
    const sw = $('themeSwitch'); if (sw) sw.checked = isDark;
    const icon = $('themeIcon'); if (icon) icon.className = isDark ? 'fas fa-sun' : 'fas fa-moon';
    const label = $('themeLabel'); if (label) label.textContent = isDark ? 'Light Mode' : 'Dark Mode';
    const ni = $('navThemeIcon'); if (ni) ni.className = isDark ? 'fas fa-sun' : 'fas fa-moon';
    const nl = $('navThemeLabel'); if (nl) nl.textContent = isDark ? 'Light mode' : 'Dark mode';
    if (!skipSave) K.settings.saveToServer();
  },
  setFontSize(s, skipSave) {
    document.querySelectorAll('.k-font-btn').forEach(b => b.classList.toggle('active', b.dataset.size === s));
    const sizes = { small: '13px', medium: '14px', large: '16px' };
    document.querySelector('.k-app').style.fontSize = sizes[s] || '14px';
    localStorage.setItem('k_font_size', s);
    if (!skipSave) K.settings.saveToServer();
  },
  switchTab(tab) {
    document.querySelectorAll('.k-stab').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
    document.querySelectorAll('.k-settings-tab-content').forEach(p => p.style.display = p.dataset.tab === tab ? '' : 'none');
    if (tab === 'folders') K.settings.renderFolders();
    if (tab === 'themes') K.settings.renderSavedThemes();
    if (tab === 'privacy') K.settings.loadPrivacy();
    if (tab === 'sessions') K.settings.loadSessions();
    if (tab === 'bots') K.settings.loadBots();
    K.state.saveURL();
  },
  setHero(url) {
    const bg = $('splashScreen')?.querySelector('.k-splash-bg');
    if (bg) {
      if (url) { bg.style.backgroundImage = 'url("' + url.replace(/["\\]/g, '') + '")'; localStorage.setItem('k_hero_url', url); }
      else { bg.style.backgroundImage = ''; localStorage.removeItem('k_hero_url'); }
    }
    K.settings.saveToServer();
  },
  loadHero() {
    const url = localStorage.getItem('k_hero_url');
    if (url) { const bg = $('splashScreen')?.querySelector('.k-splash-bg'); if (bg) bg.style.backgroundImage = 'url("' + url.replace(/["\\]/g, '') + '")'; }
    const hu = $('heroUrlInput'); if (hu) hu.value = url || '';
  },
  async loadPrivacy() {
    try {
      const d = await K.api.get(V2 + '/profile/privacy');
      if (d.success && d.data) {
        const selects = document.querySelectorAll('.k-settings-item select');
        if (selects[0]) selects[0].value = d.data.last_seen || 'everyone';
        if (selects[1]) selects[1].value = d.data.profile_photo || 'everyone';
      }
    } catch(e) { K.ui.toast('Failed to load privacy settings', 'error'); }
  },
  async updatePrivacy(key, value) {
    try {
      await K.api.put(V2 + '/profile', {[key]: value});
      K.ui.toast('Privacy updated', 'success');
    } catch(e) { K.ui.toast('Failed', 'error'); }
  },
  async toggleReadReceipts(value) {
    localStorage.setItem('k_read_receipts', value);
    K.settings.saveToServer();
    K.ui.toast('Read receipts ' + (value === 'true' ? 'enabled' : 'disabled'), 'success');
  },
startLakeBackgrounds() {
    if (!K.state.user?.is_premium) {
      K.ui.toast('Dynamic lake backgrounds are a Premium feature', 'info');
      return;
    }
    // Photo URLs - served from static/ folder
    const photos = [
      '/static/lake1.jpg',
      '/static/lake2.jpg',
      '/static/lake3.jpg'
    ];
    let currentIndex = localStorage.getItem('k_lake_index') ? parseInt(localStorage.getItem('k_lake_index')) : 0;
    const intervalMs = 30 * 60 * 1000; // 30 min base
    const randomOffset = Math.floor(Math.random() * (50 * 60 * 1000 - 30 * 60 * 1000 + 1)) + 30 * 60 * 1000; // 30-50 min random
    let timer = null;
    
    // Create overlay element if not exists
    let overlay = document.querySelector('.lake-overlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.className = 'lake-overlay';
      overlay.style.cssText = `
        position: fixed;
        bottom: 20px;
        left: 20px;
        color: var(--text-primary, #fff);
        font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
        font-size: 12px;
        background: rgba(0,0,0,0.6);
        padding: 8px 12px;
        border-radius: 4px;
        z-index: 1000;
        user-select: none;
      `;
      document.body.appendChild(overlay);
    }
    
    function setBackground(idx) {
      currentIndex = idx % photos.length;
      const photo = photos[currentIndex];
      document.documentElement.style.setProperty('--hero-image', `url("${photo}")`);
      localStorage.setItem('k_lake_index', String(currentIndex));
      // Update time overlay
      const now = new Date();
      const options = { 
        weekday: 'short', 
        month: 'short', 
        day: 'numeric',
        hour: '2-digit', 
        minute: '2-digit' 
      };
      overlay.textContent = now.toLocaleDateString(undefined, options);
    }
    
    // Set first photo immediately
    setBackground(0);
    
    // Schedule next change with random 30-50 min interval
    function scheduleNext() {
      timer = setTimeout(() => {
        currentIndex = (currentIndex + 1) % photos.length;
        setBackground(currentIndex);
        // Reschedule with new random interval
        scheduleNext();
      }, randomOffset);
    }
    
    scheduleNext();
    
    // Store the timer reference for cleanup
    localStorage.setItem('k_lake_timer', String(timer || ''));
    // Start updating time overlay every minute
    this.updateLakeTime();
    setInterval(() => this.updateLakeTime(), 60000);
    K.ui.toast('Dynamic lake backgrounds started', 'success');
  },
  
  // Update time overlay periodically
  updateLakeTime() {
    const overlay = document.querySelector('.lake-overlay');
    if (overlay) {
      const now = new Date();
      const options = { 
        weekday: 'short', 
        month: 'short', 
        day: 'numeric',
        hour: '2-digit', 
        minute: '2-digit' 
      };
      overlay.textContent = now.toLocaleDateString(undefined, options);
    }
  },
  stopLakeBackgrounds() {
    const timer = localStorage.getItem('k_lake_timer');
    if (timer && timer !== 'null' && timer !== 'undefined') {
      clearTimeout(timer);
      localStorage.removeItem('k_lake_timer');
    }
    // Remove the hero image var
    document.documentElement.style.removeProperty('--hero-image');
    // Remove overlay
    const overlay = document.querySelector('.lake-overlay');
    if (overlay) overlay.remove();
    localStorage.removeItem('k_lake_index');
    K.ui.toast('Lake backgrounds stopped', 'success');
  },
  stopLakeBackgrounds() {
    const timer = localStorage.getItem('k_lake_timer');
    if (timer && timer !== 'null' && timer !== 'undefined') {
      clearTimeout(timer);
      localStorage.removeItem('k_lake_timer');
    }
    // Remove the hero image var
    document.documentElement.style.removeProperty('--hero-image');
    localStorage.removeItem('k_lake_index');
    K.ui.toast('Lake backgrounds stopped', 'success');
  },
  async loadSessions() {
    try {
      const d = await K.api.get(V2 + '/sessions');
      if (d.success) {
        const list = $('sessionsList');
        if (list) {
          const sessions = d.data?.sessions || [];
          list.innerHTML = sessions.length ? sessions.map(s =>
            `<div class="k-settings-item"><span><strong>${esc(s.device||'Unknown')}</strong>${s.is_current ? ' <span style="color:var(--online-green)">(current)</span>' : ''}<br><span style="font-size:12px;color:var(--text-muted)">${esc(s.ip_address||'')}</span></span><span style="font-size:11px;color:var(--text-muted)">${s.last_activity||s.last_active ? fmtTime(s.last_activity||s.last_active) : ''}</span></div>`
          ).join('') : '<div style="color:var(--text-muted);padding:12px">No active sessions</div>';
        }
      }
    } catch(e) { K.ui.toast('Failed to load sessions', 'error'); }
  },
  _setBubbleColor(cssVar, storageKey, color, skipSave) {
    document.documentElement.style.setProperty(cssVar, color);
    localStorage.setItem(storageKey, color);
    if (!skipSave) K.settings.saveToServer();
  },
  setMyColor(color, skipSave) { K.settings._setBubbleColor('--bubble-my', 'k_color_my', color, skipSave); },
  setTheirColor(color, skipSave) { K.settings._setBubbleColor('--bubble-their', 'k_color_their', color, skipSave); },
  _showPeerIds() { return localStorage.getItem('k_show_peer_ids') === '1'; },
  setShowPeerIds(checked, skipSave) {
    localStorage.setItem('k_show_peer_ids', checked ? '1' : '0');
    const cb = $('showPeerIds'); if (cb) cb.checked = !!checked;
    if (!skipSave) K.settings.saveToServer();
    if (K.chat?.loadList) K.chat.loadList();
    if (K.chat?.loadMessages && K.state?.activeChat) {
      K.chat.loadMessages(K.state.activeChat.type, K.state.activeChat.id);
      K.chat.loadHeader(K.state.activeChat.type, K.state.activeChat.id);
    }
  },
  addFolder() {
    const name = prompt('Folder name:');
    if (name && name.trim()) {
      K.state.folders = K.state.folders || [];
      K.state.folders.push({name: name.trim(), chats: []});
      localStorage.setItem('k_folders', JSON.stringify(K.state.folders));
      K.settings.saveToServer();
      K.settings.renderFolders();
      K.settings.renderFolderBar();
    }
  },
  deleteFolder(name) {
    K.state.folders = (K.state.folders||[]).filter(f => f.name !== name);
    localStorage.setItem('k_folders', JSON.stringify(K.state.folders));
    K.settings.saveToServer();
    if (K.state.activeFolder === name) K.state.activeFolder = null;
    K.settings.renderFolders();
    K.settings.renderFolderBar();
    K.chat.loadList();
  },
  renameFolder(oldName) {
    const newName = prompt('New folder name:', oldName);
    if (newName && newName.trim() && newName.trim() !== oldName) {
      const f = K.state.folders.find(x => x.name === oldName);
      if (f) { f.name = newName.trim(); localStorage.setItem('k_folders', JSON.stringify(K.state.folders)); K.settings.saveToServer(); K.settings.renderFolders(); K.settings.renderFolderBar(); }
    }
  },
  renderFolders() {
    const list = $('foldersList'); if (!list) return;
    const folders = K.state.folders || [];
    if (!folders.length) { list.innerHTML = '<div style="padding:12px;color:var(--text-muted);font-size:13px">No folders yet. Create one to organize chats.</div>'; return; }
    list.innerHTML = folders.map(f =>
      `<div class="k-settings-item">
        <span><i class="fas fa-folder" style="margin-right:8px;color:var(--accent-blue)"></i>${esc(f.name)} <span style="font-size:11px;color:var(--text-muted)">(${(f.chats||[]).length} chats)</span></span>
        <span style="display:flex;gap:4px">
          <button class="k-icon-btn" onclick="K.settings.renameFolder('${esc(f.name)}')" style="font-size:14px;width:28px;height:28px" title="Rename"><i class="fas fa-pen"></i></button>
          <button class="k-icon-btn" onclick="K.settings.deleteFolder('${esc(f.name)}')" style="font-size:14px;width:28px;height:28px;color:var(--accent-red)" title="Delete"><i class="fas fa-trash"></i></button>
        </span>
      </div>`
    ).join('');
  },
  renderFolderBar() {
    const bar = $('folderBar'); if (!bar) return;
    const folders = K.state.folders || [];
    if (!folders.length) { bar.style.display = 'none'; return; }
    bar.style.display = 'flex';
    const af = K.state.activeFolder;
    bar.innerHTML = `<button class="k-folder-btn ${!af?'active':''}" onclick="K.state.activeFolder=null;K.settings.renderFolderBar();K.chat.loadList()">All</button>` +
      folders.map(f => `<button class="k-folder-btn ${af===f.name?'active':''}" onclick="K.state.activeFolder='${esc(f.name)}';K.settings.renderFolderBar();K.chat.loadList()">${esc(f.name)}</button>`).join('');
  },
  _savedThemes() { try { return JSON.parse(localStorage.getItem('k_saved_themes')||'[]'); } catch(e) { return []; } },
  saveCurrentTheme() {
    const saved = K.settings._savedThemes();
    const t = {
      name: 'Theme ' + (saved.length + 1),
      version: 1,
      theme: K.settings._isDark() ? 'dark' : 'light',
      font_size: localStorage.getItem('k_font_size')||'medium',
      color_my: localStorage.getItem('k_color_my')||'#5e72e4',
      color_their: localStorage.getItem('k_color_their')||'#e8e8e8',
      hero_url: localStorage.getItem('k_hero_url')||''
    };
    saved.push(t);
    localStorage.setItem('k_saved_themes', JSON.stringify(saved));
    K.settings.saveToServer();
    K.settings.renderSavedThemes();
    K.ui.toast('Theme saved', 'success');
  },
  renderSavedThemes() {
    const list = $('themeList'); if (!list) return;
    const saved = K.settings._savedThemes();
    if (!saved.length) { list.innerHTML = '<div style="padding:12px;color:var(--text-muted);font-size:13px">No saved themes</div>'; return; }
    list.innerHTML = saved.map((t, i) =>
      `<div class="k-settings-item">
        <span><span style="display:inline-block;width:16px;height:16px;border-radius:50%;background:${t.color_my};margin-right:8px;vertical-align:middle"></span>${esc(t.name)}</span>
        <span style="display:flex;gap:4px">
          <button class="k-btn k-btn-secondary" style="padding:4px 10px;font-size:12px" onclick="K.settings.applySavedTheme(${i})">Apply</button>
          <button class="k-icon-btn" onclick="K.settings.deleteSavedTheme(${i})" style="font-size:14px;width:28px;height:28px;color:var(--accent-red)" title="Delete"><i class="fas fa-trash"></i></button>
        </span>
      </div>`
    ).join('');
    const cl = $('savedThemeList');
    if (cl) cl.innerHTML = list.innerHTML;
  },
  applySavedTheme(idx) {
    const saved = K.settings._savedThemes();
    const t = saved[idx]; if (!t) return;
    K.settings._applyTheme(t.theme === 'dark');
    K.settings.setFontSize(t.font_size);
    K.settings.setMyColor(t.color_my);
    K.settings.setTheirColor(t.color_their);
    K.settings.setHero(t.hero_url);
    K.settings.saveToServer();
    K.ui.toast('Theme applied: ' + t.name, 'success');
  },
  deleteSavedTheme(idx) {
    const saved = K.settings._savedThemes();
    saved.splice(idx, 1);
    localStorage.setItem('k_saved_themes', JSON.stringify(saved));
    K.settings.saveToServer();
    K.settings.renderSavedThemes();
  },
  exportTheme() {
    const t = {
      name: 'Kiselgram Theme',
      version: 1,
      theme: K.settings._isDark() ? 'dark' : 'light',
      font_size: localStorage.getItem('k_font_size')||'medium',
      color_my: localStorage.getItem('k_color_my')||'#5e72e4',
      color_their: localStorage.getItem('k_color_their')||'#e8e8e8',
      hero_url: localStorage.getItem('k_hero_url')||''
    };
    const blob = new Blob([JSON.stringify(t, null, 2)], {type: 'application/json'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'kiselgram-theme.ktqh';
    a.click();
    URL.revokeObjectURL(a.href);
  },
  async loadFromServer() {
    try {
      const d = await K.api.get(V2 + '/k/settings');
      if (d.success && d.data?.settings) {
        const s = d.data.settings;
        if (s.pinned) { K.state.pinned = s.pinned; localStorage.setItem('k_pinned', JSON.stringify(s.pinned)); }
        if (s.folders) { K.state.folders = s.folders; localStorage.setItem('k_folders', JSON.stringify(s.folders)); }
        if (s.hero_url) { localStorage.setItem('k_hero_url', s.hero_url); K.settings.loadHero(); }
        if (s.theme) { localStorage.setItem('k_theme', s.theme); K.settings._applyTheme(s.theme === 'dark', true); }
        if (s.font_size) { localStorage.setItem('k_font_size', s.font_size); K.settings.setFontSize(s.font_size, true); }
        if (s.color_my) { localStorage.setItem('k_color_my', s.color_my); K.settings.setMyColor(s.color_my, true); }
        if (s.color_their) { localStorage.setItem('k_color_their', s.color_their); K.settings.setTheirColor(s.color_their, true); }
        if (s.saved_themes) { localStorage.setItem('k_saved_themes', JSON.stringify(s.saved_themes)); }
        if (s.music_tracks) { K.music._tracks = s.music_tracks; localStorage.setItem('k_music_tracks', JSON.stringify(s.music_tracks)); }
        if (typeof s.show_peer_ids !== 'undefined') {
          localStorage.setItem('k_show_peer_ids', s.show_peer_ids ? '1' : '0');
          const cb = $('showPeerIds'); if (cb) cb.checked = !!s.show_peer_ids;
        }
if (typeof s.read_receipts !== 'undefined') {
          localStorage.setItem('k_read_receipts', s.read_receipts ? 'true' : 'false');
          const cb = document.querySelector('#readReceipts'); if (cb) cb.value = s.read_receipts ? 'true' : 'false';
        }
      }
    } catch(e) { K.ui.toast('Failed to load settings', 'error'); }
  },
  _saveTimer: null,
  async saveToServer() {
    if (K.settings._saveTimer) clearTimeout(K.settings._saveTimer);
    K.settings._saveTimer = setTimeout(async () => {
      K.settings._saveTimer = null;
      const settings = {
      pinned: K.state.pinned || [],
      folders: K.state.folders || [],
      hero_url: localStorage.getItem('k_hero_url') || '',
      theme: localStorage.getItem('k_theme') || 'light',
      font_size: localStorage.getItem('k_font_size') || 'medium',
      color_my: localStorage.getItem('k_color_my') || '#5e72e4',
      color_their: localStorage.getItem('k_color_their') || '#e8e8e8',
      saved_themes: K.settings._savedThemes(),
      music_tracks: K.music._tracks || [],
      show_peer_ids: K.settings._showPeerIds(),
      read_receipts: localStorage.getItem('k_read_receipts') === 'true'
    };
    try {
      await K.api.put(V2 + '/k/settings', {settings});
    } catch(e) { K.ui.toast('Failed to save settings', 'error'); }
    }, 300);
  },
  importTheme(input) {
    if (!input?.files?.length) return;
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const t = JSON.parse(e.target.result);
        if (t.theme) K.settings._applyTheme(t.theme === 'dark');
        if (t.font_size) K.settings.setFontSize(t.font_size);
        if (t.color_my) K.settings.setMyColor(t.color_my);
        if (t.color_their) K.settings.setTheirColor(t.color_their);
        if (t.hero_url) K.settings.setHero(t.hero_url);
        K.ui.toast('Theme imported: ' + (t.name||'Unknown'), 'success');
      } catch(e) { K.ui.toast('Invalid theme file', 'error'); }
    };
    reader.readAsText(input.files[0]);
    input.value = '';
  },
  async loadBots() {
    const el = $('myBotsList'); if (!el) return;
    el.innerHTML = K.ui.loader();
    try {
      const d = await K.api.get(V2 + '/bots');
      if (!d.success || !d.data?.bots?.length) {
        el.innerHTML = '<div class="k-empty" style="padding:20px"><i class="fas fa-robot"></i><h3>No bots</h3><p>Create bots in Premium settings</p></div>';
        return;
      }
      el.innerHTML = d.data.bots.map(b => `
        <div class="k-settings-item" style="flex-direction:column;align-items:stretch;gap:6px;padding:12px">
          <div style="display:flex;align-items:center;gap:8px">
            <div style="width:44px;height:44px;flex-shrink:0;border-radius:50%;overflow:hidden">${K.ui.avatar(b.display_name||b.username, b.avatar_url)}</div>
            <span style="font-weight:600;flex:1">${esc(b.display_name||b.username)} <span style="font-size:12px;color:var(--text-muted)">@${esc(b.username)}</span></span>
          </div>
          <div style="display:flex;gap:6px">
            <input class="k-input" id="webappUrl_${b.bot_id}" value="${esc(b.bot_webapp_url||'')}" placeholder="https://your-web-app.com" style="flex:1;font-size:13px">
            <button class="k-btn k-btn-primary" style="font-size:13px;padding:6px 12px;white-space:nowrap" onclick="K.settings.saveBotWebapp(${b.bot_id})">Save</button>
          </div>
        </div>`).join('');
    } catch(e) { el.innerHTML = '<div class="k-empty"><p>Failed to load bots</p></div>'; }
  },
  async saveBotWebapp(botId) {
    const input = $('webappUrl_' + botId);
    if (!input) return;
    let url = input.value.trim();
    if (url && !url.startsWith('http://') && !url.startsWith('https://')) {
      url = 'https://' + url;
      input.value = url;
    }
    try {
      const d = await K.api.put(V2 + `/bot/${botId}/webapp`, {webapp_url: url});
      if (d.success) { K.ui.toast('Web App URL saved', 'success'); }
      else { K.ui.toast(d.error?.message || 'Failed', 'error'); }
    } catch(e) { K.ui.toast('Error', 'error'); }
  },
  async createBot() {
    const username = $('botUsername')?.value.trim();
    const displayName = $('botDisplayName')?.value.trim();
    const resultEl = $('botTokenResult');
    if (!username) { K.ui.toast('Enter a bot username', 'error'); return; }
    try {
      const d = await K.api.post(V2 + '/bots', {username, display_name: displayName || undefined});
      if (d.success) {
        $('botUsername').value = '';
        $('botDisplayName').value = '';
        if (resultEl) {
          resultEl.style.display = 'block';
          resultEl.innerHTML = '<div style="font-weight:600;margin-bottom:4px">Bot created! Token (save this):</div><code style="font-size:12px;word-break:break-all">' + esc(d.data.bot_token) + '</code>';
        }
        K.ui.toast('Bot created', 'success');
        this.loadBots();
      } else {
        const msg = d.error?.fields?.username || d.error?.message || 'Failed';
        K.ui.toast(msg, 'error');
      }
    } catch(e) {
      const msg = e.body?.error?.fields?.username || e.body?.error?.message || 'Error creating bot';
      K.ui.toast(msg, 'error');
    }
  },
  async loadInvite() {
    const qrEl = $('inviteQR');
    const linkEl = $('inviteLink');
    const countEl = $('inviteCount');
    const barEl = $('referralBar');
    const statusEl = $('inviteStatus');
    const badgeEl = $('premiumBadge');
    const listEl = $('referredUsersList');
    if (!qrEl) return;
    try {
      const d = await K.api.get(V2 + '/referrals/info');
      if (d.success) {
        const data = d.data;
        if (linkEl) linkEl.textContent = data.invite_url.replace('https://', '');
        if (countEl) countEl.textContent = data.count + '/' + data.threshold;
        if (barEl) barEl.style.width = Math.min(PERCENT, (data.count / data.threshold) * PERCENT) + '%';
        if (statusEl) statusEl.textContent = data.count >= data.threshold ? 'Premium unlocked!' : data.count + '/' + data.threshold + ' to Premium';
        if (badgeEl) badgeEl.style.display = data.has_premium ? '' : 'none';
        if (data.has_premium && K.state.user && !K.state.user.is_premium) {
          K.state.user.is_premium = true;
          K.ui.renderUser();
        }
        qrEl.innerHTML = '';
        const img = document.createElement('img');
        img.src = `https://api.qrserver.com/v1/create-qr-code/?size=${QR_IMAGE_SIZE}x${QR_IMAGE_SIZE}&data=${encodeURIComponent(data.invite_url)}`;
img.alt = 'Invite QR';
img.style.width = QR_IMAGE_SIZE + 'px';
img.style.height = QR_IMAGE_SIZE + 'px';
        img.style.borderRadius = '8px';
        qrEl.appendChild(img);
        if (listEl) {
          const r = await K.api.get(V2 + '/referrals/list');
          if (r.success && r.data.length) {
            listEl.innerHTML = r.data.map(u =>
              '<div class="k-settings-item"><span>@' + esc(u.username) + '</span><span style="font-size:11px;color:var(--text-muted)">' + fmtTime(new Date(u.created_at)) + '</span></div>'
            ).join('');
          } else {
            listEl.innerHTML = '<div style="color:var(--text-muted);padding:12px;font-size:13px">No referrals yet</div>';
          }
        }
      }
    } catch(e) { K.ui.toast('Failed to load invite info', 'error'); }
  },
  copyInviteLink() {
    const el = $('inviteLink');
    if (!el) return;
    const url = 'https://' + el.textContent;
    navigator.clipboard.writeText(url).then(() => K.ui.toast('Link copied!', 'success')).catch(() => K.ui.toast('Failed to copy', 'error'));
  }
};
