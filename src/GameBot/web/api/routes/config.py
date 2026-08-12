"""配置保存接口 — POST /api/save。"""
from fastapi import APIRouter

from ..models import OkResponse, SaveConfigRequest
from .. import services

router = APIRouter()


@router.post("/save", response_model=OkResponse)
async def save_config(req: SaveConfigRequest):
    """保存用户配置到 user_configs.json。"""
    try:
        services.save_user_configs(req.configs)
        return OkResponse(ok=True)
    except Exception as e:
        return OkResponse(ok=False, error=str(e))
