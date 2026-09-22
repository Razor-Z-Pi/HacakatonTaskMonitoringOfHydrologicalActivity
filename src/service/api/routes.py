from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from ...geoutils.vectorize import geodataframe_to_zipped_shapefile, mask_to_geodataframe
from ...repository import DataRepository, PairNotFoundError
from ...schemas import (
    AreasResponse,
    ContourLayer,
    DownloadFormat,
    MaskLayer,
    PairSummary,
    ReportResponse,
)
from ..deps import get_repository

router = APIRouter(prefix="/api", tags=["hydromonitor"])


def _get_pair_or_404(repo: DataRepository, pair_id: str) -> None:
    try:
        repo.get_pair_row(pair_id)
    except PairNotFoundError:
        raise HTTPException(status_code=404, detail=f"Пара '{pair_id}' не найдена")


@router.get("/pairs", response_model=list[PairSummary])
def list_pairs(repo: DataRepository = Depends(get_repository)) -> list[PairSummary]:
    return repo.list_pairs()


@router.get("/pairs/{pair_id}/areas", response_model=AreasResponse)
def get_areas(pair_id: str, repo: DataRepository = Depends(get_repository)) -> AreasResponse:
    _get_pair_or_404(repo, pair_id)
    try:
        return repo.get_areas(pair_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=422, detail=f"Не найдены исходные растры пары: {exc}")


@router.get("/pairs/{pair_id}/contours")
def get_contours(
    pair_id: str,
    layer: ContourLayer = Query(..., description="pre | peak | flood | receded"),
    repo: DataRepository = Depends(get_repository),
) -> JSONResponse:
    _get_pair_or_404(repo, pair_id)
    try:
        geojson = repo.get_contours_geojson(pair_id, layer.value)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=422, detail=f"Не найдены исходные растры пары: {exc}")
    return JSONResponse(content=geojson)


@router.get("/pairs/{pair_id}/report", response_model=ReportResponse)
def get_report(pair_id: str, repo: DataRepository = Depends(get_repository)) -> ReportResponse:
    _get_pair_or_404(repo, pair_id)
    try:
        return repo.get_report(pair_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=422, detail=f"Не найдены исходные растры пары: {exc}")


@router.get("/pairs/{pair_id}/mask")
def get_mask(
    pair_id: str,
    layer: MaskLayer = Query(MaskLayer.flood, description="flood (по умолчанию) | pre | peak | receded"),
    repo: DataRepository = Depends(get_repository),
) -> FileResponse:
    _get_pair_or_404(repo, pair_id)
    try:
        path = repo.get_mask_path(pair_id, layer.value)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=422, detail=f"Не найдены исходные растры пары: {exc}")
    return FileResponse(path, media_type="image/tiff", filename=path.name)


@router.get("/pairs/{pair_id}/download")
def download(
    pair_id: str,
    format: DownloadFormat = Query(..., description="geojson | shp"),
    layer: ContourLayer = Query(ContourLayer.flood, description="pre | peak | flood | receded"),
    repo: DataRepository = Depends(get_repository),
):
    _get_pair_or_404(repo, pair_id)
    try:
        masks = repo.get_or_compute_masks(pair_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=422, detail=f"Не найдены исходные растры пары: {exc}")

    mask, profile = masks[layer.value]

    if format == DownloadFormat.geojson:
        from ...geoutils.vectorize import mask_to_geojson

        geojson = mask_to_geojson(
            mask,
            profile,
            feature_type=layer.value,
            fallback_pixel_area_ha=repo.cfg.pixel_area_ha_fallback,
        )
        return JSONResponse(
            content=geojson,
            headers={"Content-Disposition": f'attachment; filename="{pair_id}_{layer.value}.geojson"'},
        )

    # format == shp
    gdf = mask_to_geodataframe(mask, profile, layer.value, repo.cfg.pixel_area_ha_fallback)
    out_path = Path(tempfile.gettempdir()) / f"{pair_id}_{layer.value}.zip"
    geodataframe_to_zipped_shapefile(gdf, out_path)
    return FileResponse(out_path, media_type="application/zip", filename=out_path.name)


@router.post("/submission/build")
def build_submission(repo: DataRepository = Depends(get_repository)):
    """Служебный эндпоинт: прогоняет все пары из sample_submission.csv
    и формирует submission.csv. Пары, отсутствующие в реестре, пишутся с нулями. """
    path = repo.build_full_submission()
    return {"submission_csv": str(path)}


@router.get("/submission")
def get_submission(repo: DataRepository = Depends(get_repository)) -> FileResponse:
    """Отдаёт готовый submission.csv. Если файла нет — строит его."""
    path = repo.cfg.submission_csv
    if not path.exists():
        path = repo.build_full_submission()
    return FileResponse(path, media_type="text/csv", filename=path.name)


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}