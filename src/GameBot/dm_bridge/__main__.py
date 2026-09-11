"""dm_bridge 入口 — 32 位 Python 3.8（.venv-dm）运行。

用法：
    serve 模式（默认）：由 64 位主进程（DmBridgeClient）通过管道拉起，
        配置经环境变量 GAMEBOT_DM_BRIDGE_CONFIG（JSON）传入。
    --register：以管理员身份注册 dm.dll（一次性，会自动弹 UAC 提权），
        手动执行：.venv-dm\\Scripts\\python.exe -m GameBot.dm_bridge --register
"""

import json
import os
import sys

# 直接以文件方式运行（非 -m）或提权重启时自愈 sys.path：
# __main__.py → dm_bridge → GameBot → src
_SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


def _print_line(payload):
    print(json.dumps(payload, ensure_ascii=True), flush=True)


def _serve():
    """RPC 服务模式：创建 COM → 打印就绪行 → 进入请求循环。"""
    from GameBot.dm_bridge.server import BridgeServer, create_dm, set_dpi_aware

    set_dpi_aware()

    import pythoncom

    pythoncom.CoInitialize()

    cfg = {}
    raw = os.environ.get("GAMEBOT_DM_BRIDGE_CONFIG", "")
    if raw:
        try:
            cfg = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as e:
            _print_line({"ready": False, "error": "GAMEBOT_DM_BRIDGE_CONFIG 非 JSON: %s" % e})
            return 1

    try:
        dm, ver = create_dm(cfg)
    except (OSError, RuntimeError) as e:
        _print_line({"ready": False, "error": str(e)})
        return 1

    _print_line({"ready": True, "version": ver})
    BridgeServer(dm).serve_forever()
    return 0


def _register():
    """注册模式：复用 DmRegistrar（含 UAC 自动提权），从项目配置读取 DLL 路径与版本。"""
    from GameBot.config import config
    from GameBot.runner.driver.registrar import DmRegistrar

    dm_cfg = config.get("dm", {})
    version = dm_cfg.get("version", "3.1233")
    dll_path = config.project_root / dm_cfg.get("dll_path", "external/dm") / "dm.dll"
    DmRegistrar.ensure_registered(version, dll_path)
    print("大漠注册完成，版本 %s" % version)


def main():
    if sys.maxsize > 2**32:
        _print_line({"ready": False, "error": "dm_bridge 需要 32 位 Python（大漠 COM 要求），请使用 .venv-dm 环境"})
        sys.exit(1)
    if "--register" in sys.argv:
        _register()
        return
    sys.exit(_serve())


if __name__ == "__main__":
    main()
