"""合并构建 — 按加载顺序合并配置、深度合并、英雄互斥处理、来源追踪（provenance）。"""

import copy
from typing import Dict, List


class ConfigBuilderMixin:
    """Config 的合并构建 mixin。

    依赖 self._load_file()、self._split_sections()（ConfigLoaderMixin 提供）、
    self._EXCLUSIVE_NAMESPACES。
    """

    def _build(self, order: List[str], prov: Dict[str, List[str]] = None) -> dict:
        """按加载顺序合并配置，生成类 JSON 结果（规则 1/3/4）。

        - 可继承节点深度合并到顶层（同名字段递归合并，未覆盖的字段从父配置继承）；
        - [hero] 特殊处理：浅合并顶层子键（skills/inventory/stigma 等），
          每个子键完全覆盖（不递归），任务配置只写 inventory 不会丢失 skills 等属性；
        - 命名空间节点深度合并到各自命名空间路径下（不同子路径可共存）；
        - 互斥命名空间（heroes）：后加载的英雄整体替换前一英雄贡献的可继承节点，
          保证同一时刻只有一个英雄的配置生效。

        :param order: 线性加载顺序（配置名列表）
        :param prov: 可选 provenance 输出字典：dot_path -> [写入来源链]
            （按写入顺序追加，末位为生效来源）；None 则不记录
        :return: 合并后的配置字典
        """
        result: dict = {}
        # 互斥命名空间追踪：命名空间根 -> (当前持有者配置名, 已写入的顶层键集合)
        exclusive_owner: Dict[str, tuple] = {}
        for name in order:
            raw = self._load_file(name)
            inheritable, namespaced = self._split_sections(raw)
            # 检查配置名是否属于某个互斥命名空间（完整前缀匹配）
            exclusive_ns = None
            for ns in self._EXCLUSIVE_NAMESPACES:
                if name == ns or name.startswith(ns + "."):
                    exclusive_ns = ns
                    break
            if exclusive_ns is not None:
                # 互斥处理：新英雄出现时，先清除前一英雄写入的所有可继承节点
                prev = exclusive_owner.get(exclusive_ns)
                if prev is not None and prev[0] != name:
                    for key in prev[1]:
                        result.pop(key, None)
                        self._prov_drop(prov, key)
                # 记录当前英雄及其贡献的键集合，供下一英雄清理用
                exclusive_owner[exclusive_ns] = (name, set(inheritable))
                for key, value in inheritable.items():
                    result[key] = copy.deepcopy(value)
                    self._prov_mark(prov, key, name)
            else:
                # 普通可继承节点：深度合并到顶层（未覆盖的字段从父配置继承）
                for key, value in inheritable.items():
                    # [hero] 浅合并：合并顶层子键（英雄的 skills/inventory/stigma 等），
                    # 每个子键完全覆盖（不递归），任务配置只写 inventory 不会丢失 skills 等属性。
                    if key == "hero" and isinstance(value, dict) and isinstance(result.get("hero"), dict):
                        merged_hero = copy.deepcopy(result["hero"])
                        for sub_key, sub_val in value.items():
                            merged_hero[sub_key] = (
                                copy.deepcopy(sub_val) if isinstance(sub_val, (dict, list)) else sub_val
                            )
                            self._prov_mark(prov, f"hero.{sub_key}", name)
                        result["hero"] = merged_hero
                    elif key in result and isinstance(result[key], dict) and isinstance(value, dict):
                        self._deep_merge(result[key], value, _path=key, _prov=prov, _source=name)
                    else:
                        result[key] = copy.deepcopy(value) if isinstance(value, (dict, list)) else value
                        self._prov_mark(prov, key, name)
            # 命名空间节点：深度合并到各自路径下（不同子路径可共存，同路径后加载覆盖先加载）
            self._deep_merge(result, namespaced, _prov=prov, _source=name)
        # 收集 extends 映射，供 get_task_view 沿 extends 链合并任务视图
        extends_map = {}
        for name in order:
            raw = self._load_file(name)
            extends_map[name] = raw.get("extends", [])
        result["_extends"] = extends_map
        return result

    def _deep_merge(self, base: dict, override: dict, _path: str = "", _prov=None, _source=None):
        """深度合并：override 覆盖 base，base 被原地修改。

        - 两边都是 dict → 递归合并子键；
        - 否则 override 直接覆盖（dict/list 做 deepcopy 避免共享引用）。

        :param _path/_prov/_source: provenance 记录参数（内部使用）；
            _prov 为 None 时纯合并不记录
        """
        for key, value in override.items():
            path = f"{_path}.{key}" if _path else key
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                # 两边都是 dict，递归合并子键
                self._deep_merge(base[key], value, path, _prov, _source)
            else:
                # 非 dict 或新增键，直接覆盖
                base[key] = copy.deepcopy(value) if isinstance(value, (dict, list)) else value
                self._prov_mark(_prov, path, _source)

    @staticmethod
    def _prov_mark(prov, path: str, source):
        """记录 path 的一次写入来源（按写入顺序追加；prov 为 None 时跳过）。"""
        if prov is None or source is None:
            return
        prov.setdefault(path, []).append(source)

    @staticmethod
    def _prov_drop(prov, key: str):
        """删除 key 及其子路径的全部来源记录（英雄互斥清理用；prov 为 None 时跳过）。"""
        if prov is None:
            return
        prefix = key + "."
        for p in [p for p in prov if p == key or p.startswith(prefix)]:
            del prov[p]
