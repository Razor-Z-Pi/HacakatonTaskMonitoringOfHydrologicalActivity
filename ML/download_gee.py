"""Выгрузка снимков Sentinel-1/2 из Google Earth Engine на каноническую сетку пары.

Для каждой пары из ``pairs.csv`` создаёт в её ``rasters/<event>/<aoi>/``:

    S1_pre_<date>.tif        3 канала VV, VH, VV_VH_ratio (дБ, sigma0)
    S1_peak_<date>.tif
    SENTINEL2_pre_<date>.tif  8 каналов B3,B4,B8,B11,NDWI,MNDWI,NDVI,AWEISH (SR 0-1)
    SENTINEL2_peak_<date>.tif  (только для пар с пригодной оптикой)

на сетке эталонной маски пары (10 м, EPSG:32652), попиксельно совмещённо —
именно в таком виде их читает ``hydromonitor.io``.

Рецепт S1 (из паспорта сцены): коллекция ``COPERNICUS/S1_GRD`` уже террейн-
скорректирована, радиометрически откалибрована и очищена от теплового шума,
каналы VV/VH — в дБ (10·log10). Дополнительно маскируется шум границы кадра
(< −30 дБ) и считается отношение VV/VH в дБ (VV − VH).

Рецепт S2: ``COPERNICUS/S2_SR_HARMONIZED`` (L2A surface reflectance, умножить
на 1e-4), маскируются облака/тени по SCL, считаются NDWI/MNDWI/NDVI/AWEIsh.

Запуск (один раз — интерактивная авторизация):
    earthengine authenticate
План без обращения к GEE:
    uv run python download_gee.py --dry-run
Экспорт в GEE-ассеты и скачивание GeoTIFF:
    uv run python download_gee.py --project <EE_PROJECT>
Альтернатива — экспорт в Google Drive (скачивание вручную / через geemap):
    uv run python download_gee.py --project <EE_PROJECT> --backend drive
"""

from __future__ import annotations

import argparse
import shutil
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio

from hydromonitor.config import load_config
from hydromonitor.pairs import load_pairs, rasters_dir_path, reference_mask_path

S1_BANDS = ["VV", "VH", "VV_VH_ratio"]
S2_BANDS = ["B3", "B4", "B8", "B11", "NDWI", "MNDWI", "NDVI", "AWEISH"]
S2_SRC_BANDS = ["B2", "B3", "B4", "B8", "B11", "B12"]
SCL_CLOUD_CLASSES = (3, 8, 9, 10)  # тень облака, облако ср./выс., перистые
S1_BORDER_DB = -30.0  # шум границы кадра Sentinel-1
MAX_DOWNLOAD_BYTES = 40 * 1024 * 1024  # запас под лимит getDownloadURL (~48 MB)

DRIVE_FOLDER = "hydromonitor_gee"
ASSET_ROOT = "hydromonitor_gee"


@dataclass
class Job:
    pair_id: str
    sensor: str          # "S1" | "SENTINEL2"
    window: str          # "pre" | "peak"
    date: str
    bands: list[str]
    target: Path
    desc: str
    grid: tuple          # (w, h, crs, crs_transform[6], bounds[4])
    orbit: float | None = None  # relativeOrbitNumber_start (только для S1)


def _grid_of(cfg, pair) -> tuple:
    """Каноническая сетка пары из эталонной маски: (w, h, crs, crsTransform, bounds)."""
    with rasterio.open(reference_mask_path(cfg, pair)) as s:
        t = s.transform
        crs_transform = [t.a, t.b, t.c, t.d, t.e, t.f]  # xScale, xShear, xOrigin, yShear, yScale, yOrigin
        bounds = [s.bounds.left, s.bounds.bottom, s.bounds.right, s.bounds.top]
        return s.width, s.height, str(s.crs), crs_transform, bounds


def build_jobs(cfg, pairs) -> list[Job]:
    jobs: list[Job] = []
    for p in pairs:
        grid = _grid_of(cfg, p)
        for window in ("pre", "peak"):
            date = p.date_pre_sar if window == "pre" else p.date_peak_sar
            if not date:
                continue
            target = rasters_dir_path(cfg, p) / f"S1_{window}_{date}.tif"
            desc = f"{p.pair_id}__S1_{window}"
            jobs.append(Job(p.pair_id, "S1", window, date, S1_BANDS, target, desc, grid,
                            float(p.relative_orbit)))
        if p.has_optical:
            for window in ("pre", "peak"):
                date = p.date_pre_opt if window == "pre" else p.date_peak_opt
                if not date:
                    continue
                target = rasters_dir_path(cfg, p) / f"SENTINEL2_{window}_{date}.tif"
                desc = f"{p.pair_id}__S2_{window}"
                jobs.append(Job(p.pair_id, "SENTINEL2", window, date, S2_BANDS, target, desc, grid))
    return jobs


# --------------------------------------------------------------------------- #
# GEE-серверная часть (импорт ee — внутри, чтобы --dry-run работал без GEE)
# --------------------------------------------------------------------------- #

def _region(ee, bounds, crs):
    left, bottom, right, top = bounds
    return ee.Geometry.Rectangle([left, bottom, right, top], proj=crs, geodesic=False)


