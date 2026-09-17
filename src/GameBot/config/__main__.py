"""配置系统 CLI — 配置排障与审计工具。

用法（主环境 .venv）：

    python -m GameBot.config order <配置名>                      # 打印依赖闭包的线性加载顺序
    python -m GameBot.config explain <配置名> <dot路径>          # 查某个键的值与写入来源链
    python -m GameBot.config dump <配置名> [--annotate] [--out 文件]  # 导出合并后的有效配置
    python -m GameBot.config lint                                # 结构校验全部 TOML（不执行任务）
    python -m GameBot.config new <配置名>                        # 生成新任务/变体配置模板

示例：

    python -m GameBot.config explain war3.jiubing2.tasks.endless.endless_善木木 hero.shard.use_index
    python -m GameBot.config dump war3.jiubing2.tasks.endless.endless_善木木 --out merged_cfg.json
    python -m GameBot.config dump war3.jiubing2.tasks.endless.endless_善木木 --annotate

provenance 来源名说明：
- 配置名（如 war3.jiubing2.tasks.endless.endless）：对应 config/data/ 下的 TOML 文件
- user_configs.json：用户覆盖层写入
- <派生:xxx>：引擎派生步骤写入（bind 选择、inventory_slots 注入、物品名→item_id 解析）
"""

import argparse
import json
import sys

from GameBot.config import config


def _short(source: str) -> str:
    """来源名缩短显示：完整配置名取最后一段 + .toml；标记类来源原样保留。"""
    if source.startswith("<") or source.startswith("user_configs"):
        return source
    return source.split(".")[-1] + ".toml"


def _lookup(node, dot_path: str):
    """按 dot 路径从配置字典取值，返回 (存在?, 值)。"""
    for key in dot_path.split("."):
        if isinstance(node, dict) and key in node:
            node = node[key]
        else:
            return False, None
    return True, node


def _flatten(node, prefix: str = ""):
    """把嵌套 dict 展开为 (dot_path, 叶子值) 序列。"""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _flatten(v, f"{prefix}.{k}" if prefix else k)
    else:
        yield prefix, node


def _cmd_order(config_name: str) -> int:
    order = []
    config._resolve_order(config_name, order, [], set())
    print(f"{config_name} 的依赖闭包加载顺序（先 → 后，后者覆盖前者）：")
    for i, name in enumerate(order, 1):
        print(f"  {i:2d}. {config._file_path_for(name)}")
    return 0


def _cmd_explain(config_name: str, dot_path: str) -> int:
    result = config.load_task(config_name)
    prov = config.get_provenance(config_name)

    found, value = _lookup(result, dot_path)
    if found:
        print(f"{dot_path} = {json.dumps(value, ensure_ascii=False)}")
    else:
        print(f"{dot_path}: 有效配置中不存在该路径")

    prefix = dot_path + "."
    # 自身与子路径：路径被直接写入/被下级覆盖的记录
    entries = {p: chain for p, chain in prov.items() if p == dot_path or p.startswith(prefix)}
    # 祖先路径：该值随某个上层键整表写入（如 hero 浅合并记到 hero.shard 粒度）
    ancestors = {p: chain for p, chain in prov.items() if dot_path.startswith(p + ".")}
    if not entries and not ancestors:
        if found:
            print("无来源记录（该值由合并后处理写入，或未走标准合并路径）")
        return 1 if not found else 0

    print("来源链（先 → 后，后者覆盖前者）：")
    for p, chain in sorted(ancestors.items()):
        chain_str = " → ".join(_short(s) for s in chain)
        suffix = f"   ← 生效: {_short(chain[-1])}" if len(chain) > 1 else ""
        print(f"  {p} (经上层键写入): {chain_str}{suffix}")
    for p, chain in sorted(entries.items()):
        chain_str = " → ".join(_short(s) for s in chain)
        suffix = f"   ← 生效: {_short(chain[-1])}" if len(chain) > 1 else ""
        label = p if p == dot_path else f"  {p}"
        print(f"  {label}: {chain_str}{suffix}")
    return 0


def _prov_lookup(prov: dict, dot_path: str):
    """查 dot_path 的来源链：最近祖先路径（上层键整表写入）+ 本路径自身的写入记录拼接。"""
    parts = dot_path.split(".")
    ancestor_chain = []
    for i in range(len(parts) - 1, 0, -1):
        ancestor = ".".join(parts[:i])
        if ancestor in prov:
            ancestor_chain = prov[ancestor]
            break
    own_chain = prov.get(dot_path, [])
    # 拼接去重（保持写入顺序）：祖先链是"随整表写入"的来源，自身链是直接写入/派生记录
    chain = list(ancestor_chain)
    for s in own_chain:
        if not chain or chain[-1] != s:
            chain.append(s)
    return chain or None


