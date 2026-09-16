"""派生值解析 — 从源配置推导运行时字段的公共逻辑。

被 Config.load_task 与组队路径（team/base.py）等非标准加载路径共用，
避免同一段推导逻辑在多处手写复制。

派生结果写入配置字典（war3.bind / kk.bind / hero.inventory 的 item_id 等），
provenance 中以 "<派生:xxx>" 标记来源。
"""

import copy
import logging
from typing import Optional

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
    """将 inventory 条目中的 item（物品名）解析为 item_id（原地修改）。

    支持用物品名替代数字 ID，提升配置可读性。已有 item_id 的条目不受影响。

    :param inventory: 物品栏条目列表（原地修改）
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


def derive_bind_mode(task_node: Optional[dict], ns_cfg: dict) -> str:
    """推导窗口绑定模式。

    优先级：任务段 bind_mode > 任务段 target_player 非空（多开认领必须后台）>
    命名空间级 bind_mode（war3.bind_mode / kk.bind_mode）> "foreground" 默认。
    """
    if isinstance(task_node, dict):
        if task_node.get("bind_mode"):
            return task_node["bind_mode"]
        if task_node.get("target_player"):
            # 多开认领（target_player 非空）必须后台绑定，自动推导无需显式配置
            return "background"
    return ns_cfg.get("bind_mode", "foreground")


def select_bind_cfg(ns_cfg: dict, mode: str) -> str:
    """按 mode 把 ns_cfg["bind"] 解析为 bind_foreground/bind_background（原地写）。

    解析结果记录 bind_mode 字段，供业务层判断（如后台时跳过活动窗口检测）。

    :return: 来源键名（"bind_foreground" / "bind_background"）；无源配置返回 ""
    """
    src_key = "bind_background" if mode == "background" else "bind_foreground"
    src_cfg = ns_cfg.get(src_key)
    if src_cfg is None:
        return ""
    ns_cfg["bind"] = copy.deepcopy(src_cfg)
    ns_cfg["bind"]["bind_mode"] = mode
    return src_key


def apply_bind_mode(config: dict, task_node: Optional[dict] = None, force_mode: str = None):
    """对 config 的 war3/kk 命名空间执行 bind 解析（原地写 ns.bind）。

    :param config: 合并后的配置字典（含 war3/kk 命名空间节点）
    :param task_node: 任务自身节点（[this] 段；提供 bind_mode/target_player 任务级覆盖）
    :param force_mode: 强制模式（"foreground"/"background"），
        组队多成员强转后台等场景使用
    """
    for ns in ("war3", "kk"):
        ns_cfg = config.get(ns)
        if not isinstance(ns_cfg, dict):
            continue
        mode = force_mode or derive_bind_mode(task_node, ns_cfg)
        select_bind_cfg(ns_cfg, mode)
