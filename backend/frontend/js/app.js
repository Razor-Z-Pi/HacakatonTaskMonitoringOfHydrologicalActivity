(function () {
  'use strict';

  let pairs = [];
  let currentPairId = null;
  let currentFC = null;
  let currentAreas = null;
  let reportData = null;

  const $ = id => document.getElementById(id);
  const els = {};

  document.addEventListener('DOMContentLoaded', init);

  async function init() {
    els.selPair      = $('selPair');
    els.btnLoad      = $('btnLoad');
    els.chkSplit     = $('chkSplit');
    els.statBefore   = $('statBefore');
    els.statPeak     = $('statPeak');
    els.statNew      = $('statNew');
    els.statDelta    = $('statDelta');
    els.reportBody   = $('reportBody');
    els.modeBadge    = $('modeBadge');
    els.loader       = $('mapLoader');
    els.pairMeta     = $('pairMeta');

    MapView.init('map', {
      onSplitChange: function (on) {
        if (els.chkSplit.checked !== on) els.chkSplit.checked = on;
      }
    });

    bindUI();

    try {
      pairs = await API.getPairs();
      fillPairSelect(pairs);
      updateModeBadge(true);
      await load();
    } catch (e) {
      console.error(e);
      updateModeBadge(false);
      toast('Не удалось подключиться к API: ' + e.message, 'danger');
    }
  }

  function bindUI() {
    els.btnLoad.addEventListener('click', load);

    els.chkSplit.addEventListener('change', function () {
      const ok = MapView.setSplit(this.checked);
      if (!ok) {
        this.checked = false;
        toast('Плагин SideBySide не загрузился', 'warning');
      }
    });

    $('btnDownload').addEventListener('click', downloadGeoJSON);
    $('btnDownloadTop').addEventListener('click', downloadGeoJSON);
    $('btnDownloadReport').addEventListener('click', downloadReportJSON);

    const modal = $('reportModal');
    modal.addEventListener('show.bs.modal', buildReport);
  }

  function fillPairSelect(list) {
    els.selPair.innerHTML = '';
    list.forEach(p => {
      const o = document.createElement('option');
      o.value = p.pair_id;
      const kind = p.group === 'control' ? ' · межень' : '';
      o.textContent = (p.aoi_name || p.pair_id) + ' · ' + p.date_pre + ' → ' + p.date_peak + kind;
      els.selPair.appendChild(o);
    });
  }

  function updateModeBadge(ok) {
    if (!els.modeBadge) return;
    if (ok) {
      els.modeBadge.textContent = 'API подключён';
      els.modeBadge.className = 'badge rounded-pill text-bg-success align-self-center d-none d-md-inline';
    } else {
      els.modeBadge.textContent = 'API недоступен';
      els.modeBadge.className = 'badge rounded-pill text-bg-danger align-self-center d-none d-md-inline';
    }
  }

  async function load() {
    const pairId = els.selPair.value;
    if (!pairId) {
      toast('Нет пар для отображения', 'warning');
      return;
    }

    setLoading(true);
    try {
      const pair = pairs.find(p => p.pair_id === pairId) || {};

      // Сегментация считается лениво на первом запросе; три контура + площади — параллельно.
      const [pre, peak, flood, areas] = await Promise.all([
        API.getContours(pairId, 'pre'),
        API.getContours(pairId, 'peak'),
        API.getContours(pairId, 'flood'),
        API.getAreas(pairId)
      ]);

      stampDates(pre.features, pair.date_pre);
      stampDates(peak.features, pair.date_peak);
      stampDates(flood.features, pair.date_peak);

      currentFC = {
        type: 'FeatureCollection',
        features: (pre.features || []).concat(peak.features || [], flood.features || [])
      };
      currentPairId = pairId;
      currentAreas = areas;
      reportData = null;

      MapView.render(currentFC);
      MapView.fitTo(currentFC);

      renderStats(areas);
      if (els.pairMeta) {
        els.pairMeta.textContent = (pair.event_id ? pair.event_id + ' · ' : '') + (pair.aoi_name || pairId);
      }

      toast('Загружено объектов: ' + currentFC.features.length, 'success', 2200);
    } catch (e) {
      console.error(e);
      toast('Ошибка загрузки: ' + e.message, 'danger');
    } finally {
      setLoading(false);
    }
  }

  function stampDates(features, date) {
    (features || []).forEach(f => {
      if (f.properties) f.properties.date = date || '—';
    });
  }

  function setLoading(on) {
    if (!els.loader) return;
    els.loader.classList.toggle('d-none', !on);
    els.btnLoad.disabled = on;
  }

  function fmt(n, d) {
    return Number(n || 0).toLocaleString('ru-RU', {
      minimumFractionDigits: d == null ? 0 : d,
      maximumFractionDigits: d == null ? 0 : d
    });
  }

  function renderStats(areas) {
    const before = Number(areas.water_pre_ha) || 0;
    const peak   = Number(areas.water_peak_ha) || 0;
    const flood  = Number(areas.flood_ha) || 0;

    els.statBefore.textContent = fmt(before);
    els.statPeak.textContent   = fmt(peak);
    els.statNew.textContent    = fmt(flood);

    const delta = before > 0 ? ((peak - before) / before) * 100 : (peak > 0 ? 100 : 0);
    const sign = delta > 0 ? '+' : '';
    els.statDelta.textContent = sign + fmt(delta, 1) + '%';
    els.statDelta.style.color = delta > 0 ? '#dc3545' : '#198754';
  }

  async function buildReport() {
    if (!currentPairId) {
      els.reportBody.innerHTML = '<div class="alert alert-secondary mb-0">Сначала загрузите пару.</div>';
      return;
    }

    els.reportBody.innerHTML =
      '<div class="text-center py-4"><div class="spinner-border spinner-border-sm text-primary"></div></div>';

    try {
      reportData = await API.getReport(currentPairId);
      els.reportBody.innerHTML = renderReportHTML(reportData);
    } catch (e) {
      console.error(e);
      els.reportBody.innerHTML =
        '<div class="alert alert-danger mb-0">Не удалось получить отчёт: ' + e.message + '</div>';
    }
  }

  function renderReportHTML(r) {
    const before = Number(r.water_pre_ha) || 0;
    const peak   = Number(r.water_peak_ha) || 0;
    const flood  = Number(r.flood_ha) || 0;
    const deltaPct = before > 0 ? ((peak - before) / before) * 100 : (peak > 0 ? 100 : 0);

    const risk = flood > 5000 ? 'высокий'
               : flood > 1000 ? 'средний'
               : 'низкий';

    const kpi = (val, key, color) =>
      '<div class="col-6 col-md-3">' +
        '<div class="report-kpi">' +
          '<div class="v" style="color:' + color + '">' + val + '</div>' +
          '<div class="k">' + key + '</div>' +
        '</div>' +
      '</div>';

    const bc = r.landcover_breakdown || {};
    const warnings = (r.warnings || []).map(w =>
      '<li>' + w + '</li>'
    ).join('');

    return '' +
      '<div class="mb-3">' +
        '<div class="d-flex justify-content-between flex-wrap gap-2">' +
          '<div><b>' + (r.aoi_name || r.pair_id) + '</b> · ' +
            (r.date_pre || '—') + ' → ' + (r.date_peak || '—') + '</div>' +
          '<div class="text-secondary small">Источник: API</div>' +
        '</div>' +
      '</div>' +

      '<div class="row g-2 mb-4">' +
        kpi(fmt(before) + ' га', 'Вода «до»', '#0d6efd') +
        kpi(fmt(peak) + ' га', 'Вода «пик»', '#38bdf8') +
        kpi(fmt(flood) + ' га', 'Новое затопление', '#dc3545') +
        kpi((deltaPct > 0 ? '+' : '') + fmt(deltaPct, 1) + '%', 'Прирост воды', '#6f42c1') +
      '</div>' +

      '<div class="row g-2 mb-3">' +
        kpi(fmt(r.receded_ha) + ' га', 'Убыль воды', '#198754') +
        kpi(fmt(r.aoi_ha) + ' га', 'Площадь AOI', '#6c757d') +
        kpi(fmt(r.flood_share_pct, 2) + '%', 'Доля затопления AOI', '#fd7e14') +
        kpi((r.has_optical ? 'да' : 'нет'), 'Оптика S2', r.has_optical ? '#0d6efd' : '#6c757d') +
      '</div>' +

      '<div class="alert alert-' +
        (risk === 'высокий' ? 'danger' : risk === 'средний' ? 'warning' : 'success') +
        ' py-2">' +
        '<b>Уровень риска:</b> ' + risk +
        ' &nbsp;·&nbsp; <b>Застроено в зоне затопления:</b> ' + fmt(bc.built_up_ha, 1) + ' га' +
      '</div>' +

      (warnings
        ? '<div class="alert alert-warning py-2"><b>Предупреждения:</b><ul class="mb-0 mt-1">' + warnings + '</ul></div>'
        : '') +

      '<p class="text-secondary small mt-3 mb-0">' +
        'Пара: ' + (r.event_id || '—') + ' · ' + (r.aoi_name || '—') +
      '</p>';
  }

  function downloadGeoJSON() {
    if (!currentFC || !currentFC.features.length) {
      toast('Нет данных для экспорта', 'warning');
      return;
    }

    const out = {
      type: 'FeatureCollection',
      name: 'water_' + currentPairId,
      features: currentFC.features
    };

    saveBlob(JSON.stringify(out, null, 2),
      'water_' + currentPairId + '.geojson',
      'application/geo+json');
    toast('GeoJSON сохранён', 'success');
  }

  function downloadReportJSON() {
    if (!reportData) { buildReport(); return; }
    saveBlob(JSON.stringify(reportData, null, 2),
      'report_' + currentPairId + '.json',
      'application/json');
  }

  function saveBlob(text, filename, mime) {
    const blob = new Blob([text], { type: mime + ';charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1500);
  }

  function toast(msg, kind, delay) {
    const box = $('toastBox');
    if (!box) return;

    const el = document.createElement('div');
    el.className = 'toast align-items-center text-bg-' + (kind || 'secondary') + ' border-0';
    el.setAttribute('role', 'alert');
    el.innerHTML =
      '<div class="d-flex">' +
        '<div class="toast-body">' + msg + '</div>' +
        '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>' +
      '</div>';

    box.appendChild(el);
    const t = new bootstrap.Toast(el, { delay: delay || 3200 });
    t.show();
    el.addEventListener('hidden.bs.toast', () => el.remove());
  }
})();
