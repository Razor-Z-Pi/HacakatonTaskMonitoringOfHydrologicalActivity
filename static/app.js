// Фронтенд обращается только к /api/* backend'а — контракт см. README.md.
const API = "/api";

const map = L.map("map").setView([50.5, 127.5], 7); // приблизительный центр Амурской области

// Подложка Esri World Imagery — бесплатно, без ключа (см. Стек, раздел 5).
L.tileLayer(
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
  { attribution: "Tiles © Esri", maxZoom: 18 }
).addTo(map);

const layers = {
  pre: L.geoJSON(null, { style: { color: "#1f78b4", weight: 1, fillOpacity: 0.35 } }),
  peak: L.geoJSON(null, { style: { color: "#33a1c9", weight: 1, fillOpacity: 0.35 } }),
  flood: L.geoJSON(null, { style: { color: "#e31a1c", weight: 1, fillOpacity: 0.5 } }),
};

layers.pre.addTo(map);
layers.peak.addTo(map);
layers.flood.addTo(map);

L.control
  .layers(null, {
    "Вода «до»": layers.pre,
    "Вода «пик»": layers.peak,
    "Новое затопление": layers.flood,
  })
  .addTo(map);

function bindPopups(layer, unitLabel) {
  layer.eachLayer((l) => {
    const p = l.feature?.properties || {};
    l.bindPopup(`<b>${p.type ?? unitLabel}</b><br>Площадь: ${p.area_ha ?? "—"} га`);
  });
}

async function fetchJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
  return res.json();
}

async function loadPairs() {
  const pairs = await fetchJson(`${API}/pairs`);
  const select = document.getElementById("pairSelect");
  select.innerHTML = "";
  for (const p of pairs) {
    const opt = document.createElement("option");
    opt.value = p.pair_id;
    opt.textContent = `${p.pair_id} — ${p.aoi_name} (${p.date_pre} → ${p.date_peak})`;
    select.appendChild(opt);
  }
  if (pairs.length > 0) await loadPair(pairs[0].pair_id);
}

async function loadContour(pairId, layerKey) {
  const geojson = await fetchJson(`${API}/pairs/${pairId}/contours?layer=${layerKey}`);
  layers[layerKey].clearLayers();
  layers[layerKey].addData(geojson);
  bindPopups(layers[layerKey], layerKey);
}

async function loadAreas(pairId) {
  const areas = await fetchJson(`${API}/pairs/${pairId}/areas`);
  document.getElementById("areaFlood").textContent = `${areas.flood_ha} га`;
  document.getElementById("areaPre").textContent = `${areas.water_pre_ha} га`;
  document.getElementById("areaPeak").textContent = `${areas.water_peak_ha} га`;
  document.getElementById("areaAoi").textContent = `${areas.aoi_ha} га`;
}

async function loadPair(pairId) {
  await Promise.all([
    loadContour(pairId, "pre"),
    loadContour(pairId, "peak"),
    loadContour(pairId, "flood"),
    loadAreas(pairId),
  ]);
  try {
    const bounds = layers.flood.getBounds();
    if (bounds.isValid()) map.fitBounds(bounds, { maxZoom: 12 });
  } catch (_) {
    /* пустой слой — не критично */
  }
}

document.getElementById("pairSelect").addEventListener("change", (e) => loadPair(e.target.value));

document.getElementById("btnReport").addEventListener("click", async () => {
  const pairId = document.getElementById("pairSelect").value;
  const report = await fetchJson(`${API}/pairs/${pairId}/report`);
  document.getElementById("reportJson").textContent = JSON.stringify(report, null, 2);
  new bootstrap.Modal(document.getElementById("reportModal")).show();
});

document.getElementById("btnDownloadGeojson").addEventListener("click", () => {
  const pairId = document.getElementById("pairSelect").value;
  window.location.href = `${API}/pairs/${pairId}/download?format=geojson&layer=flood`;
});

document.getElementById("btnDownloadShp").addEventListener("click", () => {
  const pairId = document.getElementById("pairSelect").value;
  window.location.href = `${API}/pairs/${pairId}/download?format=shp&layer=flood`;
});

loadPairs().catch((err) => console.error("Не удалось загрузить список пар:", err));
