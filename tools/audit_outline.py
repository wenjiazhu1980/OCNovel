# -*- coding: utf-8 -*-
"""大纲全局审计器 CLI - 检测剧情不闭环 / 伏笔不回收等结构性缺陷

审计核心逻辑在 src/generators/outline/outline_auditor.py（流水线与本 CLI 共用）；
本文件仅做命令行封装：读取 outline.json、跑审计、渲染报告 / JSON、可选 LLM 复核。

规则：
    O1 伏笔埋设-回收配对   —— 找全书埋设却未回收的悬挂伏笔
    O2 命名实体生命线断裂   —— 找前期高频登场、中途断崖消失的角色/线索
    O3 系统任务闭环         —— 找"系统发布任务"后无对应"任务完成"的事件
    O4 人物身份一致性       —— 找同名角色被赋予互斥身份（重名/设定漂移）
    O5 结局回收率           —— 统计全书埋设/回收比与悬挂率
    O3-LLM（--llm）         —— 用 LLM 对任务闭环做语义裁决，识破母题复用导致的假闭环

使用示例
========
基础审计::

    python tools/audit_outline.py --outline data/output/outline.json

叠加 LLM 语义复核::

    python tools/audit_outline.py --outline data/output/outline.json --llm --config config.json

JSON 输出（便于脚本消费）::

    python tools/audit_outline.py --outline data/output/outline.json --json

退出码
======
- 0: 未发现 fatal 级问题
- 1: 发现 fatal 级问题（剧情未闭环 / 重名冲突等）
- 2: 参数错误 / 文件无法读取
"""

from __future__ import annotations

import argparse
import json as _json
import sys
from pathlib import Path
from typing import Dict, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 审计核心从 src 层导入（保证流水线与 CLI 共用同一实现，且可被打包）
from src.generators.outline.outline_auditor import (  # noqa: E402
    Finding,
    audit_foreshadowing,
    audit_entities,
    audit_task_closure,
    audit_identity,
    audit_recovery_rate,
    llm_review_task_closure,
    llm_review_task_closure_with_stats,
    run_audit,
    serialize_finding,
    _ALL_RULES,
)

_SEV_TAG = {"fatal": "✗", "warning": "!", "info": "·"}


def _load_chapters(path: str) -> List[dict]:
    data = _json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("outline 顶层应为章节列表 (list)")
    return data


def _build_content_model(config_path: str):
    """从 config.json 构造 content_model（延迟 import，避免模块级副作用）。"""
    from main import create_model
    from src.config.config import Config
    config = Config(config_path)
    return create_model(config.get_model_config("content_model"))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="大纲全局审计：检测剧情不闭环 / 伏笔不回收等结构性缺陷",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--outline", "-o", required=True, help="outline.json 路径")
    parser.add_argument("--json", action="store_true", help="JSON 输出（便于脚本消费）")
    parser.add_argument("--llm", action="store_true",
                        help="叠加 LLM 语义复核任务闭环（需同时提供 --config）")
    parser.add_argument("--config", help="config.json 路径（--llm 时构造模型用）")
    args = parser.parse_args(argv)

    if args.llm and not args.config:
        print("错误：--llm 需要同时提供 --config <config.json>", file=sys.stderr)
        return 2

    try:
        chapters = _load_chapters(args.outline)
    except Exception as e:
        print(f"错误：无法读取大纲文件：{e}", file=sys.stderr)
        return 2

    findings = run_audit(chapters)
    llm_stats = None
    if args.llm:
        try:
            model = _build_content_model(args.config)
        except Exception as e:
            print(f"错误：构造模型失败：{e}", file=sys.stderr)
            return 2
        llm_result = llm_review_task_closure_with_stats(chapters, model)
        llm_stats = llm_result.stats
        findings.extend(llm_result.findings)

    fatal = [f for f in findings if f.severity == "fatal"]
    warning = [f for f in findings if f.severity == "warning"]
    n_chapters = len([c for c in chapters if c])

    if args.json:
        out = {
            "outline": args.outline,
            "chapters": n_chapters,
            "total_findings": len(findings),
            "fatal": len(fatal),
            "warning": len(warning),
            "llm_enabled": bool(args.llm),
            "llm_stats": llm_stats,
            "findings": [serialize_finding(f) for f in findings],
        }
        print(_json.dumps(out, ensure_ascii=False, indent=2))
        return 1 if fatal else 0

    print(f"大纲审计报告：{args.outline}")
    print(f"共 {n_chapters} 章，发现 {len(findings)} 处问题（fatal {len(fatal)}）")
    if llm_stats is not None:
        print(
            "LLM复核统计："
            f"发布任务 {llm_stats.get('published_tasks', 0)} 个，"
            f"实际调用 {llm_stats.get('llm_calls', 0)} 次，"
            f"发现 {llm_stats.get('llm_findings', 0)} 处，"
            f"调用失败 {llm_stats.get('llm_call_failures', 0)} 次"
        )
    print("=" * 60)
    by_rule: Dict[str, List[Finding]] = {}
    for f in findings:
        by_rule.setdefault(f.rule_id, []).append(f)
    base_rules = [rid for rid, _ in _ALL_RULES]
    rule_order = base_rules + [r for r in sorted(by_rule) if r not in base_rules]
    for rid in rule_order:
        fs = by_rule.get(rid, [])
        if not fs:
            continue
        print(f"\n[{rid}] {fs[0].title}（{len(fs)} 项）")
        for f in fs[:30]:
            print(f"  {_SEV_TAG.get(f.severity, '-')} {f.message}")
        if len(fs) > 30:
            print(f"  …另有 {len(fs) - 30} 项（用 --json 查看全部）")
    print()
    print(f"[修改必要性]: {'需要修改' if fatal else '可选优化'}")
    return 1 if fatal else 0


if __name__ == "__main__":
    sys.exit(main())
