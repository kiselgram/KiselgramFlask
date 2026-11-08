'use strict';

/* Kiselgram — World Map tab with live user locations.
 * Shows live shared locations (from /tg/geo/live) on a Leaflet + OpenStreetMap map.
 * Polls for location updates so markers move in near real time.
 * Falls back to demo cities when no live locations exist.
 */

K.map = {
  map: null,
  inited: false,
  markers: {},            // message_id -> Leaflet marker
  liveTimer: null,
  demoCities: [
    { name: 'New York', lat: 40.7128, lng: -74.0060, country: 'USA' },
    { name: 'London', lat: 51.5074, lng: -0.1278, country: 'UK' },
    { name: 'Paris', lat: 48.8566, lng: 2.3522, country: 'France' },
    { name: 'Berlin', lat: 52.5200, lng: 13.4050, country: 'Germany' },
    { name: 'Moscow', lat: 55.7558, lng: 37.6173, country: 'Russia' },
    { name: 'Tokyo', lat: 35.6762, lng: 139.6503, country: 'Japan' },
    { name: 'Sydney', lat: -33.8688, lng: 151.2093, country: 'Australia' },
    { name: 'São Paulo', lat: -23.5505, lng: -46.6333, country: 'Brazil' },
    { name: 'Cape Town', lat: -33.9249, lng: 18.4241, country: 'South Africa' },
    { name: 'Dubai', lat: 25.2048, lng: 55.2708, country: 'UAE' },
    { name: 'Bangkok', lat: 13.7563, lng: 100.5018, country: 'Thailand' },
    { name: 'Istanbul', lat: 41.0082, lng: 28.9784, country: 'Turkey' }
  ],

  init() {
    if (!document.getElementById('map')) return;
    if (typeof L === 'undefined') {
      // Leaflet (CDN) not reachable — show a friendly placeholder instead of crashing.
      const wrap = $('mapWrap');
      if (wrap && !wrap.querySelector('.k-map-offline')) {
        const msg = document.createElement('div');
        msg.className = 'k-map-offline';
        msg.style.cssText = 'position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;color:var(--text-muted);font-size:14px;text-align:center;padding:20px';
        msg.innerHTML = '<i class="fas fa-map" style="font-size:32px"></i><div>Map is unavailable offline.<br>Connect to the internet and reopen this tab.</div>';
        wrap.appendChild(msg);
      }
      return;
    }
    if (this.inited) {
      this.map.invalidateSize();
      this.loadSelectedLocations();
      this._startLivePolling();
      return;
    }
    this.inited = true;

    const map = L.map('map', {
      center: [20, 0],
      zoom: 2,
      minZoom: 1,
      maxZoom: 18,
      zoomControl: true,
      attributionControl: false,
      scrollWheelZoom: true
    });

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 18,
      minZoom: 1,
      attribution: '© OpenStreetMap contributors'
    }).addTo(map);

    this.map = map;

    this._loadChatSelector();
    this.loadSelectedLocations();
    this._startLivePolling();
  },

  _loadChatSelector() {
    const sel = $('mapChatSelect');
    if (!sel) return;
    while (sel.options.length > 1) sel.remove(1);
    try {
      (K.state.chats || []).forEach((c) => {
        const opt = document.createElement('option');
        opt.value = c.id;
        opt.textContent = c.name || (c.chat_type === 'personal' ? 'Personal chat' : c.chat_type) + ' #' + c.id;
        sel.appendChild(opt);
      });
    } catch (e) {}
  },

  async loadSelectedLocations() {
    if (!this.map || typeof L === 'undefined') return;
    const sel = $('mapChatSelect');
    const chatId = sel ? parseInt(sel.value, 10) : null;
    const isAll = sel && sel.value === 'all';

    // Clear existing markers
    Object.values(this.markers).forEach((m) => this.map.removeLayer(m));
    this.markers = {};

    const countEl = $('mapLocationsCount');
    if (countEl) countEl.style.display = 'none';

    let locations = [];

    if (!isAll && chatId) {
      try {
        const d = await K.api.get(V2 + `/tg/geo/live?chat_id=${chatId}`);
        if (d.success) locations = d.data.live || [];
      } catch (e) {}
    } else {
      try {
        const d = await K.api.get(V2 + '/tg/geo/live');
        if (d.success) locations = d.data.live || [];
      } catch (e) {}
    }

    this._renderLiveLocations(locations);
  },

  _renderLiveLocations(locations) {
    const countEl = $('mapLocationsCount');
    const me = K.state.user?.user_id;

    if (countEl) {
      countEl.textContent = locations.length + ' live location' + (locations.length !== 1 ? 's' : '');
      countEl.style.display = locations.length ? 'block' : 'none';
    }

    if (!locations || locations.length === 0) {
      this._renderDemoCities();
      return;
    }

    const group = L.featureGroup().addTo(this.map);
    const now = new Date();

    locations.forEach((loc) => {
      const isOwn = loc.user_id === me;
      const marker = L.marker([loc.lat, loc.lon], {
        icon: L.divIcon({
          className: 'k-live-marker' + (isOwn ? ' k-live-marker-me' : ''),
          html: `<div style="width:26px;height:26px;border-radius:50%;background:${isOwn ? 'var(--accent-red)' : 'var(--accent-blue)'};color:white;display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;border:2px solid white;box-shadow:0 2px 6px rgba(0,0,0,0.3)">📍</div>`,
          iconSize: [26, 26],
          iconAnchor: [13, 13]
        })
      }).addTo(group);

      const until = loc.until ? new Date(loc.until) : null;
      const remaining = until ? Math.max(0, Math.ceil((until - now) / 60000)) : 0;
      const timeLeft = remaining > 0 ? ` (${remaining}m left)` : '';

      marker.bindPopup(
        `<div style="min-width:180px">` +
        `<div style="font-weight:600;font-size:13px">${esc(loc.username || 'Unknown')}${isOwn ? ' <span style="font-size:10px;color:var(--accent-red)">(you)</span>' : ''}</div>` +
        `<div style="font-size:11px;color:var(--text-muted)">${loc.lat.toFixed(5)}, ${loc.lon.toFixed(5)}${timeLeft}</div>` +
        `<div style="font-size:11px;color:var(--text-muted);margin-top:4px">Chat #${loc.chat_id}</div>` +
        `<a href="#" onclick="event.preventDefault();K.map._openOSM(${loc.lat},${loc.lon})" style="font-size:11px;color:var(--accent-blue)">Open in map</a>` +
        `</div>`,
        { className: 'k-map-popup' }
      );

      this.markers[loc.message_id] = marker;
    });

    this.map.fitBounds(group.getBounds().pad(0.4));
  },

  _renderDemoCities() {
    const group = L.featureGroup().addTo(this.map);
    this.demoCities.forEach((c) => {
      const marker = L.marker([c.lat, c.lng]).addTo(group);
      marker.bindPopup(`<strong>${esc(c.name)}</strong><br>${esc(c.country)}<br><small style="color:var(--text-muted)">demo location</small>`, { className: 'k-map-popup' });
      this.markers['demo_' + c.name] = marker;
    });
  },

  /* Focus the map on a shared (static) location from a message and open its popup. */
  showLocation(lat, lon, sender) {
    if (!this.map || typeof L === 'undefined') return;
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
    if (this._focusMarker) {
      try { this.map.removeLayer(this._focusMarker); } catch (e) {}
      this._focusMarker = null;
    }
    const from = sender ? `from <b>${esc(sender)}</b>` : '';
    this._focusMarker = L.marker([lat, lon], {
      icon: L.divIcon({
        className: 'k-focus-marker',
        html: '<div class="k-focus-dot"></div>',
        iconSize: [30, 30],
        iconAnchor: [15, 15]
      })
    }).addTo(this.map);
    this._focusMarker.bindPopup(
      `<div style="min-width:180px">` +
      `<div style="font-weight:600;font-size:13px">📍 Shared location</div>` +
      (sender ? `<div style="font-size:12px;margin-top:2px">${from}</div>` : '') +
      `<div style="font-size:11px;color:var(--text-muted);margin-top:4px">${lat.toFixed(5)}, ${lon.toFixed(5)}</div>` +
      `<a href="#" onclick="event.preventDefault();K.map._openOSM(${lat},${lon})" style="font-size:11px;color:var(--accent-blue)">Open in OpenStreetMap</a>` +
      `</div>`,
      { className: 'k-map-popup' }
    );
    this.map.flyTo([lat, lon], 15, { duration: 0.8 });
    setTimeout(() => { try { this._focusMarker && this._focusMarker.openPopup(); } catch (e) {} }, 900);
  },

  _startLivePolling() {
    if (this.liveTimer) clearInterval(this.liveTimer);
    // Poll live locations every 15 seconds
    this.liveTimer = setInterval(() => {
      this.loadSelectedLocations();
    }, 15000);
  },

  _stopLivePolling() {
    if (this.liveTimer) {
      clearInterval(this.liveTimer);
      this.liveTimer = null;
    }
  },

  _openOSM(lat, lon) {
    window.open(`https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=15/${lat}/${lon}`, '_blank');
  }
};

// Cleanup polling when navigating away
const _origShow = K.views.show;
K.views.show = function(name) {
  if (name !== 'map' && K.map && K.map._stopLivePolling) K.map._stopLivePolling();
  _origShow.call(this, name);
};