def _cmd_dump(config_name: str, annotate: bool, out: str) -> int:
    result = config.load_task(config_name)
    if annotate:
        # 展平为 dot 路径列表并标注来源链（比裸 JSON 更可读）；
        # 来源记录是整表写入粒度，逐行回溯最近祖先路径取来源
        prov = config.get_provenance(config_name)
        for path, value in sorted(_flatten(result)):
            chain = _prov_lookup(prov, path)
            src = f"   # {' → '.join(_short(s) for s in chain)}" if chain else ""
            print(f"{path} = {json.dumps(value, ensure_ascii=False)}{src}")
        return 0

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"已写入 {out}")
    else:
        print(text)
    return 0


# ── lint / new ──────────────────────────────────────────────

_TASK_PREFIX = "war3.jiubing2.tasks."


def _config_names(config_dir):
    """枚举 data/ 下所有 TOML 对应的配置名（标准点路径；回退布局的短名也可加载，
    lint 统一按完整路径名处理，如 war3/war3.toml → war3.war3）。"""
    names = {}
    for f in sorted(config_dir.rglob("*.toml")):
        parts = list(f.relative_to(config_dir).with_suffix("").parts)
        names[".".join(parts)] = f
    return names


def _has_non_ascii(text: str) -> bool:
    return any(ord(ch) > 127 for ch in text)


def _section_paths(node, prefix=""):
    """枚举 dict 中"段节点"路径：含至少一个标量/列表直接子键的 dict。
    （只含 dict 子键的是结构节点，不算段。）"""
    if not isinstance(node, dict):
        return
    has_leaf = any(not isinstance(v, dict) for v in node.values())
    if has_leaf:
        yield prefix
    for k, v in node.items():
        if isinstance(v, dict):
            yield from _section_paths(v, f"{prefix}.{k}" if prefix else k)


def _namespaced_section_paths(raw):
    """文件展开后的命名空间根下的段节点路径集合（绝对寻址/自身段都算）。"""
    from GameBot.config.system.base import NAMESPACE_ROOTS

    result = set()
    for root in NAMESPACE_ROOTS:
        sub = raw.get(root)
        if isinstance(sub, dict):
            result.update(_section_paths(sub, root))
    return result


def _cmd_lint() -> int:
    from GameBot.config import ConfigurationError
    from GameBot.config.system.base import NAMESPACE_ROOTS

    config_dir = config.config_dir
    names = _config_names(config_dir)
    findings = []  # (级别, 文件, 消息)

    # 1) 未登记的一级条目
    for entry in config_dir.iterdir():
        name0 = entry.name if entry.is_dir() else (entry.stem if entry.suffix == ".toml" else None)
        if name0 and name0 not in NAMESPACE_ROOTS:
            findings.append(
                ("错误", entry.name, "未登记的一级命名空间条目；"
                 "其顶层键会提升为共享键。请登记到 base.py 的 NAMESPACE_ROOTS")
            )

    for name, path in names.items():
        rel = path.name
        # 2) 解析 + 依赖展开（含 extends 声明、循环依赖、旧格式自身路径拦截）
        try:
            order = []
            config._resolve_order(name, order, [], set())
            raw = config._load_file(name)
        except ConfigurationError as e:
            findings.append(("错误", rel, str(e)))
            continue
        except Exception as e:  # TOML 语法错误等
            findings.append(("错误", rel, f"解析失败: {e}"))
            continue

        extends = raw.get("extends", [])
        # 3) extends 分层：低层文件不得 extends tasks.*
        for dep in extends:
            if dep.startswith(_TASK_PREFIX) and not name.startswith(_TASK_PREFIX):
                findings.append(("错误", rel, f"低层配置不应 extends 任务层 {dep}"))

        # 4) 变体约定：<基任务>_<玩家名>（后缀含非 ASCII，如玩家名）应只 extends 同组基任务
        leaf = name.split(".")[-1]
        if name.startswith(_TASK_PREFIX) and "_" in leaf:
            suffix = leaf.rsplit("_", 1)[-1]
            if _has_non_ascii(suffix):
                group = name.rsplit(".", 1)[0]
                base = None
                stem = leaf
                while "_" in stem:
                    stem = stem[: stem.rfind("_")]
                    cand = f"{group}.{stem}"
                    if config._file_path_for(cand).exists():
                        base = cand
                        break
                if base is None:
                    findings.append(("警告", rel, f"变体名 {leaf} 在同组找不到基任务文件"))
                elif extends != [base]:
                    findings.append(("警告", rel, f"变体应只 extends 基任务 [{base}]，当前 {extends}"))

        # 5) 绝对寻址段目标存在性：非自身路径的段应与闭包内其他文件的段路径有交集
        #    （某段仅由本文件凭空创建 → 疑似笔误/补丁落空）
        if name.startswith(_TASK_PREFIX):
            others = set()
            for other in order:
                if other == name:
                    continue
                others.update(_namespaced_section_paths(config._load_file(other)))
            own_prefix = name + "."
            for sec in _namespaced_section_paths(raw):
                if sec == name or sec.startswith(own_prefix):
                    continue
                # 命中条件：其他文件写了同段或更深的段（证明节点存在），
                # 或 sec 的直接父节点是其他文件的段（在已有节点下新增子表）；
                # 不允许浅层祖先（war3 根段存在于所有闭包，会让检查失效）
                hit = any(
                    s == sec
                    or s.startswith(sec + ".")
                    or (sec.startswith(s + ".") and s.count(".") >= sec.count(".") - 1)
                    for s in others
                )
                if not hit:
                    findings.append(
                        ("警告", rel, f"绝对寻址段 [{sec}] 在闭包中无对应节点；"
                         "若意图是给已有节点打补丁，请检查路径是否笔误")
                    )

    if not findings:
        print(f"lint 通过：{len(names)} 个配置文件无问题")
        return 0
    for level, rel, msg in findings:
        print(f"[{level}] {rel}: {msg}")
    n_err = sum(1 for lv, _, _ in findings if lv == "错误")
    print(f"\n{len(findings)} 项发现（错误 {n_err}，警告 {len(findings) - n_err}）")
    return 1 if n_err else 0


