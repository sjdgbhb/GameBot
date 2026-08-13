"""任务 schema 接口 — GET /api/schema/{task_id}。"""

from fastapi import APIRouter, HTTPException

from .. import services
from ..models import SchemaResponse

router = APIRouter()


@router.get("/schema/{task_id}", response_model=SchemaResponse)
async def get_schema(task_id: str):
    """返回指定任务的表单 schema 及默认值。"""
    schema = services.get_task_schema(task_id)
    if schema is None:
        raise HTTPException(status_code=404, detail="未找到该任务的 schema")
    return SchemaResponse(**schema)
