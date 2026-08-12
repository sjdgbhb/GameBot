"""英雄管理接口 — 导出/导入/物品栏保存。"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from ..models import (
    HeroImportBatchRequest,
    HeroImportBatchResponse,
    OkResponse,
    SaveHeroInventoryRequest,
)
from .. import services

router = APIRouter()


@router.get("/hero_export/{hero_id}", response_class=PlainTextResponse)
async def export_hero(hero_id: str):
    """导出英雄 TOML 配置文件内容。"""
    try:
        content = services.export_hero_config(hero_id)
        return PlainTextResponse(content, media_type="text/plain; charset=utf-8")
    except ValueError:
        raise HTTPException(status_code=400, detail="非法英雄 ID")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="英雄配置不存在")


@router.post("/save_hero_inventory", response_model=OkResponse)
async def save_hero_inventory(req: SaveHeroInventoryRequest):
    """保存英雄默认物品栏到 TOML 文件。"""
    try:
        services.save_hero_inventory(req.hero_id, req.inventory)
        return OkResponse(ok=True)
    except Exception as e:
        return OkResponse(ok=False, error=str(e))


@router.post("/hero_import_batch", response_model=HeroImportBatchResponse)
async def hero_import_batch(req: HeroImportBatchRequest):
    """批量导入英雄配置文件。"""
    if not req.heroes:
        return HeroImportBatchResponse(ok=False, errors=["heroes 列表为空"])
    result = services.import_hero_batch(req.heroes)
    return HeroImportBatchResponse(
        ok=len(result["errors"]) == 0,
        saved=result["saved"],
        errors=result["errors"],
    )