def _s1_image(ee, job, region):
    date = job.date
    coll = (
        ee.ImageCollection("COPERNICUS/S1_GRD")
        .filterDate(date, ee.Date(date).advance(1, "day"))
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.eq("orbitProperties_pass", "DESCENDING"))
        .filter(ee.Filter.eq("relativeOrbitNumber_start", int(round(job.orbit))))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .filterBounds(region)
    )
    img = coll.mosaic()
    vv = img.select("VV").toFloat()  # уже дБ
    vh = img.select("VH").toFloat()
    img = img.updateMask(vv.gt(S1_BORDER_DB))
    ratio = vv.subtract(vh).rename("VV_VH_ratio")
    return img.select("VV", "VH").addBands(ratio).rename(S1_BANDS)


def _s2_image(ee, job, region):
    date = job.date
    coll = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterDate(date, ee.Date(date).advance(1, "day"))
        .filterBounds(region)
    )
    # AOI может накрываться несколькими MGRS-тайлами (напр. Благовещенск на стыке
    # зон 51/52) → мозаика всех тайлов за дату, облачность маскируется ниже по SCL.
    img = coll.mosaic()
    scl = img.select("SCL")
    keep = scl.neq(3).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10))
    refl = img.select(S2_SRC_BANDS).multiply(1e-4).updateMask(keep)
    b2, b3, b4, b8, b11, b12 = (refl.select(b) for b in S2_SRC_BANDS)
    ndwi = b3.subtract(b8).divide(b3.add(b8)).rename("NDWI")
    mndwi = b3.subtract(b11).divide(b3.add(b11)).rename("MNDWI")
    ndvi = b8.subtract(b4).divide(b8.add(b4)).rename("NDVI")
    aweish = (b2.add(b3.multiply(2.5)).subtract(b8.add(b11).multiply(1.5))
              .subtract(b12.multiply(0.25)).rename("AWEISH"))
    return refl.select("B3", "B4", "B8", "B11").addBands([ndwi, mndwi, ndvi, aweish])


def _export(ee, job, project, backend):
    w, h, crs, crs_transform, bounds = job.grid
    region = _region(ee, bounds, crs)
    image = _s1_image(ee, job, region) if job.sensor == "S1" else _s2_image(ee, job, region)
    params = dict(
        image=image.select(job.bands),
        description=job.desc[:100],
        region=region,
        crs=crs,
        crsTransform=crs_transform,
        dimensions=f"{w}x{h}",
        maxPixels=int(1e13),
    )
    if backend == "drive":
        return ee.batch.Export.image.toDrive(
            **params, folder=DRIVE_FOLDER, fileNamePrefix=job.desc
        ), None
    asset_id = _asset_id(project, job)
    task = ee.batch.Export.image.toAsset(
        **params, assetId=asset_id, pyramidingPolicy={".default": "sample"}
    )
    return task, asset_id


def _wait(tasks, poll_sec=15.0):
    pending = list(tasks)
    failed = []
    while pending:
        time.sleep(poll_sec)
        for t in list(pending):
            state = t.status()["state"]
            if state == "COMPLETED":
                print(f"  [OK]      {t.config['description']}")
                pending.remove(t)
            elif state in ("FAILED", "CANCELLED"):
                print(f"  [FAIL]    {t.config['description']}: {t.status().get('error_message')}")
                failed.append(t.config["description"])
                pending.remove(t)
    if failed:
        raise RuntimeError(f"Не завершились экспорты: {failed}")


def _asset_id(project: str, job: Job) -> str:
    return f"projects/{project}/assets/{ASSET_ROOT}/{job.desc}"


