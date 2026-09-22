(function (global) {
  'use strict';

  const STYLES = {
    before: { color: '#0d6efd', weight: 1.5, fillColor: '#0d6efd', fillOpacity: 0.42 },
    peak:   { color: '#38bdf8', weight: 1.5, fillColor: '#38bdf8', fillOpacity: 0.36 },
    new:    { color: '#dc3545', weight: 1.8, fillColor: '#dc3545', fillOpacity: 0.55 }
  };

  const LABELS = {
    before: 'Вода «до»',
    peak:   'Вода (пик)',
    new:    'Новое затопление'
  };

  const COLORS = {
    before: '#0d6efd',
    peak:   '#38bdf8',
    new:    '#dc3545'
  };

  const ATTR_IMAGERY =
    'Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics';
  const ATTR_S2 =
    'Sentinel-2 cloudless &copy; <a href="https://eox.at">EOX</a> (CC BY-NC-SA 4.0)';

  let map = null;
  let groups = {};
  let baseLayers = {};
  let layerControl = null;
  let sideBySide = null;
  let splitOn = false;
  let splitRatio = 0.5;
  let activeBase = null;
  let onSplitChange = null;

  function init(containerId, opts) {
    opts = opts || {};

    map = L.map(containerId, {
      center: [50.55, 137.15],
      zoom: 10,
      zoomControl: true,
      preferCanvas: false,
      worldCopyJump: true
    });

    map.createPane('paneBefore').style.zIndex = 401;
    map.createPane('panePeak').style.zIndex   = 402;
    map.createPane('paneNew').style.zIndex    = 403;

    baseLayers['Esri World Imagery'] = L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      { maxZoom: 19, attribution: ATTR_IMAGERY }
    );

    baseLayers['Sentinel-2 cloudless'] = L.tileLayer(
      'https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2020_3857/default/g/{z}/{y}/{x}.jpg',
      { maxZoom: 14, attribution: ATTR_S2 }
    );

    baseLayers['OpenStreetMap'] = L.tileLayer(
      'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
      { maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' }
    );

    activeBase = baseLayers['Esri World Imagery'];
    activeBase.addTo(map);

    groups.before = L.geoJSON(null, {
      pane: 'paneBefore',
      style: () => STYLES.before,
      onEachFeature: bindPopup
    });

    groups.peak = L.geoJSON(null, {
      pane: 'panePeak',
      style: () => STYLES.peak,
      onEachFeature: bindPopup
    });

    groups.new = L.geoJSON(null, {
      pane: 'paneNew',
      style: () => STYLES.new,
      onEachFeature: bindPopup
    });

    groups.before.addTo(map);
    groups.peak.addTo(map);
    groups.new.addTo(map);

    // --- переключатель слоёв ---
    layerControl = L.control.layers(baseLayers, {
      '<span class="lbl-before">Вода «до»</span>': groups.before,
      '<span class="lbl-peak">Вода (пик)</span>': groups.peak,
      '<span class="lbl-new">Новое затопление</span>': groups.new
    }, { collapsed: false, position: 'topright' }).addTo(map);

    L.control.scale({ imperial: false, position: 'bottomleft' }).addTo(map);

    // --- перерисовка клипа при движении карты ---
    map.on('move zoom viewreset resize', updateClip);

    if (opts.onSplitChange) onSplitChange = opts.onSplitChange;

    return map;
  }

  function bindPopup(feature, layer) {
    const p = feature.properties || {};
    const layerKey = p.layer || 'before';
    const title = LABELS[layerKey] || p.type || 'Водный объект';
    const color = COLORS[layerKey] || '#666';
    const area = (p.area_ha != null) ? Number(p.area_ha).toLocaleString('ru-RU', { maximumFractionDigits: 1 }) : '—';

    const rows = [
      ['Площадь', '<b>' + area + ' га</b>'],
      ['Дата', p.date || '—'],
      ['Тип', p.name || p.type || '—']
    ];
    if (p.confidence != null) rows.push(['Уверенность', (p.confidence * 100).toFixed(0) + '%']);

    const html =
      '<div class="popup-title"><span class="dot" style="background:' + color + '"></span>' + title + '</div>' +
      '<table class="popup-table">' +
      rows.map(r => '<tr><td>' + r[0] + '</td><td>' + r[1] + '</td></tr>').join('') +
      '</table>';

    layer.bindPopup(html, { closeButton: true, autoPan: true });
    layer.bindTooltip(area + ' га', { sticky: true, direction: 'top', opacity: 0.85 });
  }

  function render(fc) {
    clear();

    const buckets = { before: [], peak: [], new: [] };
    (fc.features || []).forEach(f => {
      const k = (f.properties && f.properties.layer) || 'before';
      (buckets[k] || buckets.before).push(f);
    });

    Object.keys(buckets).forEach(k => {
      groups[k].addData({
        type: 'FeatureCollection',
        features: buckets[k]
      });
    });

    // если включён режим сравнения — прячем слой «новое затопление» из клипа
    updateClip();
  }

  function clear() {
    Object.keys(groups).forEach(k => groups[k].clearLayers());
  }

  function fitTo(fc) {
    if (!fc || !fc.features || !fc.features.length) return;
    const tmp = L.geoJSON(fc);
    const b = tmp.getBounds();
    if (b.isValid()) {
      map.fitBounds(b, { padding: [40, 40], maxZoom: 13 });
    }
  }

  function setSplit(enabled) {
    if (typeof L.Control.SideBySide !== 'function') {
      console.warn('[map] Leaflet.SideBySide не загружен');
      return false;
    }

    if (enabled === splitOn) return true;

    if (enabled) {
      // убираем текущую подложку, плагин сам добавит обе
      map.removeLayer(activeBase);

      const left  = baseLayers['Esri World Imagery'];
      const right = baseLayers['Sentinel-2 cloudless'];

      sideBySide = L.control.sideBySide(left, right).addTo(map);

      sideBySide.on('dividermove', function () {
        const d = map.getContainer().querySelector('.leaflet-sbs-divider');
        if (d) {
          const mr = map.getContainer().getBoundingClientRect();
          const dr = d.getBoundingClientRect();
          if (mr.width > 0) splitRatio = (dr.left + dr.width / 2 - mr.left) / mr.width;
        }
        updateClip();
      });

      splitOn = true;
    } else {
      if (sideBySide) {
        try { map.removeControl(sideBySide); } catch (e) { /* noop */ }
        sideBySide = null;
      }
      map.removeLayer(baseLayers['Esri World Imagery']);
      map.removeLayer(baseLayers['Sentinel-2 cloudless']);
      activeBase = baseLayers['Esri World Imagery'];
      activeBase.addTo(map);
      splitOn = false;
    }

    updateClip();
    if (onSplitChange) onSplitChange(splitOn);
    return true;
  }

  function isSplitOn() { return splitOn; }

  function updateClip() {
    if (!map) return;

    const pb = map.getPane('paneBefore');
    const pp = map.getPane('panePeak');
    if (!pb || !pp) return;

    if (!splitOn) {
      pb.style.clip = 'auto';
      pp.style.clip = 'auto';
      return;
    }

    const size = map.getSize();
    const nw = map.containerPointToLayerPoint([0, 0]);
    const se = map.containerPointToLayerPoint([size.x, size.y]);
    const clipX = nw.x + splitRatio * size.x;

    pb.style.clip = 'rect(' + [nw.y + 'px', clipX + 'px', se.y + 'px', nw.x + 'px'].join(',') + ')';
    pp.style.clip = 'rect(' + [nw.y + 'px', se.x + 'px', se.y + 'px', clipX + 'px'].join(',') + ')';
  }

  global.MapView = {
    init: init,
    render: render,
    clear: clear,
    fitTo: fitTo,
    setSplit: setSplit,
    isSplitOn: isSplitOn,
    getMap: () => map,
    LABELS: LABELS,
    COLORS: COLORS
  };
})(window);