def _cmd_new(config_name: str) -> int:
    if not config_name.startswith(_TASK_PREFIX):
        print(f"new 仅支持 {_TASK_PREFIX}* 任务配置，收到: {config_name}")
        return 1
    filepath = config._file_path_for(config_name)
    if filepath.exists():
        print(f"文件已存在: {filepath}")
        return 1

    # 变体判定：<基>_<后缀> 且同目录存在基任务文件
    leaf = config_name.split(".")[-1]
    group = config_name.rsplit(".", 1)[0]
    base = None
    stem = leaf
    while "_" in stem:
        stem = stem[: stem.rfind("_")]
        cand = f"{group}.{stem}"
        if config._file_path_for(cand).exists():
            base = cand
            break

    if base:
        content = f'''# 变体配置：{leaf}（差异字段覆盖基任务，extends 基任务即可）
extends = ["{base}"]

[this]
target_player = ""      # 多开认领：非空自动推导 bind_mode=background
# bind_mode = "background"  # 需要显式控制时取消注释

# 常用差异字段（按需添加）：
# [float_window]
# y = 500               # 错开浮窗位置
'''
    else:
        content = '''extends = ["war3.jiubing2", "kk"]

[this]
name = ""               # 任务显示名（浮窗/日志）
bind_mode = "foreground"  # foreground / background；变体用 target_player 自动切后台

# 物品栏（按需）：
# [hero]
# inventory = [{{slot = 0, item = "物品名"}}]   # 物品名见 jiubing2.toml 的 items
'''
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content, encoding="utf-8")
    print(f"已创建 {filepath}" + (f"（变体，extends {base}）" if base else ""))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m GameBot.config", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("order", help="打印依赖闭包的线性加载顺序")
    p.add_argument("config_name")

    p = sub.add_parser("explain", help="查某个键的值与写入来源链")
    p.add_argument("config_name")
    p.add_argument("path", help="dot 路径，如 hero.shard.use_index")

    p = sub.add_parser("dump", help="导出合并后的有效配置")
    p.add_argument("config_name")
    p.add_argument("--annotate", action="store_true", help="展平为 dot 路径并标注来源链")
    p.add_argument("--out", default="", help="输出到文件（默认打印到 stdout）")

    sub.add_parser("lint", help="结构校验全部 TOML（不执行任务）")

    p = sub.add_parser("new", help="生成新任务/变体配置模板")
    p.add_argument("config_name", help="如 war3.jiubing2.tasks.others.my_task 或 ...endless_玩家名")

    args = parser.parse_args()
    if args.cmd == "order":
        return _cmd_order(args.config_name)
    if args.cmd == "explain":
        return _cmd_explain(args.config_name, args.path)
    if args.cmd == "dump":
        return _cmd_dump(args.config_name, args.annotate, args.out)
    if args.cmd == "lint":
        return _cmd_lint()
    if args.cmd == "new":
        return _cmd_new(args.config_name)
    return 1


if __name__ == "__main__":
    sys.exit(main())
