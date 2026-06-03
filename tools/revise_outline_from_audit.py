# -*- coding: utf-8 -*-
"""根据 outline_audit_report.json 修订 outline.json。

示例：
    python tools/revise_outline_from_audit.py --outline data/output/outline.json --config config.json
    python tools/revise_outline_from_audit.py --outline data/output/outline.json --config config.json --dry-run --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.generators.outline.outline_reviser import revise_outline_file  # noqa: E402


def _build_outline_model(config_path: str):
    """从 config.json 构造 outline_model。"""
    from dotenv import load_dotenv
    from main import create_model
    from src.config.config import Config

    env_path = os.path.join(os.path.dirname(os.path.abspath(config_path)), ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path, override=True)
    config = Config(config_path)
    return create_model(config.get_model_config("outline_model"))


def _parse_rules(raw: Optional[str]) -> Optional[List[str]]:
    if not raw:
        return None
    rules = [item.strip() for item in raw.split(",") if item.strip()]
    return rules or None


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="根据大纲审计报告，对 outline.json 做必要修订",
    )
    parser.add_argument("--outline", "-o", required=True, help="outline.json 路径")
    parser.add_argument("--audit-report", "-a", help="outline_audit_report.json 路径，默认与 outline 同目录")
    parser.add_argument("--config", "-c", required=True, help="config.json 路径，用于构造 outline_model")
    parser.add_argument("--output-report", help="修订报告输出路径，默认 outline_revision_report.json")
    parser.add_argument("--include-warning", action="store_true", help="除 fatal 外也纳入 warning 级发现")
    parser.add_argument("--rules", help="只处理指定规则，逗号分隔，例如 O3,O3-LLM,O4")
    parser.add_argument("--dry-run", action="store_true", help="只生成修订报告，不写回 outline.json")
    parser.add_argument("--json", action="store_true", help="JSON 输出结果")
    args = parser.parse_args(argv)

    outline_path = os.path.abspath(args.outline)
    audit_report_path = args.audit_report or os.path.join(
        os.path.dirname(outline_path),
        "outline_audit_report.json",
    )
    audit_report_path = os.path.abspath(audit_report_path)

    if not os.path.exists(outline_path):
        print(f"错误：outline.json 不存在: {outline_path}", file=sys.stderr)
        return 2
    if not os.path.exists(audit_report_path):
        print(f"错误：审计报告不存在: {audit_report_path}", file=sys.stderr)
        return 2
    if not os.path.exists(args.config):
        print(f"错误：配置文件不存在: {args.config}", file=sys.stderr)
        return 2

    try:
        model = _build_outline_model(args.config)
        severities = ("fatal", "warning") if args.include_warning else ("fatal",)
        report = revise_outline_file(
            outline_path=outline_path,
            audit_report_path=audit_report_path,
            model=model,
            output_report_path=args.output_report,
            severities=severities,
            rules=_parse_rules(args.rules),
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"错误：大纲修订失败：{exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    stats = report.get("stats", {})
    print(f"大纲修订完成：{outline_path}")
    print(f"审计报告：{audit_report_path}")
    print(
        "结果："
        f"actionable {stats.get('actionable_findings', 0)} / "
        f"requested {stats.get('requested_revisions', 0)} / "
        f"applied {stats.get('applied_revisions', 0)}"
    )
    if report.get("dry_run"):
        print("模式：dry-run，未写回 outline.json")
    elif report.get("backup_path"):
        print(f"备份：{report['backup_path']}")
    else:
        print("未发现需要写回的修订")
    print(f"修订报告：{report.get('revision_report')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
