const MOBILE_BREAKPOINT = 768;
const CONSECUTIVE_MSG_GAP = 300000;
const MAX_INPUT_HEIGHT = 100;
const TYPING_DEBOUNCE = 500;
const TYPING_COOLDOWN = 4000;

K.chat = {
  _initActions_ran: false,
  _initActions() {
    if (K.chat._initActions_ran) return;
    K.chat._initActions_ran = true;
    document.getElementById('messagesContainer')?.addEventListener('click', (e) => {
      const code = e.target.closest('.k-copy-code');
      if (code) {
        const text = code.textContent;
        navigator.clipboard?.writeText(text).then(() => K.ui.toast('Copied', 'success')).catch(() => {});
      }
    });
  },
  async loadList() {
    const c = $('chatList'); if (!c) return;
    c.innerHTML = K.ui.loader();
    try {
      const d = await K.api.get(V2 + '/chat_list');
      if (d.success) K.chat.renderList(d.data.chats);
      else c.innerHTML = '<div class="k-empty"><p>Failed to load</p></div>';
    } catch(e) { c.innerHTML = '<div class="k-empty"><i class="fas fa-wifi-slash"></i><h3>Connection error</h3><p onclick="K.chat.loadList()" style="color:var(--accent-blue);cursor:pointer">Tap to retry</p></div>'; }
  },
  renderList(chats) {
    const c = $('chatList'); if (!c) return;
    K.state.chats = chats;
    if (!chats || !chats.length) {
      c.innerHTML = `<div class="k-empty"><i class="fas fa-comment"></i><h3>No chats yet</h3><p>Search users to start chatting</p><button class="k-btn k-btn-primary" style="margin-top:16px" onclick="K.chat.startNew()"><i class="fas fa-plus"></i> New Chat</button></div>`;
      return;
    }
    const af = K.state.activeFolder;
    let filtered = chats;
    if (af) {
      const f = (K.state.folders||[]).find(x => x.name === af);
      if (f?.chats?.length) {
        const ids = new Set(f.chats.map(x => x.type+':'+x.id));
        filtered = chats.filter(chat => {
          const cid = chat.chat_type === 'personal' ? (chat.peer?.user_id || chat.peer?.id) : (chat.group?.group_id || chat.channel?.channel_id);
          return ids.has(chat.chat_type+':'+cid);
        });
      }
    }
    const pinned = K.state.pinned || [];
    const sorted = [...filtered].sort((a,b) => {
      const aId = a.chat_type === 'personal' ? (a.peer?.user_id || a.peer?.id) : (a.group?.group_id || a.channel?.channel_id);
      const bId = b.chat_type === 'personal' ? (b.peer?.user_id || b.peer?.id) : (b.group?.group_id || b.channel?.channel_id);
      const aP = pinned.includes(a.chat_type+':'+aId);
      const bP = pinned.includes(b.chat_type+':'+bId);
      if (aP && !bP) return -1;
      if (!aP && bP) return 1;
      return 0;
    });
    c.innerHTML = sorted.map(chat => {
      const isSaved = chat.is_saved;
      const id = isSaved ? (K.state.user?.user_id || chat.peer?.user_id) : (chat.chat_type === 'personal' ? (chat.peer?.user_id || chat.peer?.id) : (chat.group?.group_id || chat.channel?.channel_id));
      const name = isSaved ? 'Saved Messages' : (chat.peer?.display_name || chat.peer?.username || chat.group?.name || chat.channel?.name || 'Unknown');
      const statusEmoji = isSaved ? '' : (chat.peer?.status_emoji || '');
      const isPremium = chat.peer?.is_premium;
      const avatar = isSaved ? null : (chat.peer?.avatar_url || chat.group?.avatar_url || chat.channel?.avatar_url);
      const type = isSaved ? 'personal' : chat.chat_type;
      const isActive = K.state.activeChat?.type === type && K.state.activeChat?.id === id;
      const isPinned = K.state.pinned?.includes(type+':'+id);
      const showIds = K.settings?._showPeerIds?.();
      const idSuffix = showIds ? ` <span class="k-peer-id" title="Peer ID">${id}</span>` : '';
      let preview = '';
      if (chat.last_message) {
        const lm = chat.last_message;
        if (lm.file_type === 'image' || lm.file_name?.match(/\.(jpg|jpeg|png|gif|webp)/i)) preview = '<i class="fas fa-camera"></i> Photo';
        else if (lm.file_type === 'video') preview = '<i class="fas fa-video"></i> Video';
        else if (lm.file_type === 'voice' || lm.file_type === 'audio') preview = '<i class="fas fa-microphone"></i> Voice';
        else preview = esc((lm.content||'').substring(0,80));
      }
      const time = chat.last_message?.timestamp ? fmtTime(chat.last_message.timestamp) : '';
      const unread = chat.unread_count || 0;
      const isOnline = !isSaved && type === 'personal' && chat.peer?.is_online;
      return `<div class="k-chat-item ${isActive?'active':''} ${isPinned?'pinned':''}" onclick="K.chat.open('${type}',${id})" data-type="${type}" data-id="${id}">
        <div class="k-chat-avatar personal">${isSaved ? '<i class="fas fa-bookmark" style="font-size:20px;color:var(--accent-blue)"></i>' : K.ui.avatar(name, avatar, chat.peer?.is_bot)}${isOnline ? '<span class="k-online-dot"></span>' : ''}</div>
        <div class="k-chat-info">
          <div class="k-chat-name-row"><span class="k-chat-name">${esc(name)}${idSuffix}${isPremium ? (statusEmoji === '⭐' ? ' <img src="/static/img/img.png" alt="" style="width:16px;height:16px;vertical-align:middle;display:inline-block">' : ' ' + esc(statusEmoji)) : (statusEmoji ? ' ' + esc(statusEmoji) : '')}${isPinned ? ' <i class="fas fa-thumbtack" style="font-size:10px;color:var(--accent-blue);transform:rotate(45deg);margin-left:2px"></i>' : ''}</span><span class="k-chat-time">${time}</span></div>
          <div class="k-chat-preview"><span>${preview}</span>${unread ? `<span class="k-unread">${unread>99?'99+':unread}</span>` : ''}</div>
        </div>
      </div>`;
    }).join('');
  },
  startNew() {
    K.modals.show('newChat');
    setTimeout(() => $('newChatSearch')?.focus(), 100);
  },
  async open(type, id) {
    K.state.activeChat = { type, id };
    K.state.saveURL();
    K.chat._lastMsgId = {};
    K.chat.reply.cancel();
    const _sb = $('sidebar'), _mb = $('menuBtn'), _bd = $('sidebarBackdrop'); _sb?.classList.remove('open'); _mb?.classList.remove('active'); _bd?.classList.remove('open');
    document.querySelectorAll('.k-chat-item').forEach(i => i.classList.remove('active'));
    const sel = document.querySelector(`.k-chat-item[data-type="${type}"][data-id="${id}"]`);
    if (sel) sel.classList.add('active');
    $('chatPlaceholder')?.classList.add('k-hidden');
    $('chatHeader')?.classList.remove('k-hidden');
    $('messagesContainer')?.classList.remove('k-hidden');
    $('inputArea')?.classList.remove('k-hidden');
    $('replyBar')?.classList.remove('k-hidden');
    $('typingIndicator')?.classList.remove('k-hidden');
    $('chatView')?.classList.add('active');
    document.querySelectorAll('.k-panel').forEach(p => p.classList.remove('active'));
    if (window.innerWidth > MOBILE_BREAKPOINT) { const cp = $('panel-chats'); if (cp) cp.classList.add('active'); }
    if ($('chatMenu')) $('chatMenu').style.display = 'none';
    if ($('chatInfo')) $('chatInfo').style.display = 'none';
    await K.chat.loadHeader(type, id);
    await K.chat.loadMessages(type, id);
    $('messageInput').focus();
    if (type === 'personal') { try {
      const rr = localStorage.getItem('k_read_receipts');
      if (rr !== '0') { await K.api.post(V2 + `/mark_read/${id}`); }
      K.chat.loadList(); } catch(_) {} }
  },
  headerClick() {
    if (!K.state.activeChat || K.state.activeChat.type !== 'personal') return;
    const id = K.state.activeChat.id;
    if (id === K.state.user?.user_id) {
      K.modals.show('editProfile');
    } else {
      K.modals.viewProfile(id);
    }
  },
  close() {
    K.state.activeChat = null;
    $('chatView').classList.remove('active');
    $('chatPlaceholder')?.classList.remove('k-hidden');
    $('chatHeader')?.classList.add('k-hidden');
    $('messagesContainer')?.classList.add('k-hidden');
    $('inputArea')?.classList.add('k-hidden');
    $('replyBar')?.classList.add('k-hidden');
    $('typingIndicator')?.classList.add('k-hidden');
    if (window.innerWidth <= MOBILE_BREAKPOINT) $('chatView').classList.remove('active');
  },
  async loadHeader(type, id) {
    const nameEl = $('chatName'), statusEl = $('chatStatus'), avatarEl = $('chatAvatar');
    const cb = $('callBtn'); if (cb) cb.style.display = 'none';
    const wb = $('webappBtn'); if (wb) wb.style.display = 'none';
    const isSelf = id === K.state.user?.user_id;
    const showIds = K.settings?._showPeerIds?.();
    if (isSelf) {
      if (nameEl) nameEl.textContent = 'Saved Messages' + (showIds ? ' #' + id : '');
      if (avatarEl) { avatarEl.innerHTML = '<i class="fas fa-bookmark" style="font-size:20px;color:var(--accent-blue)"></i>'; avatarEl.className = 'k-chat-avatar-sm'; }
      if (statusEl) { statusEl.textContent = ''; statusEl.className = 'k-chat-header-status'; }
      return;
    }
    const chat = K.state.chats?.find(c => {
      if (type === 'personal') return (c.peer?.user_id || c.peer?.id) === id;
      if (type === 'group') return c.group?.group_id === id;
      if (type === 'channel') return c.channel?.channel_id === id;
    });
    if (chat) {
      const peer = chat.peer || chat.group || chat.channel;
      if (peer) {
        const pname = peer.display_name || peer.name || peer.username || 'User #'+id;
        const emoji = peer.status_emoji || '';
        const isP = peer.is_premium;
        if (nameEl) nameEl.innerHTML = esc(pname) + (showIds ? ` <span class="k-peer-id" title="Peer ID">${id}</span>` : '') + (isP && (!emoji || emoji === '⭐') ? '<img src="/static/img/img.png" alt="" style="width:16px;height:16px;vertical-align:middle;display:inline-block;margin-left:3px">' : (emoji ? ' ' + esc(emoji) : ''));
        if (avatarEl) { avatarEl.innerHTML = K.ui.avatar(pname, peer.avatar_url, peer.is_bot); avatarEl.className = 'k-chat-avatar-sm'+(type==='group'?' group':type==='channel'?' channel':''); }
        if (statusEl) { statusEl.textContent = peer.is_online ? 'online' : ''; statusEl.className = 'k-chat-header-status'+(peer.is_online?' online':''); }
        if (cb && type === 'personal') cb.style.display = 'flex';
        if (wb && peer.is_bot && peer.bot_webapp_url) { wb.style.display = 'flex'; wb.dataset.url = peer.bot_webapp_url; }
        return;
      }
    }
    try {
      if (type === 'personal') {
        const d = await K.api.get(V2 + '/users?search=' + encodeURIComponent('user' + id));
        if (d.success) {
          const users = d.data?.users || [];
          const u = users.find(x => x.user_id === id);
          if (u) {
            const emoji = u.status_emoji || '';
            const isP = u.is_premium;
            if (nameEl) nameEl.innerHTML = esc(u.display_name || u.username) + (showIds ? ` <span class="k-peer-id" title="Peer ID">${id}</span>` : '') + (isP && (!emoji || emoji === '⭐') ? '<img src="/static/img/img.png" alt="" style="width:16px;height:16px;vertical-align:middle;display:inline-block;margin-left:3px">' : (emoji ? ' ' + esc(emoji) : ''));
            if (avatarEl) { avatarEl.className = 'k-chat-avatar-sm'; avatarEl.innerHTML = K.ui.avatar(u.display_name||u.username, u.avatar_url, u.is_bot); }
            if (statusEl) { statusEl.textContent = u.is_online ? 'online' : ''; statusEl.className = 'k-chat-header-status'+(u.is_online?' online':''); }
            if (wb && u.is_bot && u.bot_webapp_url) { wb.style.display = 'flex'; wb.dataset.url = u.bot_webapp_url; }
          }
          if (cb) cb.style.display = 'flex';
        }
        if (nameEl && !nameEl.textContent) nameEl.textContent = 'User #'+id;
      } else if (type === 'group') {
        const d = await K.api.get(V2 + `/groups/${id}`);
        if (d.success && d.data) {
          const g = d.data;
          if (nameEl) nameEl.textContent = g.name;
          if (avatarEl) { avatarEl.className = 'k-chat-avatar-sm group'; avatarEl.innerHTML = K.ui.avatar(g.name, g.avatar_url); }
          if (statusEl) { statusEl.textContent = (g.member_count||0)+' members'; statusEl.className = 'k-chat-header-status'; }
        }
      } else if (type === 'channel') {
        const d = await K.api.get(V2 + `/channels/${id}`);
        if (d.success && d.data) {
          const ch = d.data;
          if (nameEl) nameEl.textContent = ch.name;
          if (avatarEl) { avatarEl.className = 'k-chat-avatar-sm channel'; avatarEl.innerHTML = K.ui.avatar(ch.name, ch.avatar_url); }
          if (statusEl) { statusEl.textContent = (ch.subscriber_count||0)+' subscribers'; statusEl.className = 'k-chat-header-status'; }
        }
      }
    } catch(e) { K.ui.toast('Failed to load chat info', 'error'); }
  },
  async loadMessages(type, id, append=false) {
    const mc = $('messagesContainer'); if (!mc) return;
    const after = append ? (K.chat._cursor || 0) : 0;
    if (!append) { K.chat._cursor = 0; K.chat._hasMore = true; }
    if (!K.chat._hasMore && append) return;
    const key = type+':'+id;
    const firstLoad = !K.chat._lastMsgId?.[key];
    if (!append && firstLoad) mc.innerHTML = K.ui.loader();
    try {
      let url;
      if (type === 'personal') url = V2 + `/messages/${id}`;
      else if (type === 'group') url = V2 + `/group_messages/${id}`;
      else if (type === 'channel') url = V2 + `/channel_messages/${id}`;
      const d = await K.api.get(url + `?after=${after}&limit=50`);
      const msgs = (d.data && d.data.messages) || d.messages || [];
      const pag = d.data?.pagination;
      K.chat._hasMore = pag?.has_more ?? false;
      if (pag?.next_cursor) K.chat._cursor = pag.next_cursor;
      if (append) {
        if (!msgs.length) { K.chat._hasMore = false; return; }
        const prevScroll = mc.scrollHeight;
        mc.insertAdjacentHTML('afterbegin', msgs.map(m => K.chat.renderMessage(m)).join(''));
        mc.scrollTop = mc.scrollHeight - prevScroll;
      } else {
        const newestId = msgs.length ? (msgs[msgs.length-1].id || msgs[msgs.length-1].message_id) : null;
        if (!firstLoad && newestId && newestId === K.chat._lastMsgId?.[key]) { return; }
        K.chat._lastMsgId = {...K.chat._lastMsgId, [key]: newestId};
        mc.innerHTML = '';
        K.chat.renderMessages(msgs);
        if (K.chat._hasMore) mc.insertAdjacentHTML('afterend', '<div id="loadMoreTrigger" style="text-align:center;padding:8px"><button class="k-btn k-btn-secondary" onclick="K.chat.loadMore()">Load older messages</button></div>');
      }
    } catch(e) { if (!append && firstLoad) mc.innerHTML = '<div class="k-empty"><i class="fas fa-exclamation-triangle"></i><h3>Error</h3><p onclick="K.chat.loadMessages(\''+type+'\','+id+')" style="color:var(--accent-blue);cursor:pointer">Tap to retry</p></div>'; }
  },
  async loadMore() {
    if (!K.state.activeChat) return;
    const lm = $('loadMoreTrigger'); if (lm) lm.remove();
    await K.chat.loadMessages(K.state.activeChat.type, K.state.activeChat.id, true);
  },
  renderMessages(msgs) {
    const mc = $('messagesContainer'); if (!mc) return;
    let html = '', lastDate = '', lastSender = null, lastTime = null;
    const uid = K.state.user?.user_id;
    for (const m of msgs) {
      const d = safeDate(m.timestamp) || new Date();
      const ds = d.toLocaleDateString();
      if (ds !== lastDate) {
        lastDate = ds; lastSender = null; lastTime = null;
        const today = new Date(); const y = new Date(today); y.setDate(y.getDate()-1);
        let label = d.toLocaleDateString(undefined, {month:'long', day:'numeric'});
        if (ds === today.toLocaleDateString()) label = 'Today';
        else if (ds === y.toLocaleDateString()) label = 'Yesterday';
        html += `<div class="k-date-divider"><span>${label}</span></div>`;
      }
      const isOwn = m.sender_id === uid || m.is_own;
      const consecutive = m.sender_id === lastSender && lastTime && (safeDate(m.timestamp)?.getTime()||0) - (safeDate(lastTime)?.getTime()||0) < CONSECUTIVE_MSG_GAP;
      html += K.chat._messageHtml(m, isOwn, consecutive);
      lastSender = m.sender_id; lastTime = m.timestamp;
    }
    mc.innerHTML = html || `<div class="k-empty" style="padding:40px 20px"><i class="fas fa-comments"></i><h3>No messages yet</h3><p>Say hello!</p></div>`;
    K.chat._scrollToBottom();
  },
  _messageHtml(m, isOwn, consecutive) {
    const time = m.timestamp ? (safeDate(m.timestamp)?.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}) || '') : '';
    const mid = m.message_id || m.id;
    const isRead = m.is_read === true || m.is_read === 1;
    const statusIcon = !isOwn ? '' : (isRead ? '<i class="fas fa-check-double" style="font-size:10px;color:var(--accent-blue)"></i>' : '<i class="fas fa-check" style="font-size:10px"></i>');
    let att = '';
    const fileUrl = m.file_url || m.file_path || '';
    const fileName = m.file_name || '';
    const fileType = m.file_type || '';
    if (m.file_path || m.file_type || m.file_name) {
      const isImg = fileType === 'image' || fileName.match(/\.(jpg|jpeg|png|gif|webp|bmp|svg)$/i);
      const isVid = fileType === 'video' || fileName.match(/\.(mp4|webm|avi|mov|mkv)$/i);
      const isAud = fileType === 'audio' || fileType === 'voice' || fileName.match(/\.(mp3|wav|m4a|ogg)$/i);
      if (isImg && fileUrl) {
        att = `<div class="k-msg-attachment"><img src="${esc(fileUrl)}" loading="lazy" onclick="K.features.showMediaViewer([{file_url:'${esc(fileUrl)}',file_type:'image',file_name:'${esc(fileName||'')}'}],0)"></div>`;
      } else if (isVid && fileUrl) {
        att = `<div class="k-msg-attachment"><video src="${esc(fileUrl)}" controls preload="metadata" style="max-width:260px;max-height:200px;border-radius:12px"></video></div>`;
      } else if (isAud && fileUrl) {
        att = `<div class="k-msg-attachment k-audio-msg" onclick="event.stopPropagation();K.music.playUrl('${esc(fileUrl)}','${esc(fileName||'Audio')}','${esc(m.sender_username||'')}',${m.message_id||m.id})"><i class="fas fa-music"></i><span class="k-audio-name">${esc(fileName||'Audio message')}</span><span class="k-audio-play"><i class="fas fa-play"></i></span><button class="k-icon-btn" onclick="event.stopPropagation();K.music.likeMusic(${m.message_id||m.id})" title="Add to My Music" style="font-size:14px;width:28px;height:28px;margin-left:auto;flex-shrink:0"><i class="fas fa-heart"></i></button></div>`;
      } else if (fileUrl) {
        const icon = fileName.match(/\.pdf$/i) ? 'fa-file-pdf' : fileName.match(/\.(doc|docx)$/i) ? 'fa-file-word' : 'fa-file';
        att = `<div class="k-msg-file"><i class="fas ${icon}"></i> <a href="${esc(fileUrl)}" target="_blank" rel="noopener">${esc(fileName||'File')}</a></div>`;
      }
    }
    let reply = '';
    if (m.reply_to_id) reply = `<div class="k-msg-reply"><div style="font-weight:600;font-size:11px">↩ Reply</div>${esc(m.reply_to_content||'')}</div>`;
    const showIds = K.settings?._showPeerIds?.();
    let sName = '';
    if (!isOwn && !consecutive) {
      const nm = esc(m.sender_username||m.sender_name);
      const idB = showIds && m.sender_id ? ` <span class="k-peer-id" title="User ID">#${m.sender_id}</span>` : '';
      if (nm || idB) sName = `<div class="k-msg-sender">${nm}${idB}</div>`;
    }
    let reactions = '';
    let pollHtml = '';
    if (m.poll) {
      pollHtml = K.features?.renderPoll ? K.features.renderPoll(m.poll, mid) : '<div class="k-poll-placeholder">Poll</div>';
    }
    if (m.reactions && typeof m.reactions === 'object') {
      const entries = Object.entries(m.reactions);
      if (entries.length) {
        reactions = `<div class="k-msg-reactions">${entries.map(([t,c]) => `<span class="k-reaction-badge" onclick="event.stopPropagation();K.chat.react(${mid},'${esc(t)}')">${esc(t)} ${c}</span>`).join('')}</div>`;
      }
    }
    const cls = isOwn ? 'outgoing' : 'incoming';
    const content = m.content ? `<div class="k-msg-text">${K.markdown.render(m.content)}</div>` : '';
    let emojiHtml = '';
    if (m.emoji_file) {
      const size = m.emoji_size || 96;
      const count = m.emoji_count || 1;
      const url = m.emoji_url || `/uploads/animated_emojis/${m.emoji_file}`;
      emojiHtml = `<div class="k-msg-emoji" style="width:${size}px;height:${size}px"><img src="${esc(url)}" alt="emoji" style="width:${size}px;height:${size}px" onclick="K.features.showMediaViewer([{file_url:'${esc(url)}',file_type:'image',file_name:'emoji'}],0)"></div>`;
      if (count > 1) emojiHtml = emojiHtml.replace('</div>', `<span class="k-emoji-count">${count}</span></div>`);
    }
    return `<div class="k-msg ${cls}" data-msg-id="${mid}">
      ${sName}${reply}${emojiHtml}${att}${content ? `<div class="k-msg-bubble">${content}<div class="k-msg-meta">${time} ${statusIcon}</div></div>` : (att || emojiHtml ? `<div class="k-msg-bubble"><div class="k-msg-meta">${time} ${statusIcon}</div></div>` : '')}${pollHtml}${reactions}
      <div class="k-msg-actions">
        <button class="k-msg-action-btn" onclick="K.chat.reply.set(${mid},'${esc(K.markdown.strip(m.content||'').substring(0,40))}')" title="Reply"><i class="fas fa-reply"></i></button>
        <button class="k-msg-action-btn" onclick="K.features.showForwardDialog(${mid})" title="Forward"><i class="fas fa-forward"></i></button>
        <button class="k-msg-action-btn" onclick="K.chat.react(${mid})" title="React"><i class="fas fa-smile"></i></button>
        <button class="k-msg-action-btn" onclick="K.chat.copy(${mid})" title="Copy"><i class="fas fa-copy"></i></button>
        ${!isOwn && m.content ? `<button class="k-msg-action-btn k-translate-btn" onclick="K.features.translateMessage(${mid},'${esc(m.content.substring(0,200))}')" title="Translate"><i class="fas fa-language"></i></button>` : ''}
        ${isOwn ? `<button class="k-msg-action-btn" onclick="K.chat.edit(${mid})" title="Edit"><i class="fas fa-pen"></i></button>
        <button class="k-msg-action-btn" onclick="K.chat.delete(${mid})" title="Delete" style="color:var(--accent-red)"><i class="fas fa-trash"></i></button>
        <button class="k-msg-action-btn" onclick="K.features.showReadReceipts(${mid})" title="Read receipts"><i class="fas fa-check-double"></i></button>` : ''}
      </div>
    </div>`;
  },
  renderMessage(m) { return K.chat._messageHtml(m, m.sender_id === K.state.user?.user_id || m.is_own, false); },
  _scrollToBottom() { const mc = $('messagesContainer'); if (mc) { mc.scrollTop = mc.scrollHeight; } },
  async send() {
    const input = $('messageInput'); if (!input) return;
    const content = input.value.trim();
    const selEmoji = K.state.emoji || null;
    if ((!content && !selEmoji) || !K.state.activeChat) return;
    const { type, id } = K.state.activeChat;
    let payload = { content };
    if (selEmoji) {
      payload.emoji_file = selEmoji.file;
      payload.emoji = selEmoji.emoji || '';
      payload.size = selEmoji.size || 96;
      payload.count = selEmoji.count || 1;
    }
    let url;
    if (type === 'personal') { url = V2 + '/send_message'; payload.receiver_id = id; }
    else if (type === 'group') { url = V2 + '/send_group_message'; payload.group_id = id; }
    else if (type === 'channel') { url = V2 + '/send_channel_message'; payload.channel_id = id; }
    if (K.state.replyTo) { payload.reply_to_id = K.state.replyTo; K.chat.reply.cancel(); }
    input.value = ''; input.style.height = 'auto'; K.chat.input.handle();
    if (selEmoji) { K.state.emoji = null; const eb = $('emojiBadge'); if (eb) eb.remove(); const ebBtn = $('emojiPickerBtn'); if (ebBtn) ebBtn.classList.remove('active'); }
    const tmpId = 'tmp_'+Date.now();
    const optMsg = { message_id: tmpId, content, sender_id: K.state.user?.user_id, sender_username: K.state.user?.display_name, timestamp: new Date().toISOString(), is_own: true };
    if (selEmoji) { optMsg.emoji_file = selEmoji.file; optMsg.emoji_url = selEmoji.url; optMsg.emoji_size = selEmoji.size || 96; optMsg.emoji_count = selEmoji.count || 1; }
    const mc = $('messagesContainer');
    if (mc) {
      const empty = mc.querySelector('.k-empty');
      if (empty) mc.innerHTML = '';
      mc.insertAdjacentHTML('beforeend', K.chat._messageHtml(optMsg, true, false));
      K.chat._scrollToBottom();
    }
    try {
      const d = await K.api.post(url, payload);
      if (d.success) { K.chat.loadMessages(type, id); K.chat.loadList(); }
      else { K.ui.toast('Send failed', 'error'); }
    } catch(e) { K.ui.toast('Message not sent', 'error'); }
  },
  input: {
    _typingTimer: null,
    handle() {
      const input = $('messageInput'), btn = $('sendBtn');
      if (input) { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, MAX_INPUT_HEIGHT) + 'px'; }
      if (btn) btn.disabled = !(input?.value.trim());
      clearTimeout(K.chat.input._typingTimer);
      K.chat.input._typingTimer = setTimeout(() => K.chat._sendTyping(), TYPING_DEBOUNCE);
    },
    keydown(e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); K.chat.send(); return; }
      if ((e.ctrlKey || e.metaKey) && e.key === 'b') { e.preventDefault(); K.chat.format.insert('**'); }
      if ((e.ctrlKey || e.metaKey) && e.key === 'i') { e.preventDefault(); K.chat.format.insert('*'); }
    }
  },
  format: {
    insert(delim) {
      const input = $('messageInput'); if (!input) return;
      const start = input.selectionStart, end = input.selectionEnd;
      const val = input.value;
      const selected = val.substring(start, end);
      let replacement;
      if (selected) {
        // Wrap selected text
        replacement = delim + selected + delim;
      } else {
        // Insert placeholder, select placeholder on next char
        const placeholders = {'**': 'bold text', '*': 'italic text', '~~': 'strikethrough', '`': 'code'};
        const placeholder = placeholders[delim] || 'text';
        replacement = delim + placeholder + delim;
        // TODO: select the placeholder
      }
      input.value = val.substring(0, start) + replacement + val.substring(end);
      const newPos = start + replacement.length;
      input.selectionStart = input.selectionEnd = newPos;
      input.focus();
      K.chat.input.handle();
    },
    link() {
      const input = $('messageInput'); if (!input) return;
      const start = input.selectionStart, end = input.selectionEnd;
      const val = input.value;
      const selected = val.substring(start, end);
      if (selected && selected.includes('://')) {
        // Selected text looks like a URL → wrap with [text](url)
        input.value = val.substring(0, start) + '[' + selected + '](' + selected + ')' + val.substring(end);
      } else if (selected) {
        input.value = val.substring(0, start) + '[' + selected + '](url)' + val.substring(end);
      } else {
        input.value = val.substring(0, start) + '[link text](url)' + val.substring(end);
      }
      input.focus();
      K.chat.input.handle();
    }
  },
  _typingSent: false,
  async _sendTyping() {
    if (!K.state.activeChat || K.chat._typingSent) return;
    K.chat._typingSent = true;
    const { type, id } = K.state.activeChat;
    try { await K.api.post(V2 + `/typing/${type}/${id}`); } catch(_) {}
    setTimeout(() => { K.chat._typingSent = false; }, TYPING_COOLDOWN);
  },
  reply: {
    set(msgId, text) {
      K.state.replyTo = msgId;
      const bar = $('replyBar'); if (!bar) return;
      $('replyName').textContent = 'Replying';
      $('replyText').textContent = text || '';
      bar.style.display = 'flex'; $('messageInput')?.focus();
    },
    cancel() { K.state.replyTo = null; const bar = $('replyBar'); if (bar) bar.style.display = 'none'; }
  },
  async copy(msgId) {
    const el = document.querySelector(`[data-msg-id="${msgId}"] .k-msg-text`);
    const text = el?.textContent || '';
    try { await navigator.clipboard.writeText(text); K.ui.toast('Copied', 'success'); } catch(e) { K.ui.toast('Copy failed', 'error'); }
  },
  async react(msgId, emoji) {
    if (!msgId) return;
    const emojis = ['❤️','😂','👍','🔥','😮','😢','🙏'];
    if (emoji) {
      try {
        const d = await K.api.post(V2 + '/reactions/add', { message_id: msgId, reaction_type: emoji });
        if (d.success) K.chat.loadMessages(K.state.activeChat.type, K.state.activeChat.id);
        else K.ui.toast('React failed', 'error');
      } catch(_) {}
      return;
    }
    const picker = document.querySelector('.k-reaction-picker');
    if (picker) { picker.remove(); return; }
    const overlay = document.createElement('div');
    overlay.className = 'k-reaction-picker';
    overlay.innerHTML = emojis.map(e => `<span onclick="K.chat._pickReaction(${msgId},'${e}')">${e}</span>`).join('');
    overlay.onclick = (ev) => { if (ev.target === overlay) overlay.remove(); };
    const msgEl = document.querySelector(`[data-msg-id="${msgId}"]`);
    if (msgEl) { msgEl.style.position = 'relative'; msgEl.appendChild(overlay); setTimeout(() => overlay.classList.add('active'), 10); }
    else overlay.remove();
  },
  _pickReaction(msgId, emoji) {
    document.querySelector('.k-reaction-picker')?.remove();
    K.chat.react(msgId, emoji);
  },
    async uploadFiles(input) {
    if (!input?.files?.length || !K.state.activeChat) return;
    const { type, id } = K.state.activeChat;
    const fd = new FormData();
    const msgText = $('messageInput')?.value?.trim();
    for (const f of input.files) fd.append('file', f);
    if (msgText) fd.append('message', msgText);
    if (type === 'personal') fd.append('receiver_id', id);
    else if (type === 'group') fd.append('group_id', id);
    else if (type === 'channel') fd.append('channel_id', id);
    try {
      const d = await K.api.post('/files/upload_file', fd);
      if (d.success) { $('messageInput').value = ''; K.chat.loadMessages(type, id); K.ui.toast('File sent', 'success'); }
      else K.ui.toast('Upload failed', 'error');
    } catch(e) { K.ui.toast('Upload error', 'error'); }
    input.value = '';
  },
  voice: {
    _mediaRecorder: null, _stream: null, _chunks: [], _timer: null, _seconds: 0,
    toggle() {
      const r = $('voiceRecorder'), i = $('inputArea');
      if (r.style.display === 'flex') { K.chat.voice.cancel(); return; }
      if (!navigator.mediaDevices?.getUserMedia) { K.ui.toast('Voice recording not supported', 'error'); return; }
      navigator.mediaDevices.getUserMedia({audio: true}).then(stream => {
        K.chat.voice._stream = stream;
        const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : 'audio/webm';
        K.chat.voice._mediaRecorder = new MediaRecorder(stream, {mimeType: mime});
        K.chat.voice._chunks = []; K.chat.voice._seconds = 0;
        K.chat.voice._mediaRecorder.ondataavailable = e => { if (e.data.size) K.chat.voice._chunks.push(e.data); };
        K.chat.voice._mediaRecorder.start();
        i.style.display = 'none'; r.style.display = 'flex';
        $('voiceTimer').textContent = '0:00';
        K.chat.voice._timer = setInterval(() => {
          K.chat.voice._seconds++;
          $('voiceTimer').textContent = Math.floor(K.chat.voice._seconds/60) + ':' + String(K.chat.voice._seconds%60).padStart(2,'0');
        }, 1000);
      }).catch(() => K.ui.toast('Microphone access denied', 'error'));
    },
    _stopTracks() {
      if (K.chat.voice._stream) { K.chat.voice._stream.getTracks().forEach(t => t.stop()); K.chat.voice._stream = null; }
    },
    cancel() {
      if (K.chat.voice._mediaRecorder && K.chat.voice._mediaRecorder.state !== 'inactive') K.chat.voice._mediaRecorder.stop();
      K.chat.voice._stopTracks();
      clearInterval(K.chat.voice._timer); K.chat.voice._timer = null;
      K.chat.voice._chunks = []; K.chat.voice._seconds = 0;
      $('voiceRecorder').style.display = 'none'; $('inputArea').style.display = 'flex';
    },
    async send() {
      if (!K.chat.voice._mediaRecorder || K.chat.voice._mediaRecorder.state === 'inactive') { K.chat.voice.cancel(); return; }
      K.chat.voice._mediaRecorder.stop();
      clearInterval(K.chat.voice._timer); K.chat.voice._timer = null;
      await new Promise(r => { const c = K.chat.voice; c._mediaRecorder.onstop = () => { c._stopTracks(); r(); }; });
      const blob = new Blob(K.chat.voice._chunks, {type: 'audio/webm'});
      K.chat.voice._chunks = []; K.chat.voice._seconds = 0;
      if (!K.state.activeChat) { $('voiceRecorder').style.display = 'none'; $('inputArea').style.display = 'flex'; return; }
      const { type, id } = K.state.activeChat;
      const fd = new FormData(); fd.append('file', blob, 'voice_'+Date.now()+'.ogg');
      const msgText = $('messageInput')?.value?.trim();
      if (msgText) fd.append('message', msgText);
      if (type === 'personal') fd.append('receiver_id', id);
      else if (type === 'group') fd.append('group_id', id);
      else if (type === 'channel') fd.append('channel_id', id);
      try {
        const d = await K.api.post('/files/upload_file', fd);
        if (d.success) { K.ui.toast('Voice sent', 'success'); K.chat.loadMessages(type, id); }
        else K.ui.toast('Upload failed', 'error');
      } catch(e) { K.ui.toast('Upload error', 'error'); }
      $('voiceRecorder').style.display = 'none'; $('inputArea').style.display = 'flex';
    }
  },
  async delete(msgId) {
    if (!msgId || !await K.ui.confirm('Delete this message?')) return;
    try {
      const d = await K.api.post(V2 + `/messages/${msgId}/delete`);
      if (d.success) {
        const el = document.querySelector(`[data-msg-id="${msgId}"]`);
        if (el) el.style.opacity = '0.3';
        K.ui.toast('Deleted', 'success');
      } else K.ui.toast('Failed', 'error');
    } catch(e) { K.ui.toast('Delete failed', 'error'); }
  },
  async edit(msgId) {
    const el = document.querySelector(`[data-msg-id="${msgId}"] .k-msg-text`);
    const oldText = el?.textContent || '';
    const text = await K.ui.prompt('Edit message:', oldText);
    if (!text || text === oldText) return;
    try {
      const d = await K.api.post(V2 + `/messages/${msgId}/edit`, { content: text });
      if (d.success) {
        K.ui.toast('Edited', 'success');
        K.chat.loadMessages(K.state.activeChat.type, K.state.activeChat.id);
      } else K.ui.toast('Failed', 'error');
    } catch(e) { K.ui.toast('Edit failed', 'error'); }
  },
  lightbox(url) {
    const o = document.createElement('div');
    o.className = 'k-modal-overlay';
    o.style.cssText = 'background:rgba(0,0,0,0.95);cursor:pointer';
    o.onclick = () => o.remove();
    const img = document.createElement('img');
    img.src = url; img.style.cssText = 'max-width:90%;max-height:90%;border-radius:8px;object-fit:contain';
    o.appendChild(img); document.body.appendChild(o);
  },
  async startCall() {
    if (!K.state.activeChat || K.state.activeChat.type !== 'personal') return;
    const peerId = K.state.activeChat.id;
    const peer = K.state.chats?.find(c => (c.peer?.user_id || c.peer?.id) === peerId)?.peer;
    const peerName = peer?.display_name || peer?.username || '';
    K.calls._activeCallId = null;
    try {
      const d = await K.api.post(V2 + '/calls/start', { callee_id: peerId, type: 'audio' });
      if (d.success && d.data?.room_id) {
        K.calls._activeCallId = d.data.call_id;
        K.calls._showOutgoing(peerName, 'audio');
      } else K.ui.toast('Failed to start call', 'error');
    } catch(e) { K.ui.toast('Call failed', 'error'); }
  },
  menu: {
    toggle() {
      const menu = $('chatMenu'), info = $('chatInfo');
      info.style.display = 'none';
      if (!K.state.activeChat) return;
      const { type, id } = K.state.activeChat;
      if (menu.style.display === 'block') { menu.style.display = 'none'; return; }
      menu.style.display = 'block';
      const key = type+':'+id;
      const isPinned = K.state.pinned?.includes(key);
      let items = '';
      items += `<div class="k-chat-menu-item" onclick="K.chat.menu.togglePin('${key}')"><i class="fas fa-thumbtack"></i> ${isPinned ? 'Unpin' : 'Pin'} Chat</div>`;
      items += `<div class="k-chat-menu-item" onclick="K.features.showCreatePoll()"><i class="fas fa-poll"></i> Create Poll</div>`;
      if (type === 'personal') {
        items += `<div class="k-chat-menu-item" onclick="K.chat.menu.block(${id})"><i class="fas fa-ban"></i> Block User</div>`;
        items += `<div class="k-chat-menu-item" onclick="K.chat.menu.clear(${id})"><i class="fas fa-trash"></i> Clear Chat</div>`;
      } else if (type === 'group') {
        items += `<div class="k-chat-menu-item" onclick="K.chat.info.toggle()"><i class="fas fa-users"></i> View Members</div>`;
        items += `<div class="k-chat-menu-item danger" onclick="K.chat.menu.leaveGroup(${id})"><i class="fas fa-sign-out-alt"></i> Leave Group</div>`;
      } else if (type === 'channel') {
        items += `<div class="k-chat-menu-item" onclick="K.chat.info.toggle()"><i class="fas fa-info-circle"></i> Channel Info</div>`;
        items += `<div class="k-chat-menu-item" onclick="K.chat.menu.unsubscribe(${id})"><i class="fas fa-bell-slash"></i> Unsubscribe</div>`;
      }
      if (K.state.folders?.length) {
        items += `<div style="border-top:1px solid var(--border-color);margin:6px 0;padding-top:6px;font-size:11px;color:var(--text-muted);padding:6px 12px 0">Folders</div>`;
        items += K.state.folders.map(f => {
          const inF = f.chats?.some(x => x.type === type && x.id === id);
          return `<div class="k-chat-menu-item" onclick="K.chat.menu.toggleFolder('${esc(f.name)}','${type}',${id})"><i class="fas fa-folder${inF?'-open':''}"></i> ${inF ? 'Remove from' : 'Add to'} ${esc(f.name)}</div>`;
        }).join('');
      }
      menu.innerHTML = items || '<div style="padding:16px;color:var(--text-muted)">No actions</div>';
    },
    togglePin(key) {
      let p = K.state.pinned || [];
      const idx = p.indexOf(key);
      if (idx >= 0) p.splice(idx, 1);
      else p.push(key);
      K.state.pinned = p;
      localStorage.setItem('k_pinned', JSON.stringify(p));
      K.settings.saveToServer();
      K.chat.loadList();
      K.chat.menu.toggle();
    },
    toggleFolder(fname, type, id) {
      const f = K.state.folders.find(x => x.name === fname);
      if (!f) return;
      if (!f.chats) f.chats = [];
      const idx = f.chats.findIndex(x => x.type === type && x.id === id);
      if (idx >= 0) f.chats.splice(idx, 1);
      else f.chats.push({type, id});
      K.state.folders = (K.state.folders||[]).map(x => x.name === fname ? f : x);
      localStorage.setItem('k_folders', JSON.stringify(K.state.folders));
      K.settings.saveToServer();
      K.chat.loadList();
      K.chat.menu.toggle();
    },
    async block(id) { if (await K.ui.confirm('Block this user?')) { try { const d = await K.api.post(V2 + `/block_user/${id}`); if (d.success) { K.ui.toast('Blocked', 'success'); K.chat.close(); K.chat.loadList(); } } catch(e) { K.ui.toast('Failed', 'error'); } } },
    async leaveGroup(id) { if (await K.ui.confirm('Leave this group?')) { try { const d = await K.api.post(V2 + `/leave_group/${id}`); if (d.success) { K.ui.toast('Left group', 'success'); K.chat.close(); K.chat.loadList(); } } catch(e) { K.ui.toast('Failed', 'error'); } } },
    async unsubscribe(id) { if (await K.ui.confirm('Unsubscribe?')) { try { const d = await K.api.post(V2 + `/channels/${id}/unsubscribe`); if (d.success) { K.ui.toast('Unsubscribed', 'success'); K.chat.close(); K.chat.loadList(); } } catch(e) { K.ui.toast('Failed', 'error'); } } },
    async clear(id) { if (await K.ui.confirm('Clear all messages?')) { try { const d = await K.api.post(V2 + '/clear_chat', {chat_id: id}); if (d.success) { K.chat.loadMessages(K.state.activeChat.type, id); K.ui.toast('Chat cleared', 'success'); } else K.ui.toast('Failed', 'error'); } catch(e) { K.ui.toast('Failed', 'error'); } } }
  },
  info: {
    async toggle() {
      const info = $('chatInfo'), menu = $('chatMenu');
      menu.style.display = 'none';
      if (!K.state.activeChat) return;
      if (info.style.display === 'block') { info.style.display = 'none'; return; }
      info.style.display = 'block'; info.innerHTML = K.ui.loader();
      const { type, id } = K.state.activeChat;
      try {
        if (type === 'group') {
          const d = await K.api.get(V2 + `/groups/${id}/members`);
          if (d.success) {
            const data = d.data;
            info.innerHTML = `<div class="k-info-title">Members (${data.pagination?.total||data.members?.length||0})</div>
              ${(data.members||[]).map(m => `<div class="k-info-row"><div class="k-info-avatar">${(m.username||'?')[0].toUpperCase()}</div><div class="k-info-data"><div class="k-info-name">${esc(m.username)}</div><div class="k-info-role">${m.role||'member'}</div></div></div>`).join('')}`;
          }
        } else if (type === 'channel') {
          const d = await K.api.get(V2 + `/channels/${id}`);
          if (d.success) {
            const ch = d.data;
            info.innerHTML = `<div class="k-info-desc"><strong>Description:</strong><br>${esc(ch.description||'No description')}</div>
              <div class="k-info-stat"><strong>Subscribers:</strong> ${ch.subscriber_count||0}</div>`;
          }
        } else { info.innerHTML = ''; }
      } catch(e) { info.innerHTML = '<div class="k-info-empty">Failed to load info</div>'; }
    }
  }
};
