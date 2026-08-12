"""Pydantic 请求/响应模型定义。"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---- 基础数据模型 ----

class TaskInfo(BaseModel):
    id: str
    short_id: str
    category: str
    name: str
    icon: str
    description: str = ""
    configurable: bool = False


class HeroInfo(BaseModel):
    id: str
    name: str
    floor_key: str = "P"
    inventory: List[Dict[str, Any]] = Field(default_factory=list)
    skills: List[Dict[str, Any]] = Field(default_factory=list)


class ItemDef(BaseModel):
    id: int
    name: str


class RunningTaskInfo(BaseModel):
    id: str
    pid: int


# ---- API 响应模型 ----

class CommandDef(BaseModel):
    key: str
    cmd: str


class InitResponse(BaseModel):
    tasks: List[TaskInfo]
    heroes: List[HeroInfo]
    items: List[ItemDef]
    farmable_items: List[str]
    commands: List[CommandDef] = Field(default_factory=list)
    configs: Dict[str, Any]


class SchemaResponse(BaseModel):
    id: str
    name: str
    description: str = ""
    sections: List[Dict[str, Any]]
    defaults: Dict[str, Any] = Field(default_factory=dict)


class RunningTasksResponse(BaseModel):
    tasks: List[RunningTaskInfo]


class OkResponse(BaseModel):
    ok: bool = True
    error: str = ""


class StartTaskResponse(BaseModel):
    ok: bool = True
    pid: int = 0
    log: str = ""
    error: str = ""
    running: bool = False


class HeroImportBatchResponse(BaseModel):
    ok: bool = True
    saved: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


# ---- 请求模型 ----

class SaveConfigRequest(BaseModel):
    # 动态键值对，不强制约束具体结构
    configs: Dict[str, Any]


class SaveHeroInventoryRequest(BaseModel):
    hero_id: str
    inventory: List[Dict[str, Any]] = Field(default_factory=list)


class HeroImportBatchRequest(BaseModel):
    heroes: List[Dict[str, Any]]