def _download(ee, job, asset_id):
    """Скачать ассет полосами и склеить на канонической сетке пары.

    ``getDownloadURL`` ограничен ~48 MB на запрос, а ассеты — сотни МБ float32,
    поэтому качаем горизонтальными полосами (с тем же crs_transform, что и при
    экспорте) и склеиваем по оси строк. Полосы совпадают пиксель-в-пиксель.
    """
    w, h, crs, ct, bounds = job.grid
    a, b, c, d, e, f = ct
    n_bands = len(job.bands)
    # фактор 8 байт/канал — консервативно (реальный запрос ~1.9x от float32)
    rows_per_strip = max(1, int(MAX_DOWNLOAD_BYTES // (w * 8 * n_bands)))
    image = ee.Image(asset_id)
    parts = []
    part_path = job.target.with_suffix(".part.tif")
    for r0 in range(0, h, rows_per_strip):
        r1 = min(h, r0 + rows_per_strip)
        strip_ct = [a, b, c + r0 * b, d, e, f + r0 * e]
        url = image.getDownloadURL({
            "bands": job.bands,
            "format": "GEO_TIFF",
            "crs": crs,
            "crs_transform": strip_ct,
            "dimensions": [w, r1 - r0],
        })
        with urllib.request.urlopen(url, timeout=900) as r, open(part_path, "wb") as fh:
            shutil.copyfileobj(r, fh)
        with rasterio.open(part_path) as src:
            parts.append(src.read().astype("float32"))
        part_path.unlink(missing_ok=True)
    full = np.concatenate(parts, axis=1)  # (bands, h, w)
    job.target.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "dtype": "float32",
        "nodata": None,
        "width": w,
        "height": h,
        "count": n_bands,
        "crs": crs,
        "transform": rasterio.Affine(a, b, c, d, e, f),
    }
    with rasterio.open(job.target, "w", **profile) as dst:
        dst.write(full)
        for i, name in enumerate(job.bands, 1):
            dst.set_band_description(i, name)
    print(f"  скачано: {job.target}")


def _download_existing(ee, jobs, project, workers=6):
    """Скачать уже готовые ассеты параллельно (режим --download-only)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    todo = []
    for j in jobs:
        if j.target.exists():
            continue
        aid = _asset_id(project, j)
        try:
            if ee.data.getInfo(aid) is None:
                continue  # ассет ещё не готов
        except ee.ee_exception.EEException:
            continue
        todo.append((j, aid))
    if not todo:
        print("Нет готовых ассетов для скачивания.")
        return
    print(f"Скачивание {len(todo)} ассетов (в {workers} потоков)…")
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_download, ee, j, aid): j for j, aid in todo}
        for fut in as_completed(futs):
            j = futs[fut]
            try:
                fut.result()
                done += 1
            except Exception as e:  # noqa: BLE001 — один плохой ассет не валит остальные
                print(f"  [FAIL] {j.target.name}: {type(e).__name__}: {e}")
    print(f"Скачано ассетов: {done}")


def _print_plan(jobs):
    n_s1 = sum(1 for j in jobs if j.sensor == "S1")
    n_s2 = sum(1 for j in jobs if j.sensor == "SENTINEL2")
    print(f"Всего экспортов: {len(jobs)} (S1: {n_s1}, S2: {n_s2})\n")
    print(f"{'пара':<42} {'сенсор':<10} {'окно':<5} {'дата':<11} {'сетка':<13} файл")
    for j in jobs:
        w, h, *_ = j.grid
        print(f"{j.pair_id:<42} {j.sensor:<10} {j.window:<5} {j.date:<11} "
              f"{w}x{h:<5} {j.target.name}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Выгрузка Sentinel-1/2 из GEE на сетку пар")
    ap.add_argument("--project", default=None, help="ID GEE-проекта (напр. ee-username); если не задан — ee.Initialize() без проекта")
    ap.add_argument("--backend", choices=("asset", "drive"), default="asset",
                    help="куда экспортировать: asset (автоскачивание) или drive (вручную/geemap)")
    ap.add_argument("--dry-run", action="store_true", help="только показать план, без GEE")
    ap.add_argument("--pairs", default="", help="фильтр по подстроке pair_id (через запятую)")
    ap.add_argument("--skip-fetch", action="store_true", help="только экспортировать, не скачивать")
    ap.add_argument("--download-only", action="store_true",
                    help="не экспортировать, только скачать уже готовые ассеты")
    ap.add_argument("--workers", type=int, default=6,
                    help="параллельных скачиваний (для --download-only)")
    args = ap.parse_args()

    cfg = load_config()
    pairs = load_pairs(cfg)
    if args.pairs:
        keep = {s.strip() for s in args.pairs.split(",") if s.strip()}
        pairs = [p for p in pairs if any(k in p.pair_id for k in keep)]

    jobs = build_jobs(cfg, pairs)
    _print_plan(jobs)

    if args.dry_run:
        return

    import ee  # noqa: E402  — локальный импорт: --dry-run работает без earthengine-api

    ee.Initialize(project=args.project)
    if args.download_only:
        print("\nСкачивание готовых ассетов…")
        _download_existing(ee, jobs, args.project, workers=args.workers)
        return
    if args.backend == "asset":
        # toAsset не создаёт промежуточные папки ассетов — создаём их заранее.
        folder = f"projects/{args.project}/assets/{ASSET_ROOT}"
        try:
            ee.data.createFolder(folder)
            print(f"Создана папка ассетов: {folder}")
        except ee.ee_exception.EEException:
            pass  # папка уже существует
    print("\nОтправка задач экспорта…")
    tasks, asset_ids = [], {}
    for j in jobs:
        if j.target.exists():
            print(f"  [skip] {j.target.name} уже есть")
            continue
        task, asset_id = _export(ee, j, args.project, args.backend)
        task.start()
        tasks.append(task)
        asset_ids[j.desc] = asset_id
    if not tasks:
        print("Все файлы уже на месте.")
        return

    print(f"Ожидание {len(tasks)} задач…")
    _wait(tasks)

    if args.skip_fetch:
        print("Экспорт завершён (скачивание пропущено по --skip-fetch).")
        return

    if args.backend == "asset":
        for j in jobs:
            if not j.target.exists():
                _download(ee, j, asset_ids[j.desc])
    else:
        print(f"\nСкачайте файлы из папки Google Drive '{DRIVE_FOLDER}' и положите их как:")
        for j in jobs:
            if not j.target.exists():
                print(f"  {j.desc}.tif  ->  {j.target}")


if __name__ == "__main__":
    main()
