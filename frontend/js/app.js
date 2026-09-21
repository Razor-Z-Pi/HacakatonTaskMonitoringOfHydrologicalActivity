(function () {
  'use strict';

  let scenes = [];
  let currentFC = null;
  let currentPair = { before: null, after: null };
  let currentStats = null;
  let reportData = null;

  const $ = id => document.getElementById(id);

  const els = {};

  document.addEventListener('DOMContentLoaded', init);

  async function init() {
    els.selBefore   = $('selBefore');
    els.selAfter    = $('selAfter');
    els.btnLoad     = $('btnLoad');
    els.btnSwap     = $('btnSwap');
    els.chkSplit    = $('chkSplit');
    els.statBefore  = $('statBefore');
    els.statPeak    = $('statPeak');
    els.statNew     = $('statNew');
    els.statDelta   = $('statDelta');
    els.reportBody  = $('reportBody');
    els.modeBadge   = $('modeBadge');
    els.loader      = $('mapLoader');

    MapView.init('map', {
      onSplitChange: function (on) {
        if (els.chkSplit.checked !== on) els.chkSplit.checked = on;
      }
    });

    bindUI();

    scenes = await API.getScenes();
    fillSelects(scenes);
    updateModeBadge();

    await load();
  }

  function bindUI() {
    els.btnLoad.addEventListener('click', load);
    els.btnSwap.addEventListener('click', function () {
      const a = els.selBefore.value;
      els.selBefore.value = els.selAfter.value;
      els.selAfter.value = a;
      load();
    });

    els.chkSplit.addEventListener('change', function () {
      const ok = MapView.setSplit(this.checked);
      if (!ok) {
        this.checked = false;
        toast('Плагин SideBySide не загрузился!!!', 'warning');
      }
    });

    $('btnDownload').addEventListener('click', downloadGeoJSON);
    $('btnDownloadTop').addEventListener('click', downloadGeoJSON);
    $('btnDownloadReport').addEventListener('click', downloadReportJSON);

    // отчёт строится при открытии модалки
    const modal = $('reportModal');
    modal.addEventListener('show.bs.modal', buildReport);
  }

  function fillSelects(list) {
    [els.selBefore, els.selAfter].forEach(sel => { sel.innerHTML = ''; });

    list.forEach(s => {
      const label = s.label || (s.date + (s.cloud != null ? ' · облачность ' + s.cloud + '%' : ''));
      [els.selBefore, els.selAfter].forEach(sel => {
        const o = document.createElement('option');
        o.value = s.id;
        o.textContent = label;
        sel.appendChild(o);
      });
    });

    const n = list.length;
    els.selBefore.value = list[Math.max(0, n - 4)].id;
    els.selAfter.value  = list[Math.max(0, n - 2)].id;
  }

  function updateModeBadge() {
    if (!els.modeBadge) return;
    if (API.isDemo()) {
      els.modeBadge.textContent = 'О как, тестовый режим!!!';
      els.modeBadge.className = 'badge rounded-pill text-bg-warning align-self-center d-none d-md-inline';
    } else {
      els.modeBadge.textContent = 'API подрублена!!!';
      els.modeBadge.className = 'badge rounded-pill text-bg-success align-self-center d-none d-md-inline';
    }
  }

  async function load() {
    const before = els.selBefore.value;
    const after  = els.selAfter.value;

    if (!before || !after) return;
    if (before === after) {
      toast('Выберите две разные даты!!!', 'warning');
      return;
    }

    setLoading(true);
    try {
      const fc = await API.getWater(before, after);
      currentFC = fc;
      currentPair = { before: before, after: after };

      MapView.render(fc);
      MapView.fitTo(fc);

      currentStats = computeStats(fc);
      renderStats(currentStats);

      updateModeBadge();
      toast('Загружено объектов: ' + fc.features.length, 'success', 2200);
    } catch (e) {
      console.error(e);
      toast('Ошибка загрузки: ' + e.message, 'danger');
    } finally {
      setLoading(false);
    }
  }

  function setLoading(on) {
    if (!els.loader) return;
    els.loader.classList.toggle('d-none', !on);
    els.btnLoad.disabled = on;
  }

  function computeStats(fc) {
    let before = 0, peak = 0, nw = 0;
    const list = [];

    (fc.features || []).forEach(f => {
      const p = f.properties || {};
      const a = Number(p.area_ha) || 0;
      if (p.layer === 'before') before += a;
      else if (p.layer === 'peak') peak += a;
      else if (p.layer === 'new') nw += a;

      list.push({ layer: p.layer, area: a, name: p.name || p.type || '—', date: p.date || '—' });
    });

    list.sort((x, y) => y.area - x.area);

    const delta = before > 0 ? ((peak - before) / before) * 100 : (peak > 0 ? 100 : 0);

    return {
      before: before,
      peak: peak,
      newFlood: nw,
      deltaPct: delta,
      features: list,
      pair: Object.assign({}, currentPair),
      generatedAt: new Date().toISOString()
    };
  }

  function fmt(n, d) {
    return Number(n || 0).toLocaleString('ru-RU', {
      minimumFractionDigits: d == null ? 0 : d,
      maximumFractionDigits: d == null ? 0 : d
    });
  }

  function renderStats(s) {
    els.statBefore.textContent = fmt(s.before);
    els.statPeak.textContent   = fmt(s.peak);
    els.statNew.textContent    = fmt(s.newFlood);

    const sign = s.deltaPct > 0 ? '+' : '';
    els.statDelta.textContent = sign + fmt(s.deltaPct, 1) + '%';
    els.statDelta.style.color = s.deltaPct > 0 ? '#dc3545' : '#198754';
  }

  async function buildReport() {
    if (!currentStats) {
      els.reportBody.innerHTML = '<div class="alert alert-secondary mb-0">Сначала загрузите пару сцен!!!</div>';
      return;
    }

    els.reportBody.innerHTML =
      '<div class="text-center py-4"><div class="spinner-border spinner-border-sm text-primary"></div></div>';

    // пробуем получить серверный отчёт, иначе строим локально
    let server = null;
    try {
      server = await API.getReport(currentPair.before, currentPair.after, currentStats);
    } catch (e) { /* игнор */ }

    reportData = server || localReport(currentStats);
    els.reportBody.innerHTML = renderReportHTML(reportData);
  }

  function localReport(s) {
    const b = (scenes.find(x => x.id === s.pair.before) || {}).date || s.pair.before;
    const a = (scenes.find(x => x.id === s.pair.after)  || {}).date || s.pair.after;

    const risk = s.newFlood > 5000 ? 'высокий'
               : s.newFlood > 1000 ? 'средний'
               : 'низкий';

    return {
      title: 'Отчёт о гидрологической обстановке!!!',
      period: { before: b, after: a },
      source: API.isDemo() ? 'demo' : 'api',
      generatedAt: new Date().toISOString(),
      summary: {
        water_before_ha: s.before,
        water_peak_ha: s.peak,
        new_flood_ha: s.newFlood,
        delta_pct: s.deltaPct,
        risk_level: risk,
        objects: s.features.length
      },
      top_zones: s.features.slice(0, 10)
    };
  }

  function renderReportHTML(r) {
    const s = r.summary || {};
    const p = r.period || {};

    const kpi = (val, key, color) =>
      '<div class="col-6 col-md-3">' +
        '<div class="report-kpi">' +
          '<div class="v" style="color:' + color + '">' + val + '</div>' +
          '<div class="k">' + key + '</div>' +
        '</div>' +
      '</div>';

    const zones = (r.top_zones || []).map((z, i) => {
      const lbl = MapView.LABELS[z.layer] || z.layer;
      const col = MapView.COLORS[z.layer] || '#666';
      return '<tr>' +
        '<td>' + (i + 1) + '</td>' +
        '<td><span class="badge" style="background:' + col + '">&nbsp;</span> ' + lbl + '</td>' +
        '<td>' + (z.name || '—') + '</td>' +
        '<td class="text-end"><b>' + fmt(z.area, 1) + '</b></td>' +
      '</tr>';
    }).join('');

    return '' +
      '<div class="mb-3">' +
        '<div class="d-flex justify-content-between flex-wrap gap-2">' +
          '<div><b>Период:</b> ' + (p.before || '—') + ' → ' + (p.after || '—') + '</div>' +
          '<div class="text-secondary small">Источник: ' +
            (r.source === 'demo' ? 'демонстрационные данные' : 'API') + '</div>' +
        '</div>' +
      '</div>' +

      '<div class="row g-2 mb-4">' +
        kpi(fmt(s.water_before_ha) + ' га', 'Вода «до»', '#0d6efd') +
        kpi(fmt(s.water_peak_ha) + ' га', 'Вода «пик»', '#38bdf8') +
        kpi(fmt(s.new_flood_ha) + ' га', 'Новое затопление', '#dc3545') +
        kpi((s.delta_pct > 0 ? '+' : '') + fmt(s.delta_pct, 1) + '%', 'Прирост воды', '#6f42c1') +
      '</div>' +

      '<div class="alert alert-' +
        (s.risk_level === 'высокий' ? 'danger' : s.risk_level === 'средний' ? 'warning' : 'success') +
        ' py-2">' +
        '<b>Уровень риска:</b> ' + (s.risk_level || '—') +
        ' &nbsp;·&nbsp; <b>Объектов на карте:</b> ' + (s.objects || 0) +
      '</div>' +

      '<h6 class="text-uppercase text-secondary small fw-bold mb-2">Крупнейшие зоны</h6>' +
      '<div class="table-responsive">' +
        '<table class="table table-sm table-hover report-table align-middle mb-0">' +
          '<thead class="table-light"><tr>' +
            '<th>#</th><th>Слой</th><th>Объект</th><th class="text-end">Площадь, га</th>' +
          '</tr></thead>' +
          '<tbody>' + (zones || '<tr><td colspan="4" class="text-center text-secondary">нет данных</td></tr>') + '</tbody>' +
        '</table>' +
      '</div>' +

      '<p class="text-secondary small mt-3 mb-0">' +
        'Сформировано: ' + new Date(r.generatedAt || Date.now()).toLocaleString('ru-RU') +
      '</p>';
  }

  function downloadGeoJSON() {
    if (!currentFC || !currentFC.features.length) {
      toast('Нет данных для экспорта!!!', 'warning');
      return;
    }

    const out = {
      type: 'FeatureCollection',
      name: 'water_' + currentPair.before + '__' + currentPair.after,
      features: currentFC.features
    };

    saveBlob(JSON.stringify(out, null, 2),
      'water_' + currentPair.before + '__' + currentPair.after + '.geojson',
      'application/geo+json');
    toast('GeoJSON сохранён', 'success');
  }

  function downloadReportJSON() {
    if (!reportData) { buildReport(); }
    const payload = reportData || localReport(currentStats || computeStats({ features: [] }));
    saveBlob(JSON.stringify(payload, null, 2),
      'report_' + (currentPair.before || 'na') + '__' + (currentPair.after || 'na') + '.json',
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