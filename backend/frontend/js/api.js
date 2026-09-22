/* ============================================================
 *  api.js — слой доступа к данным (реальный API backend)
 *
 *  Эндпоинты бэкенда (src/service/api/routes.py):
 *    GET /api/pairs                                -> [{pair_id, event_id, aoi_name,
 *                                                     date_pre, date_peak, group, has_optical}]
 *    GET /api/pairs/{id}/contours?layer=<l>        -> FeatureCollection (pre|peak|flood|receded)
 *    GET /api/pairs/{id}/areas                     -> {flood_ha, water_pre_ha, water_peak_ha, aoi_ha}
 *    GET /api/pairs/{id}/report                    -> полный отчёт
 *    GET /api/pairs/{id}/download?format=geojson|shp&layer=<l>
 * ============================================================ */
(function (global) {
  'use strict';

  const BASE = (global.APP_CONFIG && global.APP_CONFIG.apiBase) || '';

  const R = 6378137;
  const toRad = d => d * Math.PI / 180;

  function ringAreaHa(ring) {
    let area = 0;
    for (let i = 0, n = ring.length; i < n; i++) {
      const p1 = ring[i], p2 = ring[(i + 1) % n];
      area += toRad(p2[0] - p1[0]) * (2 + Math.sin(toRad(p1[1])) + Math.sin(toRad(p2[1])));
    }
    return Math.abs(area * R * R / 2) / 10000; // м² -> га
  }

  function geomAreaHa(geom) {
    if (!geom) return 0;
    if (geom.type === 'Polygon') return ringAreaHa(geom.coordinates[0]);
    if (geom.type === 'MultiPolygon') {
      return geom.coordinates.reduce((s, poly) => s + ringAreaHa(poly[0]), 0);
    }
    return 0;
  }

  // Маппинг слоёв backend (properties.type) -> слои карты MapView.
  const LAYER_ALIAS = {
    pre: 'before', before: 'before', water_pre: 'before', ref: 'before',
    peak: 'peak', water_peak: 'peak', after: 'peak',
    flood: 'new', new: 'new', new_flood: 'new', flooded: 'new',
    receded: 'receded'
  };

  const LAYER_NAMES = {
    before: 'Вода «до»',
    peak: 'Вода (пик)',
    new: 'Новое затопление',
    receded: 'Убыль водного зеркала'
  };

  async function getJSON(path, timeoutMs) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs || 15000);
    try {
      const res = await fetch(BASE + path, {
        signal: ctrl.signal,
        headers: { 'Accept': 'application/json' }
      });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return await res.json();
    } finally {
      clearTimeout(timer);
    }
  }

  async function getPairs() {
    const data = await getJSON('/api/pairs', 15000);
    return Array.isArray(data) ? data : [];
  }

  async function getContours(pairId, layer) {
    // Первый запрос может запускать сегментацию + векторизацию — даём большой таймаут.
    const data = await getJSON(
      '/api/pairs/' + encodeURIComponent(pairId) + '/contours?layer=' + encodeURIComponent(layer),
      120000
    );
    return normalizeFC(data, layer);
  }

  async function getAreas(pairId) {
    return await getJSON('/api/pairs/' + encodeURIComponent(pairId) + '/areas', 120000);
  }

  async function getReport(pairId) {
    return await getJSON('/api/pairs/' + encodeURIComponent(pairId) + '/report', 120000);
  }

  function downloadUrl(pairId, layer, format) {
    return BASE + '/api/pairs/' + encodeURIComponent(pairId) +
      '/download?format=' + encodeURIComponent(format) + '&layer=' + encodeURIComponent(layer);
  }

  function normalizeFC(payload, defaultLayer) {
    let features = [];
    if (payload && payload.type === 'FeatureCollection' && Array.isArray(payload.features)) {
      features = payload.features.slice();
    }

    features.forEach(f => {
      const p = f.properties = f.properties || {};
      const layer = LAYER_ALIAS[p.type] || LAYER_ALIAS[defaultLayer] || 'before';
      p.layer = layer;
      if (!p.name) p.name = LAYER_NAMES[layer] || layer;
      p.area_ha = p.area_ha == null
        ? +geomAreaHa(f.geometry).toFixed(1)
        : +Number(p.area_ha).toFixed(1);
    });

    return {
      type: 'FeatureCollection',
      features: features,
      meta: (payload && payload.meta) || null
    };
  }

  global.API = {
    getPairs: getPairs,
    getContours: getContours,
    getAreas: getAreas,
    getReport: getReport,
    downloadUrl: downloadUrl,
    geomAreaHa: geomAreaHa
  };
})(window);
