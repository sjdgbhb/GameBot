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
