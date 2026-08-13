"""任务启停接口 — POST /api/start/{task_id}、GET /api/running。"""
from fastapi import APIRouter, HTTPException

from .. import services
from ..models import RunningTasksResponse, StartTaskResponse

router = APIRouter()


@router.post("/start/{task_id}", response_model=StartTaskResponse)
async def start_task(task_id: str):
    """启动任务子进程。"""
    try:
        result = services.start_task(task_id)
        return StartTaskResponse(**result)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="未找到可执行的任务脚本")
    except Exception as e:
        return StartTaskResponse(ok=False, error=str(e))


@router.get("/running", response_model=RunningTasksResponse)
async def get_running():
    """获取正在运行的任务列表。"""
    tasks = services.get_running_tasks()
    return RunningTasksResponse(tasks=tasks)
