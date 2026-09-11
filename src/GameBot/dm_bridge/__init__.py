"""dm_bridge — 大漠插件 32 位 RPC 桥接子进程。

64 位主环境（Python 3.12）无法创建 dm.dmsoft COM 对象（仅 32 位可用），
本包在 32 位 Python 3.8（.venv-dm）中常驻运行，通过 stdin/stdout 行式 JSON
向主进程暴露大漠 COM 原语调用（与 inference/worker.py 相同的通信模式，方向相反）。

协议：
    启动就绪：{"ready": true, "version": "3.1233"} 或 {"ready": false, "error": "..."}
    请求：    {"id": 1, "method": "com", "name": "FindPic", "args": [...]}
              {"id": 2, "method": "ping"} / {"id": 3, "method": "quit"}
    响应：    {"id": 1, "ok": true, "result": ...}
              {"id": 1, "ok": false, "error": "...", "traceback": "..."}

设计约束：
- 自包含：仅依赖 stdlib + pywin32，不导入 GameBot 其他模块（--register 除外），
  便于独立打包和最小化 .venv-dm 依赖。
- 单线程：所有 COM 调用在主线程串行执行，天然满足大漠 COM 线程亲和要求。
- 多开：每个任务/成员进程独占一个 dm_bridge 子进程（1 桥接 = 1 COM 对象 = 1 窗口绑定），
  互不干扰；stdin EOF（父进程退出）时自动退出，不留孤儿进程。
"""
