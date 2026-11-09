K.views = {
  show(name) {
    if (window.innerWidth <= 768) { const _sb = $('sidebar'), _mb = $('menuBtn'), _bd = $('sidebarBackdrop'); _sb?.classList.remove('open'); _mb?.classList.remove('active'); _bd?.classList.remove('open'); }
    document.querySelectorAll('.k-panel').forEach(p => p.classList.remove('active'));
    const p = $('panel-'+name); if (p) p.classList.add('active');
    document.querySelectorAll('.k-nav-item').forEach(n => n.classList.toggle('active', n.dataset.view === name));
    document.querySelector('.k-main')?.classList.toggle('map-fullscreen', name === 'map');
    K.chat.close();
    if (name === 'chats') { K.chat.loadList(); }
    if (name === 'saved') K.saved.load();
    if (name === 'stories') K.stories.load();
    if (name === 'contacts') K.contacts.load();
    if (name === 'calls') K.calls.load();
    if (name === 'music') K.music.load();
    if (name === 'map') K.map.init();
    if (name === 'settings') { K.settings.loadPrivacy(); K.settings.loadSessions(); }
    K.state.saveURL();
  }
};
