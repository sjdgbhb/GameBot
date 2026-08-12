"""初始化接口 — GET /api/init。"""
from fastapi import APIRouter

from ..models import InitResponse
from .. import services

router = APIRouter()


@router.get("/init", response_model=InitResponse)
async def get_init():
    """返回任务列表、英雄列表、物品定义、用户配置。"""
    return InitResponse(
        tasks=services.load_tasks(),
        heroes=services.load_heroes(),
        items=services.load_items(),
        farmable_items=services.load_farmable_items(),
        commands=services.load_commands(),
        configs=services.load_user_configs(),
    )
