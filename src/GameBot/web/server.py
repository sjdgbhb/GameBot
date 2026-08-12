"""Web 配置服务器入口 — FastAPI + Vue 3 前端。

启动命令：uv run python -m GameBot.web.server
"""
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from GameBot.web.api.routes import init as init_route
from GameBot.web.api.routes import config as config_route
from GameBot.web.api.routes import hero as hero_route
from GameBot.web.api.routes import schema as schema_route
from GameBot.web.api.routes import task as task_route


def create_app() -> FastAPI:
    """创建 FastAPI 应用，注册路由和静态文件。"""
    app = FastAPI(title="GameBot 配置服务器", version="1.0.0")

    # CORS — 开发时前端 Vite dev server 运行在不同端口
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册 API 路由
    app.include_router(init_route.router, prefix="/api")
    app.include_router(config_route.router, prefix="/api")
    app.include_router(hero_route.router, prefix="/api")
    app.include_router(schema_route.router, prefix="/api")
    app.include_router(task_route.router, prefix="/api")

    # 静态文件 — 前端构建产物
    frontend_dist = Path(__file__).parent / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "GameBot.web.server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
