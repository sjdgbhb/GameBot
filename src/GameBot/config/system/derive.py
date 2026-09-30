"""派生值解析 — 从源配置推导运行时字段的公共逻辑。

被 Config.load_task 与非标准加载路径（exe 入口用户覆盖后补解析等）共用，
避免同一段推导逻辑在多处手写复制。

bind 参数表不预写入配置字典，由调用点用 resolve_bind_cfg 按 bind_mode
实时选择；其余派生结果（hero.inventory 的 item_id 等）仍写入配置字典，
provenance 中以 "<派生:xxx>" 标记来源。
"""

import copy
import logging

logger = logging.getLogger(__name__)


def get_task_view(cfg: dict, task_name: str) -> dict:
    """沿 extends 链深合并任务视图（base first, leaf last）。

    变体不写的参数自动从基任务继承；要覆盖则写全路径打到基任务节点。
    只合并 war3.jiubing2.tasks.* 下的任务节点，非任务依赖（war3.jiubing2、kk、
    heroes 等）不参与——它们的配置已在各自命名空间节点中。

    :param cfg: load_task 返回的配置字典（含 _extends 映射）
    :param task_name: 任务全名（如 war3.jiubing2.tasks.endless.endless_善木木）
    :return: 深合并后的任务视图字典；无 extends 信息时返回空字典
    """
    extends_map = cfg.get("_extends", {})
    if not extends_map:
        return {}
    chain = []
    _collect_extends_chain(task_name, extends_map, chain, set())
    # 只合并任务节点（war3.jiubing2.tasks.* 下）
    task_chain = [n for n in chain if n.startswith("war3.jiubing2.tasks.")]
    view: dict = {}
    for name in task_chain:
        node = _get_nested(cfg, name.split("."))
        if isinstance(node, dict):
            _deep_merge(view, node)
    return view


def _collect_extends_chain(name: str, extends_map: dict, chain: list, visited: set):
    """DFS 后序收集 extends 链（依赖在前、自身在后）。"""
    if name in visited:
        return
    visited.add(name)
    for dep in extends_map.get(name, []):
        _collect_extends_chain(dep, extends_map, chain, visited)
    chain.append(name)


def _get_nested(cfg: dict, parts: list):
    """按点路径段列表读取嵌套节点。"""
    node = cfg
    for p in parts:
        node = node.get(p) if isinstance(node, dict) else None
        if node is None:
            return None
    return node


def _deep_merge(base: dict, override: dict):
    """深度合并 override 到 base（原地修改 base）。"""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value) if isinstance(value, (dict, list)) else value


def resolve_item_names(inventory: list, items: list) -> int:
    """将条目中的 item（物品名）解析为 item_id（原地修改）。

    支持用物品名替代数字 ID，提升配置可读性。已有 item_id 的条目不受影响。

    :param inventory: 条目列表（原地修改）
    :param items: 物品定义表（含 id/name 字段，如 jiubing2.toml 的 items）
    :return: 成功解析的条目数
    """
    if not inventory or not items:
        return 0
    name_to_id = {it.get("name", ""): it.get("id") for it in items if it.get("name")}
    resolved = 0
    for entry in inventory:
        if "item_id" not in entry and "item" in entry:
            name = entry["item"]
            item_id = name_to_id.get(name)
            if item_id is not None:
                entry["item_id"] = item_id
                del entry["item"]
                resolved += 1
            else:
                logger.warning(f"物品名 '{name}' 未在物品定义表中找到，请检查 items 配置")
    return resolved


def resolve_action_item_names(tasks_cfg: dict, items: list) -> int:
    """将任务路径点 actions 中 type="item" 条目的 item（物品名）解析为 item_id（原地修改）。

    递归扫描 tasks 配置树中所有含 "actions" 列表的节点；
    只有 type="item" 的条目参与解析（type="skill" 的 skill 是技能名，不受影响）。

    :param tasks_cfg: war3.jiubing2.tasks 命名空间配置 dict
    :param items: 物品定义表（含 id/name 字段）
    :return: 成功解析的条目数
    """
    resolved = 0

    def _walk(node):
        nonlocal resolved
        if isinstance(node, dict):
            actions = node.get("actions")
            if isinstance(actions, list):
                item_acts = [
                    a for a in actions
                    if isinstance(a, dict) and a.get("type") == "item"
                ]
                resolved += resolve_item_names(item_acts, items)
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)

    if isinstance(tasks_cfg, dict):
        _walk(tasks_cfg)
    return resolved


def derive_bind_mode(ns_cfg: dict) -> str:
    """返回命名空间级 bind_mode（war3.bind_mode / kk.bind_mode），默认 "foreground"。

    任务/变体要切换绑定模式，用绝对寻址段直接覆盖命名空间默认
    （文件里写 [war3] / [kk] 下的 bind_mode），任务 [this] 不设 bind_mode。
    """
    return ns_cfg.get("bind_mode", "foreground")


def resolve_bind_cfg(ns_cfg: dict) -> dict:
    """按命名空间级 bind_mode 选择前台/后台绑定参数表（调用时解析）。

    结果附带 bind_mode 供业务层判断（如后台时跳过活动窗口检测）；
    bind_window 只读 display/mouse/keypad/mode/public/bind_delay，忽略该键。

    :param ns_cfg: war3/kk 命名空间配置字典
    :return: 绑定参数表副本；无对应源表时只含 bind_mode
    """
    mode = derive_bind_mode(ns_cfg)
    src_key = "bind_background" if mode == "background" else "bind_foreground"
    bind_cfg = copy.deepcopy(ns_cfg.get(src_key) or {})
    bind_cfg["bind_mode"] = mode
    return bind_cfg


def force_bind_mode(config: dict, mode: str):
    """强制 war3/kk 命名空间的绑定模式（原地写 ns.bind_mode）。

    :param config: 合并后的配置字典（含 war3/kk 命名空间节点）
    :param mode: 强制模式（"foreground"/"background"），
        手动测试脚本等需要强制绑定模式的场景使用
    """
    for ns in ("war3", "kk"):
        ns_cfg = config.get(ns)
        if isinstance(ns_cfg, dict):
            ns_cfg["bind_mode"] = mode
