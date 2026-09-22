/* ============================================================
 *  api.js — слой доступа к данным
 *  Ожидаемые эндпоинты бэкенда (все возвращают JSON):
 *    GET /api/scenes                       -> [{id, date, label, cloud}]
 *    GET /api/water?before=<id>&after=<id> -> FeatureCollection
 *    GET /api/report?before=<id>&after=<id>-> {summary, zones:[...]}  (опц.)
 *
 *  Если бэкенд недоступен — включается demo-режим с синтетикой.
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

  const MOCK_SCENES = [
    { id: 's2-2024-04-12', date: '2024-04-12', label: '12.04.2024 · Sentinel-2 · межень',      cloud: 3  },
    { id: 's2-2024-05-07', date: '2024-05-07', label: '07.05.2024 · Sentinel-2',                cloud: 12 },
    { id: 's2-2024-05-19', date: '2024-05-19', label: '19.05.2024 · Sentinel-2 · подъём',       cloud: 8  },
    { id: 's2-2024-06-02', date: '2024-06-02', label: '02.06.2024 · Sentinel-2 · пик',          cloud: 6  },
    { id: 's2-2024-06-21', date: '2024-06-21', label: '21.06.2024 · Sentinel-2 · спад',         cloud: 4  }
  ];

  // Русло Амура у Комсомольска-на-Амуре
  const RIVER = [
    [136.88, 50.640], [136.98, 50.596], [137.09, 50.560],
    [137.21, 50.522], [137.34, 50.492], [137.47, 50.455]
  ];

  const FLOOD_PATCHES = [
    { c: [137.030, 50.548], r: [0.0140, 0.0062], rot:  0.42 },
    { c: [137.205, 50.480], r: [0.0175, 0.0078], rot: -0.30 },
    { c: [136.945, 50.598], r: [0.0105, 0.0052], rot:  0.12 },
    { c: [137.320, 50.470], r: [0.0120, 0.0058], rot: -0.18 }
  ];

  function band(line, widthDeg) {
    const left = [], right = [];
    for (let i = 0; i < line.length; i++) {
      const p = line[i], prev = line[i - 1] || p, next = line[i + 1] || p;
      const dx = next[0] - prev[0], dy = next[1] - prev[1];
      const len = Math.hypot(dx, dy) || 1;
      const nx = -dy / len, ny = dx / len;
      const w = widthDeg * (0.8 + 0.35 * Math.sin(i * 1.7));
      left.push([p[0] + nx * w, p[1] + ny * w]);
      right.push([p[0] - nx * w, p[1] - ny * w]);
    }
    const ring = left.concat(right.reverse());
    ring.push(ring[0]);
    return ring;
  }

  function ellipse(cx, cy, rx, ry, rot, n) {
    n = n || 28;
    const pts = [];
    for (let i = 0; i < n; i++) {
      const a = 2 * Math.PI * i / n;
      const x = rx * Math.cos(a), y = ry * Math.sin(a);
      pts.push([
        cx + x * Math.cos(rot) - y * Math.sin(rot),
        cy + x * Math.sin(rot) + y * Math.cos(rot)
      ]);
    }
    pts.push(pts[0]);
    return pts;
  }

  function mkFeature(ring, layer, date, name) {
    const geom = { type: 'Polygon', coordinates: [ring] };
    return {
      type: 'Feature',
      geometry: geom,
      properties: {
        layer: layer,
        date: date,
        name: name,
        area_ha: +geomAreaHa(geom).toFixed(1)
      }
    };
  }

  function mockWater(beforeId, afterId) {
    const iB = Math.max(0, MOCK_SCENES.findIndex(s => s.id === beforeId));
    const iA = Math.max(0, MOCK_SCENES.findIndex(s => s.id === afterId));
    const dBefore = (MOCK_SCENES[iB] || MOCK_SCENES[0]).date;
    const dAfter  = (MOCK_SCENES[iA] || MOCK_SCENES[0]).date;

    const wB = 0.0035 + 0.0016 * iB;
    const wA = 0.0055 + 0.0034 * iA;
    const k  = Math.max(0, (iA - iB)) / 4;

    const features = [];

    features.push(mkFeature(band(RIVER, wB), 'before', dBefore, 'Водная поверхность (до)'));
    features.push(mkFeature(band(RIVER, wA), 'peak',   dAfter,  'Водная поверхность (пик)'));

    FLOOD_PATCHES.forEach((p, i) => {
      if (k <= 0.05) return;
      const s = 0.45 + 0.75 * k;
      const ring = ellipse(p.c[0], p.c[1], p.r[0] * s, p.r[1] * s, p.rot);
      features.push(mkFeature(ring, 'new', dAfter, 'Зона нового затопления #' + (i + 1)));
    });

    return { type: 'FeatureCollection', features: features, _demo: true };
  }

  const LAYER_ALIAS = {
    before: 'before', water_before: 'before', waterBefore: 'before', ref: 'before',
    peak: 'peak', water_peak: 'peak', waterPeak: 'peak', after: 'peak', max: 'peak',
    new: 'new', new_flood: 'new', newFlood: 'new', flood: 'new', flooded: 'new'
  };

  function normalizeFC(payload) {
    if (!payload) return { type: 'FeatureCollection', features: [] };

    let features = [];

    if (payload.type === 'FeatureCollection' && Array.isArray(payload.features)) {
      features = payload.features.slice();
    } else if (Array.isArray(payload)) {
      features = payload.slice();
    } else {
      Object.keys(payload).forEach(key => {
        const layer = LAYER_ALIAS[key];
        if (!layer) return;
        const v = payload[key];
        const arr = (v && v.type === 'FeatureCollection') ? v.features
                  : Array.isArray(v) ? v : [];
        arr.forEach(f => {
          f.properties = Object.assign({}, f.properties, { layer: layer });
          features.push(f);
        });
      });
    }

    features.forEach(f => {
      const p = f.properties = f.properties || {};
      p.layer = LAYER_ALIAS[p.layer] || LAYER_ALIAS[p.type] || 'before';
      if (p.area_ha == null) p.area_ha = +geomAreaHa(f.geometry).toFixed(1);
      else p.area_ha = +Number(p.area_ha).toFixed(1);
    });

    return { type: 'FeatureCollection', features: features, meta: payload.meta || null };
  }

  let demoMode = false;

  function isDemo() { return demoMode; }

  async function getJSON(path, timeoutMs) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs || 9000);
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

  async function getScenes() {
    try {
      const data = await getJSON('/api/scenes');
      if (!Array.isArray(data) || !data.length) throw new Error('пустой список');
      demoMode = false;
      return data;
    } catch (e) {
      console.warn('[api] /api/scenes недоступен => demo-режим:', e.message);
      demoMode = true;
      return MOCK_SCENES.map(s => Object.assign({}, s));
    }
  }

  async function getWater(beforeId, afterId) {
    const qs = '?before=' + encodeURIComponent(beforeId) + '&after=' + encodeURIComponent(afterId);
    if (!demoMode) {
      try {
        const data = await getJSON('/api/water' + qs, 15000);
        const fc = normalizeFC(data);
        if (!fc.features.length) throw new Error('нет объектов');
        return fc;
      } catch (e) {
        console.warn('[api] /api/water недоступен => demo-данные:', e.message);
        demoMode = true;
      }
    }
    return normalizeFC(mockWater(beforeId, afterId));
  }

  async function getReport(beforeId, afterId, localStats) {
    if (!demoMode) {
      try {
        const qs = '?before=' + encodeURIComponent(beforeId) + '&after=' + encodeURIComponent(afterId);
        return await getJSON('/api/report' + qs, 9000);
      } catch (e) {
        console.warn('[api] /api/report недоступен => локальный отчёт:', e.message);
      }
    }
    return null; // app.js построит отчёт сам
  }

  global.API = {
    getScenes: getScenes,
    getWater: getWater,
    getReport: getReport,
    geomAreaHa: geomAreaHa,
    isDemo: isDemo
  };
})(window);