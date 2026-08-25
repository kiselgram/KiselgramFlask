'use strict';

const USERNAME_MIN_LENGTH = 3;
const PASSWORD_MIN_LENGTH = 6;
const CHATS_PER_PAGE = 100;
const MESSAGES_PER_PAGE = 20;
const CONTENT_PREVIEW_MAX = 200;
const OTPS_PER_PAGE = 50;
const EMAIL_VER_PER_PAGE = 50;

K.adminPage = {
  _allUsers: [],
  _chatDetailPage: 1,
  _chatDetailId: null,
  _chatDetailHasMore: false,

  init() {
    if ($('loading')) $('loading').style.display = '';
    Promise.all([this.loadDashboard(), this.loadReports()]).then(() => {
      if ($('loading')) $('loading').style.display = 'none';
    });
  },

  // ── Tab switching ────────────────────────────────────

  initTabs() {
    document.querySelectorAll('.tab').forEach(tab => {
      tab.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        document.querySelectorAll('[id$="-tab"]').forEach(t => t.classList.add('hidden'));
        const target = document.getElementById(tab.dataset.tab + '-tab');
        if (target) target.classList.remove('hidden');
        const t = tab.dataset.tab;
        if (t === 'users') K.adminPage.loadUsers();
        if (t === 'chats') K.adminPage.loadChats();
        if (t === 'mail') K.adminPage.loadMailAccounts();
        if (t === 'promo') K.adminPage.loadPromoCodes();
        if (t === 'twofa') { K.adminPage.loadTwofaOverview(); K.adminPage.loadTwofaOtps(); K.adminPage.loadEmailVerifications(); K.adminPage.loadQrTokens(); }
        if (t === 'terminal') { K.adminPage.initTerminal(); }
        setTimeout(() => { const ti = $('terminal-input'); if (ti && t === 'terminal') ti.focus(); }, 100);
      });
    });
    if ($('reportStatus')) {
      $('reportStatus').addEventListener('change', function() { K.adminPage.loadReports(this.value); });
    }
  },

  // ── Dashboard ─────────────────────────────────────────

  async loadDashboard() {
    const el = $('stats'); if (!el) return;
    try {
      const d = await K.api.get('/api/admin/dashboard');
      if (d.success && d.data) {
        el.innerHTML = `
          <div class="stat"><div class="stat-value">${d.data.total_users}</div><div class="stat-label">Total Users</div></div>
          <div class="stat"><div class="stat-value">${d.data.users_today}</div><div class="stat-label">Users Today</div></div>
          <div class="stat"><div class="stat-value">${d.data.total_reports}</div><div class="stat-label">Total Reports</div></div>
          <div class="stat"><div class="stat-value">${d.data.pending_reports}</div><div class="stat-label">Pending Reports</div></div>
        `;
      }
    } catch(e) {
      if (el) el.innerHTML = '<div class="stat"><div class="stat-label">Failed to load stats</div></div>';
    }
  },

  // ── Reports ───────────────────────────────────────────

  async loadReports(status) {
    const el = $('reportsBody'); if (!el) return;
    const s = status || ($('reportStatus') ? $('reportStatus').value : 'pending');
    try {
      const d = await K.api.get('/api/admin/reports?status=' + s);
      if (!d.success) { el.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:12px">Failed</td></tr>'; return; }
      const reports = d.data?.reports || [];
      el.innerHTML = reports.map(r => `
        <tr>
          <td>${r.id}</td>
          <td>${esc(r.reporter_username || r.reporter_id)}</td>
          <td>${esc(r.reported_username || r.reported_user_id || '-')}</td>
          <td>${esc((r.reason||'').substring(0,60))}</td>
          <td>${r.created_at ? (safeDate(r.created_at)?.toLocaleDateString() || '') : ''}</td>
          <td>${s === 'pending' ? '<button class="btn btn-sm" onclick="K.adminPage.resolveReport('+r.id+')"><i class="fas fa-check"></i> Resolve</button>' : '<span class="badge badge-resolved">Resolved</span>'}</td>
        </tr>
      `).join('') || '<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:12px">No reports</td></tr>';
    } catch(e) {
      el.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:12px">Error</td></tr>';
    }
  },

  async resolveReport(id) {
    try {
      const d = await K.api.post('/api/admin/reports/' + id + '/resolve');
      if (d.success) this.loadReports();
    } catch(e) { K.ui.toast('Error resolving report', 'error'); }
  },

  // ── Users ─────────────────────────────────────────────

  async loadUsers() {
    try {
      const d = await K.api.get('/api/admin/users');
      if (!d.success) return;
      this._allUsers = d.data?.users || [];
      this._renderUsers(this._allUsers);
    } catch(e) { K.ui.toast('Error loading users', 'error'); }
  },

  _renderUsers(users) {
    const el = $('usersBody'); if (!el) return;
    if ($('userCount')) $('userCount').textContent = users.length;
    el.innerHTML = users.map(u => `
      <tr>
        <td>${u.id}</td>
        <td><span class="avatar-circle">${esc((u.username||'?')[0].toUpperCase())}</span> ${esc(u.username)}</td>
        <td>${esc(u.email||'-')}</td>
        <td>${u.is_admin ? '<span class="badge badge-admin">Admin</span>' : 'No'}</td>
        <td>${u.created_at ? new Date(u.created_at).toLocaleDateString() : ''}</td>
        <td>
          <div class="btn-group">
            <button class="btn btn-sm btn-outline" onclick="K.adminPage.openEdit(${u.id},'${esc(u.username)}','${esc(u.email||'')}')" title="Edit"><i class="fas fa-edit"></i></button>
            <button class="btn btn-sm btn-outline" onclick="K.adminPage.openPassword(${u.id},'${esc(u.username)}')" title="Password"><i class="fas fa-lock"></i></button>
            <button class="btn btn-sm ${u.is_admin ? 'btn-warning' : 'btn-success'}" onclick="K.adminPage.toggleAdmin(${u.id},'${esc(u.username)}',${u.is_admin})" title="${u.is_admin ? 'Demote' : 'Promote'}">${u.is_admin ? '<i class="fas fa-user-minus"></i>' : '<i class="fas fa-user-shield"></i>'}</button>
            <button class="btn btn-sm btn-danger" onclick="K.adminPage.deleteUser(${u.id},'${esc(u.username)}')" title="Delete"><i class="fas fa-trash"></i></button>
          </div>
        </td>
      </tr>
    `).join('') || '<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:12px">No users</td></tr>';
  },

  filterUsers() {
    const q = ($('userSearch') ? $('userSearch').value : '').toLowerCase();
    const filtered = q ? this._allUsers.filter(u => (u.username||'').toLowerCase().includes(q) || (u.email||'').toLowerCase().includes(q)) : this._allUsers;
    this._renderUsers(filtered);
  },

  openAddUser() {
    if ($('addUsername')) $('addUsername').value = '';
    if ($('addEmail')) $('addEmail').value = '';
    if ($('addPassword')) $('addPassword').value = '';
    if ($('addIsAdmin')) $('addIsAdmin').checked = false;
    new bootstrap.Modal($('addUserModal')).show();
  },

  async saveAddUser() {
    const data = {
      username: ($('addUsername')||{}).value || '',
      email: ($('addEmail')||{}).value || '',
      password: ($('addPassword')||{}).value || '',
      is_admin: ($('addIsAdmin')||{}).checked || false
    };
    if (!data.username || data.username.length < USERNAME_MIN_LENGTH) { K.ui.toast('Username must be at least ' + USERNAME_MIN_LENGTH + ' characters', 'error'); return; }
    if (data.password.length < PASSWORD_MIN_LENGTH) { K.ui.toast('Password must be at least ' + PASSWORD_MIN_LENGTH + ' characters', 'error'); return; }
    try {
      const d = await K.api.post('/api/admin/users/create', data);
      if (d.success) { bootstrap.Modal.getInstance($('addUserModal')).hide(); this.loadUsers(); K.ui.toast('User created', 'success'); }
      else { K.ui.toast(d.error?.message || 'Failed', 'error'); }
    } catch(e) { K.ui.toast('Error', 'error'); }
  },

  openEdit(id, username, email) {
    if ($('editUserId')) $('editUserId').value = id;
    if ($('editUsername')) $('editUsername').value = username;
    if ($('editEmail')) $('editEmail').value = email;
    new bootstrap.Modal($('editModal')).show();
  },

  async saveEditUser() {
    const id = ($('editUserId')||{}).value;
    const data = {username: ($('editUsername')||{}).value, email: ($('editEmail')||{}).value};
    try {
      const d = await K.api.post('/api/admin/users/' + id + '/update', data);
      if (d.success) { bootstrap.Modal.getInstance($('editModal')).hide(); this.loadUsers(); K.ui.toast('Saved', 'success'); }
      else { K.ui.toast(d.error?.message || 'Failed', 'error'); }
    } catch(e) { K.ui.toast('Error', 'error'); }
  },

  openPassword(id, username) {
    if ($('passwordUserId')) $('passwordUserId').value = id;
    if ($('passwordUserLabel')) $('passwordUserLabel').textContent = 'Set password for ' + username;
    if ($('newPassword')) $('newPassword').value = '';
    new bootstrap.Modal($('passwordModal')).show();
  },

  async savePassword() {
    const id = ($('passwordUserId')||{}).value;
    const pwd = ($('newPassword')||{}).value;
    if (!pwd || pwd.length < PASSWORD_MIN_LENGTH) { K.ui.toast('Password must be at least ' + PASSWORD_MIN_LENGTH + ' characters', 'error'); return; }
    try {
      const d = await K.api.post('/api/admin/users/' + id + '/set-password', {password: pwd});
      if (d.success) { bootstrap.Modal.getInstance($('passwordModal')).hide(); K.ui.toast('Password updated', 'success'); }
      else { K.ui.toast(d.error?.message || 'Failed', 'error'); }
    } catch(e) { K.ui.toast('Error', 'error'); }
  },

  async toggleAdmin(id, username, isCurrently) {
    try {
      const d = await K.api.post('/api/admin/users/' + id + '/toggle-admin');
      if (d.success) { this.loadUsers(); K.ui.toast((isCurrently ? 'Demoted' : 'Promoted') + ' ' + username, 'success'); }
      else { K.ui.toast(d.error?.message || 'Failed', 'error'); }
    } catch(e) { K.ui.toast('Error', 'error'); }
  },

  async deleteUser(id, username) {
    try {
      const d = await K.api.post('/api/admin/users/' + id + '/delete');
      if (d.success) { this.loadUsers(); K.ui.toast('Deleted ' + username, 'success'); }
      else { K.ui.toast(d.error?.message || 'Failed', 'error'); }
    } catch(e) { K.ui.toast('Error', 'error'); }
  },

  // ── Chats ─────────────────────────────────────────────

  async loadChats() {
    const chatType = ($('chatTypeFilter') ? $('chatTypeFilter').value : '');
    const url = '/api/admin/chats?per_page=' + CHATS_PER_PAGE + (chatType ? '&chat_type=' + chatType : '');
    try {
      const d = await K.api.get(url);
      if (!d.success) return;
      const data = d.data;
      if ($('chatCount')) $('chatCount').textContent = data.total;

      const personal = (data.chats||[]).filter(c => c.chat_type === 'personal').length;
      const groups = (data.chats||[]).filter(c => c.chat_type === 'group').length;
      const channels = (data.chats||[]).filter(c => c.chat_type === 'channel').length;
      const totalMsgs = (data.chats||[]).reduce((sum,c) => sum + c.message_count, 0);
      if ($('chatsStats')) {
        $('chatsStats').innerHTML = `
          <div class="stat"><div class="stat-value">${data.total}</div><div class="stat-label">Total Chats</div></div>
          <div class="stat"><div class="stat-value">${personal}</div><div class="stat-label">Personal</div></div>
          <div class="stat"><div class="stat-value" style="color:var(--yellow)">${groups}</div><div class="stat-label">Groups</div></div>
          <div class="stat"><div class="stat-value" style="color:var(--green)">${channels}</div><div class="stat-label">Channels</div></div>
          <div class="stat"><div class="stat-value">${totalMsgs}</div><div class="stat-label">Messages</div></div>
          <div class="stat"><div class="stat-value" style="font-size:22px">${data.total_pages}p</div><div class="stat-label">Pages</div></div>
        `;
      }

      if ($('chatsBody')) {
        $('chatsBody').innerHTML = (data.chats || []).map(c => `
          <tr>
            <td>${c.id}</td>
            <td>${esc(c.name)}</td>
            <td><span class="badge badge-${c.chat_type}">${c.chat_type}</span></td>
            <td>${c.member_count}</td>
            <td>${c.message_count}</td>
            <td>${c.last_activity ? new Date(c.last_activity).toLocaleString() : '-'}</td>
            <td><button class="btn btn-sm btn-outline" onclick="K.adminPage.openChatDetail(${c.id})" title="View"><i class="fas fa-eye"></i></button></td>
          </tr>
        `).join('') || '<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:12px">No chats</td></tr>';
      }
    } catch(e) { K.ui.toast('Error loading chats', 'error'); }
  },

  async openChatDetail(chatId) {
    this._chatDetailId = chatId;
    this._chatDetailPage = 1;
    try {
      const d = await K.api.get('/api/admin/chats/' + chatId);
      if (!d.success) return;
      const data = d.data;
      if ($('chatDetailTitle')) {
        $('chatDetailTitle').innerHTML = '<i class="fas fa-info-circle"></i> ' + esc(data.name) + ' <span class="badge badge-' + data.chat_type + '" style="font-size:11px">' + data.chat_type + ' #' + data.id + '</span>';
      }

      if ($('chatDetailMeta')) {
        $('chatDetailMeta').innerHTML = '<div style="display:flex;gap:16px;flex-wrap:wrap">'
          + '<span><strong>Type:</strong> ' + data.chat_type + '</span>'
          + '<span><strong>Public:</strong> ' + (data.is_public ? 'Yes' : 'No') + '</span>'
          + '<span><strong>Messages:</strong> ' + data.message_count + '</span>'
          + '<span><strong>Created:</strong> ' + (data.created_at ? new Date(data.created_at).toLocaleDateString() : '-') + '</span>'
          + '</div>'
          + (data.description ? '<div style="margin-top:6px"><strong>Description:</strong> ' + esc(data.description) + '</div>' : '');
      }

      if ($('chatDetailMembers')) {
        $('chatDetailMembers').innerHTML = (data.member_users || []).map(u => '<span class="badge badge-active" style="margin:0 4px 4px 0">' + esc(u.username) + '</span>').join('') || '<span class="text-muted">No members</span>';
      }

      // Show post area for channels
      if ($('chatDetailPostArea')) {
        $('chatDetailPostArea').classList.toggle('hidden', data.chat_type !== 'channel');
      }
      if ($('chatPostInput')) $('chatPostInput').value = '';

      await this._loadChatMessages(chatId, 1);
      new bootstrap.Modal($('chatDetailModal')).show();
    } catch(e) { K.ui.toast('Error loading chat detail', 'error'); }
  },

  async _loadChatMessages(chatId, page) {
    try {
      const d = await K.api.get('/api/admin/chats/' + chatId + '/messages?page=' + page + '&per_page=' + MESSAGES_PER_PAGE);
      if (!d.success) return;
      const data = d.data;
      this._chatDetailPage = page;
      this._chatDetailHasMore = page < data.total_pages;
      if ($('chatDetailLoadMore')) $('chatDetailLoadMore').style.display = this._chatDetailHasMore ? '' : 'none';

      const msgs = (data.messages || []).map(m => {
        const content = m.is_deleted
          ? '<span class="text-muted fst-italic">Deleted</span>'
          : esc((m.content||'').substring(0, CONTENT_PREVIEW_MAX)) + ((m.content||'').length > CONTENT_PREVIEW_MAX ? '...' : '');
        const fileIcon = m.has_attachment ? ' <i class="fas fa-paperclip" title="' + esc(m.file_type||'attachment') + '"></i>' : '';
        return '<div style="padding:8px;margin-bottom:6px;border-radius:8px;background:var(--hover);border-left:3px solid ' + (m.is_deleted ? '#bbb' : 'var(--accent)') + '">'
          + '<div style="font-size:12px"><strong>' + esc(m.sender_username) + '</strong> <span class="text-muted">' + (m.timestamp ? new Date(m.timestamp).toLocaleString() : '') + '</span>' + fileIcon + '</div>'
          + '<div style="margin-left:4px;margin-top:2px;font-size:13px">' + content + '</div>'
          + '<div style="margin-top:4px">' + (m.is_deleted
            ? '<button class="btn btn-sm btn-outline" onclick="K.adminPage._restoreMsg(' + chatId + ',' + m.id + ')" title="Restore"><i class="fas fa-undo"></i> Restore</button>'
            : '<button class="btn btn-sm btn-danger" onclick="K.adminPage._deleteMsg(' + chatId + ',' + m.id + ')" title="Delete"><i class="fas fa-trash"></i> Delete</button>')
          + '</div></div>';
      }).join('');

      const el = $('chatDetailMessages');
      if (page === 1) {
        if (el) el.innerHTML = msgs || '<div class="text-muted" style="text-align:center;padding:12px">No messages</div>';
      } else {
        if (el) el.insertAdjacentHTML('beforeend', msgs);
      }
    } catch(e) { /* silent — messages preview may be empty */ }
  },

  loadMoreChatMessages() {
    if (this._chatDetailId && this._chatDetailHasMore) {
      this._loadChatMessages(this._chatDetailId, this._chatDetailPage + 1);
    }
  },

  async _deleteMsg(chatId, msgId) {
    try {
      const d = await K.api.post('/api/admin/chats/' + chatId + '/messages/' + msgId + '/delete');
      if (d.success) { await this._loadChatMessages(chatId, 1); K.ui.toast('Message deleted', 'success'); }
      else { K.ui.toast(d.error?.message || 'Failed', 'error'); }
    } catch(e) { K.ui.toast('Error', 'error'); }
  },

  async _restoreMsg(chatId, msgId) {
    try {
      const d = await K.api.post('/api/admin/chats/' + chatId + '/messages/' + msgId + '/restore');
      if (d.success) { await this._loadChatMessages(chatId, 1); K.ui.toast('Message restored', 'success'); }
      else { K.ui.toast(d.error?.message || 'Failed', 'error'); }
    } catch(e) { K.ui.toast('Error', 'error'); }
  },

  // ── Channel Creation ───────────────────────────────────

  openCreateChannel() {
    if ($('channelName')) $('channelName').value = '';
    if ($('channelDescription')) $('channelDescription').value = '';
    new bootstrap.Modal($('createChannelModal')).show();
  },

  async saveCreateChannel() {
    const name = ($('channelName')||{}).value || '';
    const description = ($('channelDescription')||{}).value || '';
    if (!name) { K.ui.toast('Channel name required', 'error'); return; }
    try {
      const d = await K.api.post('/api/admin/channels/create', {name, description});
      if (d.success) {
        bootstrap.Modal.getInstance($('createChannelModal')).hide();
        this.loadChats();
        K.ui.toast('Channel "' + name + '" created', 'success');
      } else {
        K.ui.toast(d.error?.message || 'Failed', 'error');
      }
    } catch(e) { K.ui.toast('Error', 'error'); }
  },

  async postToChat() {
    if (!this._chatDetailId) return;
    const content = ($('chatPostInput')||{}).value || '';
    if (!content) { K.ui.toast('Write something to post', 'error'); return; }
    try {
      const d = await K.api.post('/api/admin/chats/' + this._chatDetailId + '/post', {content});
      if (d.success) {
        if ($('chatPostInput')) $('chatPostInput').value = '';
        await this._loadChatMessages(this._chatDetailId, 1);
        K.ui.toast('Posted', 'success');
      } else {
        K.ui.toast(d.error?.message || 'Failed', 'error');
      }
    } catch(e) { K.ui.toast('Error', 'error'); }
  },

  // ── 2FA ───────────────────────────────────────────────

  async loadTwofaOverview() {
    try {
      const d = await K.api.get('/api/admin/2fa/overview');
      if (!d.success || !d.data) return;
      const s = d.data;
      if ($('twofaStats')) {
        $('twofaStats').innerHTML = `
          <div class="stat"><div class="stat-value">${s.total}</div><div class="stat-label">Total OTPs</div></div>
          <div class="stat"><div class="stat-value">${s.active}</div><div class="stat-label">Active</div></div>
          <div class="stat"><div class="stat-value" style="color:var(--yellow)">${s.expired}</div><div class="stat-label">Expired</div></div>
          <div class="stat"><div class="stat-value" style="color:var(--green)">${s.used}</div><div class="stat-label">Used</div></div>
          <div class="stat"><div class="stat-value">${s.sent_today}</div><div class="stat-label">Sent Today</div></div>
        `;
      }
    } catch(e) { K.ui.toast('Error loading 2FA overview', 'error'); }
  },

  async loadTwofaOtps() {
    try {
      const d = await K.api.get('/api/admin/2fa/otps?per_page=' + OTPS_PER_PAGE);
      if (!d.success) return;
      if ($('twofaBody')) {
        $('twofaBody').innerHTML = (d.data?.otps || []).map(o => {
          const cls = o.used ? 'badge-resolved' : o.expired ? 'badge-pending' : 'badge-active';
          const lbl = o.used ? 'Used' : o.expired ? 'Expired' : 'Active';
          return '<tr><td>' + o.id + '</td><td>' + esc(o.username||'User #'+o.user_id) + '</td><td style="font-family:monospace;letter-spacing:1px">' + esc(o.code) + '</td><td>' + (o.created_at ? new Date(o.created_at).toLocaleString() : '-') + '</td><td>' + (o.expires_at ? new Date(o.expires_at).toLocaleString() : '-') + '</td><td><span class="badge ' + cls + '">' + lbl + '</span></td></tr>';
        }).join('') || '<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:12px">No OTPs</td></tr>';
      }
    } catch(e) { K.ui.toast('Error loading OTPs', 'error'); }
  },

  async cleanupOtps() {
    try {
      const d = await K.api.post('/api/admin/2fa/cleanup');
      if (d.success) { this.loadTwofaOverview(); this.loadTwofaOtps(); K.ui.toast('Deleted ' + d.data.deleted + ' OTP codes', 'success'); }
      else { K.ui.toast('Cleanup failed', 'error'); }
    } catch(e) { K.ui.toast('Error', 'error'); }
  },

  // ── Email Verification Codes ───────────────────────────

  async loadEmailVerifications() {
    try {
      const d = await K.api.get('/api/admin/2fa/email-codes?per_page=' + EMAIL_VER_PER_PAGE);
      if (!d.success) return;
      if ($('emailVerBody')) {
        $('emailVerBody').innerHTML = (d.data?.codes || []).map(e => {
          const cls = e.verified ? 'badge-resolved' : e.expired ? 'badge-pending' : 'badge-active';
          const lbl = e.verified ? 'Verified' : e.expired ? 'Expired' : 'Active';
          const user = e.username ? esc(e.username) : e.user_id ? 'User #' + e.user_id : '—';
          return '<tr><td>' + e.id + '</td><td>' + user + '</td><td>' + esc(e.email || '—') + '</td><td style="font-family:monospace;letter-spacing:1px">' + esc(e.token) + '</td><td>' + (e.created_at ? new Date(e.created_at).toLocaleString() : '-') + '</td><td>' + (e.expires_at ? new Date(e.expires_at).toLocaleString() : '-') + '</td><td><span class="badge ' + cls + '">' + lbl + '</span></td></tr>';
        }).join('') || '<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:12px">No verification codes</td></tr>';
      }
    } catch(e) { K.ui.toast('Error loading email verifications', 'error'); }
  },

  async cleanupEmailVerifications() {
    try {
      const d = await K.api.post('/api/admin/2fa/email-codes/cleanup');
      if (d.success) { this.loadEmailVerifications(); K.ui.toast('Deleted ' + d.data.deleted + ' verification codes', 'success'); }
      else { K.ui.toast('Cleanup failed', 'error'); }
    } catch(e) { K.ui.toast('Error', 'error'); }
  },

  // ── QR Login Tokens ─────────────────────────────────────

  async loadQrTokens() {
    try {
      const d = await K.api.get('/api/admin/2fa/qr-tokens?per_page=50');
      if (!d.success) return;
      if ($('qrTokensBody')) {
        $('qrTokensBody').innerHTML = (d.data?.tokens || []).map(t => {
          const cls = t.consumed ? 'badge-resolved' : t.expired ? 'badge-pending' : 'badge-active';
          const lbl = t.consumed ? 'Consumed' : t.expired ? 'Expired' : 'Active';
          const user = t.username ? esc(t.username) : t.user_id ? 'User #' + t.user_id : '—';
          const auth = t.authorized_by ? esc(t.authorized_by) : '—';
          return '<tr><td>' + t.id + '</td><td>' + user + '</td><td style="font-family:monospace;letter-spacing:1px;font-size:12px">' + esc(t.token?.substring(0, 16) + '...') + '</td><td>' + (t.created_at ? new Date(t.created_at).toLocaleString() : '-') + '</td><td>' + (t.expires_at ? new Date(t.expires_at).toLocaleString() : '-') + '</td><td>' + auth + '</td><td><span class="badge ' + cls + '">' + lbl + '</span></td></tr>';
        }).join('') || '<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:12px">No QR tokens</td></tr>';
      }
    } catch(e) { K.ui.toast('Error loading QR tokens', 'error'); }
  },

  async cleanupQrTokens() {
    try {
      const d = await K.api.post('/api/admin/2fa/qr-tokens/cleanup');
      if (d.success) { this.loadQrTokens(); K.ui.toast('Deleted ' + d.data.deleted + ' QR tokens', 'success'); }
      else { K.ui.toast('Cleanup failed', 'error'); }
    } catch(e) { K.ui.toast('Error', 'error'); }
  },

  // ── Mail Accounts ──────────────────────────────────────

  async loadMailAccounts() {
    try {
      const d = await K.api.get('/api/admin/mail/accounts');
      if ($('mailBody')) {
        $('mailBody').innerHTML = (d.accounts || []).map(a => `
          <tr>
            <td>${esc(a.email)}</td>
            <td>
              <div class="btn-group">
                <button class="btn btn-sm btn-warning" onclick="K.adminPage.openResetMailPassword('${esc(a.email)}')" title="Reset Password"><i class="fas fa-key"></i></button>
                <button class="btn btn-sm btn-danger" onclick="K.adminPage.deleteMailAccount('${esc(a.email)}')" title="Delete"><i class="fas fa-trash"></i></button>
              </div>
            </td>
          </tr>
        `).join('') || '<tr><td colspan="2" style="text-align:center;color:var(--muted);padding:12px">No mail accounts</td></tr>';
      }
    } catch(e) {
      if ($('mailBody')) $('mailBody').innerHTML = '<tr><td colspan="2" style="text-align:center;color:var(--muted);padding:12px">Failed to load</td></tr>';
    }
  },

  openAddMailAccount() {
    if ($('mailEmail')) $('mailEmail').value = '';
    if ($('mailPassword')) $('mailPassword').value = '';
    new bootstrap.Modal($('addMailModal')).show();
  },

  async saveMailAccount() {
    const email = ($('mailEmail')||{}).value || '';
    const password = ($('mailPassword')||{}).value || '';
    if (!email || !password) { K.ui.toast('Email and password required', 'error'); return; }
    try {
      const d = await K.api.post('/api/admin/mail/accounts', {email, password});
      if (d.success) { bootstrap.Modal.getInstance($('addMailModal')).hide(); this.loadMailAccounts(); K.ui.toast('Account created', 'success'); }
      else { K.ui.toast(d.error?.message || d.error || 'Failed', 'error'); }
    } catch(e) { K.ui.toast('Error', 'error'); }
  },

  openResetMailPassword(email) {
    if ($('resetMailEmail')) $('resetMailEmail').textContent = email;
    if ($('resetMailPassword')) $('resetMailPassword').value = '';
    new bootstrap.Modal($('resetMailPasswordModal')).show();
  },

  async saveResetMailPassword() {
    const email = ($('resetMailEmail')||{}).textContent || '';
    const password = ($('resetMailPassword')||{}).value || '';
    if (!password) { K.ui.toast('Password required', 'error'); return; }
    try {
      const d = await K.api.post('/api/admin/mail/accounts/' + encodeURIComponent(email) + '/password', {password});
      if (d.success) { bootstrap.Modal.getInstance($('resetMailPasswordModal')).hide(); K.ui.toast('Password reset', 'success'); }
      else { K.ui.toast(d.error?.message || d.error || 'Failed', 'error'); }
    } catch(e) { K.ui.toast('Error', 'error'); }
  },

  async deleteMailAccount(email) {
    if (!confirm('Delete mail account ' + email + '?')) return;
    try {
      const d = await K.api.delete('/api/admin/mail/accounts/' + encodeURIComponent(email));
      if (d.success) { this.loadMailAccounts(); K.ui.toast('Deleted', 'success'); }
      else { K.ui.toast(d.error?.message || d.error || 'Failed', 'error'); }
    } catch(e) { K.ui.toast('Error', 'error'); }
  },

  // ── Promo Codes ─────────────────────────────────────────

  async loadPromoCodes() {
    try {
      const d = await K.api.get('/api/admin/promo/list');
      if (d.success && d.promo_codes) {
        if ($('promoBody')) {
          $('promoBody').innerHTML = d.promo_codes.map(p => `
            <tr>
              <td style="font-family:monospace;font-weight:bold">${esc(p.code)}</td>
              <td>${p.duration_days}d</td>
              <td>${p.used_count} / ${p.max_uses}</td>
              <td><span class="badge ${p.active ? 'badge-active' : 'badge-pending'}">${p.active ? 'Active' : 'Disabled'}</span></td>
              <td>${p.created_at ? new Date(p.created_at).toLocaleDateString() : '-'}</td>
              <td>${esc(p.created_by || '-')}</td>
              <td>
                <button class="btn btn-sm ${p.active ? 'btn-warning' : 'btn-success'}" onclick="K.adminPage.togglePromo('${esc(p.code)}')" title="${p.active ? 'Disable' : 'Enable'}">
                  ${p.active ? '<i class="fas fa-pause"></i>' : '<i class="fas fa-play"></i>'}
                </button>
              </td>
            </tr>
          `).join('') || '<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:12px">No promo codes</td></tr>';
        }
      }
    } catch(e) { K.ui.toast('Error loading promo codes', 'error'); }
  },

  openGeneratePromo() {
    if ($('promoDuration')) $('promoDuration').value = '30';
    if ($('promoMaxUses')) $('promoMaxUses').value = '1';
    if ($('promoCustomCode')) $('promoCustomCode').value = '';
    new bootstrap.Modal($('generatePromoModal')).show();
  },

  async saveGeneratePromo() {
    const data = {
      duration_days: parseInt(($('promoDuration')||{}).value, 10) || 30,
      max_uses: parseInt(($('promoMaxUses')||{}).value, 10) || 1,
      custom_code: ($('promoCustomCode')||{}).value || ''
    };
    try {
      const d = await K.api.post('/api/admin/promo/generate', data);
      if (d.success) { bootstrap.Modal.getInstance($('generatePromoModal')).hide(); this.loadPromoCodes(); K.ui.toast('Code generated: ' + d.data.code, 'success'); }
      else { K.ui.toast(d.error?.message || 'Failed', 'error'); }
    } catch(e) { K.ui.toast('Error', 'error'); }
  },

  async togglePromo(code) {
    try {
      const d = await K.api.post('/api/admin/promo/toggle/' + encodeURIComponent(code));
      if (d.success) { this.loadPromoCodes(); K.ui.toast('Toggled', 'success'); }
      else { K.ui.toast(d.error?.message || 'Failed', 'error'); }
    } catch(e) { K.ui.toast('Error', 'error'); }
  },

  // ── Terminal ─────────────────────────────────────────

  _terminalHistory: [],
  _terminalHistoryIdx: -1,
  _terminalInitialized: false,

  initTerminal() {
    if (this._terminalInitialized) return;
    this._terminalInitialized = true;
    const input = $('terminal-input');
    const output = $('terminal-output');
    const clear = $('terminal-clear');
    if (!input || !output) return;

    const append = (html) => { output.insertAdjacentHTML('beforeend', html); output.scrollTop = output.scrollHeight; };

    append('<div class="t-muted">Kiselgram Admin Terminal — type <span class="t-prompt">help</span> for available commands</div>');
    append('<div class="t-muted" style="margin-bottom:6px">&#8203;</div>');

    const runCmd = async () => {
      const cmd = input.value.trim();
      input.value = '';
      if (!cmd) return;
      this._terminalHistory.push(cmd);
      this._terminalHistoryIdx = this._terminalHistory.length;
      append('<div><span class="t-prompt">$</span> ' + esc(cmd) + '</div>');

      if (cmd === 'help') {
        append('<div class="t-info">Available commands:</div>');
        append('<div class="t-muted">  Any shell command (ls, df, ps, cat, whoami, etc.)</div>');
        append('<div class="t-muted">  help     — Show this help</div>');
        append('<div class="t-muted">  clear    — Clear terminal</div>');
        append('<div class="t-muted" style="margin-bottom:4px">&#8203;</div>');
        return;
      }

      if (cmd === 'clear') {
        output.innerHTML = '';
        append('<div class="t-muted">Kiselgram Admin Terminal — type <span class="t-prompt">help</span> for available commands</div>');
        append('<div class="t-muted" style="margin-bottom:6px">&#8203;</div>');
        return;
      }

      try {
        const d = await K.api.post('/api/admin/terminal/exec', { command: cmd });
        if (d.success && d.data) {
          if (d.data.stdout) append('<div class="t-stdout">' + esc(d.data.stdout) + '</div>');
          if (d.data.stderr) append('<div class="t-stderr">' + esc(d.data.stderr) + '</div>');
          append('<div class="' + (d.data.return_code === 0 ? 't-success' : 't-error') + '" style="margin-bottom:2px">Exit code: ' + d.data.return_code + '</div>');
        } else {
          append('<div class="t-error">Error: ' + esc((d.error && d.error.message) || 'Unknown error') + '</div>');
        }
      } catch(e) {
        append('<div class="t-error">Request failed: ' + esc(e.message || 'Network error') + '</div>');
      }
    };

    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') runCmd();
      else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (this._terminalHistoryIdx > 0) {
          this._terminalHistoryIdx--;
          input.value = this._terminalHistory[this._terminalHistoryIdx];
        }
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (this._terminalHistoryIdx < this._terminalHistory.length - 1) {
          this._terminalHistoryIdx++;
          input.value = this._terminalHistory[this._terminalHistoryIdx];
        } else {
          this._terminalHistoryIdx = this._terminalHistory.length;
          input.value = '';
        }
      }
    });

    if (clear) {
      clear.addEventListener('click', () => {
        output.innerHTML = '';
        append('<div class="t-muted">Kiselgram Admin Terminal — type <span class="t-prompt">help</span> for available commands</div>');
        append('<div class="t-muted" style="margin-bottom:6px">&#8203;</div>');
        input.focus();
      });
    }
  }
};
