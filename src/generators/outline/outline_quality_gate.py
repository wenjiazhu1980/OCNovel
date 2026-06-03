# -*- coding: utf-8 -*-
"""大纲质量闸门：auto 流程中大纲生成后的阻断式关卡。

与只读的 OutlineGenerator._run_outline_audit 不同：本闸门在发现 fatal 时
会调用大纲修订写回 outline.json 并重新审计；最终仍有 fatal 则判定不通过，
由调用方（CLI auto / GUI pipeline_worker）据此中止流水线、不进正文。

错误处理：质量不达标（审计判定有 fatal）→ 判定 not passed，调用方据此中止；
闸门自身执行异常（模型不可用等）→ fail-open 放行，与 _run_outline_audit
"异常不阻断"的哲学一致，避免审计工具故障卡死整条流水线。
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from typing import List, Optional, Sequence

from .outline_auditor import (
    llm_review_task_closure_with_stats,
    merge_llm_task_review_findings,
    run_audit,
    serialize_finding,
)
from .outline_reviser import _backup_path, revise_outline_from_audit

logger = logging.getLogger(__name__)

REPORT_FILENAME = "outline_quality_gate_report.json"


@dataclass
class QualityGateResult:
    """质量闸门裁决结果。"""

    passed: bool                 # 最终无 fatal（或 fail-open 放行）
    initial_fatal: int           # 首轮审计的 fatal 数
    remaining_fatal: int         # 末轮审计的 fatal 数
    rounds_run: int              # 实际跑的修订-重审轮数
    revised: bool                # 是否真的改写了大纲
    changed_chapters: List[int] = field(default_factory=list)
    report: dict = field(default_factory=dict)


def _fatal(findings) -> list:
    return [f for f in findings if getattr(f, "severity", None) == "fatal"]


def _audit(chapters: List[dict], model, enable_llm: bool) -> list:
    """跑算法审计；enable_llm 时叠加 LLM 任务闭环复核并合并去重。"""
    findings = run_audit(chapters)
    if enable_llm:
        llm_result = llm_review_task_closure_with_stats(chapters, model)
        findings = merge_llm_task_review_findings(findings, llm_result)
    return findings


def _write_back(chapters: List[dict], output_dir: str) -> str:
    """备份磁盘上的 outline.json 后写回修订结果，返回备份路径。"""
    outline_path = os.path.join(output_dir, "outline.json")
    backup = ""
    if os.path.exists(outline_path):
        backup = _backup_path(outline_path)
        with open(outline_path, "r", encoding="utf-8") as fp:
            old = fp.read()
        with open(backup, "w", encoding="utf-8") as fp:
            fp.write(old)
    with open(outline_path, "w", encoding="utf-8") as fp:
        json.dump(chapters, fp, ensure_ascii=False, indent=2)
    return backup


def _write_report(report: dict, output_dir: str) -> None:
    path = os.path.join(output_dir, REPORT_FILENAME)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(report, fp, ensure_ascii=False, indent=2)


def _run(chapters, outline_model, enable_llm, max_rounds, output_dir, severities) -> QualityGateResult:
    """闸门主体逻辑（不含 fail-open 包裹）。"""
    current = chapters
    findings = _audit(current, outline_model, enable_llm)
    initial_fatal = _fatal(findings)

    changed: List[int] = []
    revised = False
    rounds_run = 0
    remaining_fatal = initial_fatal

    if initial_fatal:
        for _ in range(max(1, max_rounds)):
            rounds_run += 1
            audit_report = {"findings": [serialize_finding(f) for f in findings]}
            rev = revise_outline_from_audit(
                current, audit_report, outline_model, severities=severities
            )
            current = rev.revised_chapters
            rev_changed = rev.stats.get("changed_chapters") or []
            if not rev_changed:
                # 本轮修订未改动任何章节：大纲不变，重审结果必然与上轮相同，
                # 提前退出避免空转（enable_llm 时尤其会白跑一次 LLM 复核）。
                break
            revised = True
            changed.extend(rev_changed)

            findings = _audit(current, outline_model, enable_llm)
            remaining_fatal = _fatal(findings)
            if not remaining_fatal:
                break

    passed = not remaining_fatal
    changed_sorted = sorted(set(changed))
    backup_path = ""

    if output_dir and revised:
        backup_path = _write_back(current, output_dir)

    report = {
        "passed": passed,
        "initial_fatal": len(initial_fatal),
        "remaining_fatal": len(remaining_fatal),
        "rounds_run": rounds_run,
        "revised": revised,
        "changed_chapters": changed_sorted,
        "enable_llm": enable_llm,
        "backup_path": backup_path,
        "remaining_findings": [serialize_finding(f) for f in findings],
    }

    if output_dir:
        _write_report(report, output_dir)

    return QualityGateResult(
        passed=passed,
        initial_fatal=len(initial_fatal),
        remaining_fatal=len(remaining_fatal),
        rounds_run=rounds_run,
        revised=revised,
        changed_chapters=changed_sorted,
        report=report,
    )


def run_quality_gate(
    chapters: List[dict],
    outline_model,
    *,
    enable_llm: bool = True,
    max_rounds: int = 1,
    output_dir: Optional[str] = None,
    severities: Sequence[str] = ("fatal",),
) -> QualityGateResult:
    """跑审计→（有 fatal 则）修订写回→重审，返回裁决结果。

    闸门主体异常时 fail-open 放行（passed=True），由调用方据 passed 决定是否中止。
    """
    try:
        return _run(chapters, outline_model, enable_llm, max_rounds, output_dir, severities)
    except Exception as exc:
        logger.error("大纲质量闸门执行异常，fail-open 放行：%s", exc, exc_info=True)
        return QualityGateResult(
            passed=True,
            initial_fatal=0,
            remaining_fatal=0,
            rounds_run=0,
            revised=False,
            changed_chapters=[],
            report={"passed": True, "error": str(exc), "fail_open": True},
        )


def run_quality_gate_for_pipeline(config, content_generator, outline_model) -> QualityGateResult:
    """auto 流水线（CLI auto / GUI pipeline_worker 共用）的质量闸门入口。

    从 config 读开关与参数，把 content_generator.chapter_outlines 转 dict，跑闸门；
    若闸门改写了大纲（revised）则重新加载 content_generator 的大纲。
    返回结果供调用方据 result.passed 决定是否中止流水线。
    """
    gen_cfg = getattr(config, "generation_config", {}) or {}
    if not gen_cfg.get("outline_quality_gate_enabled", True):
        return QualityGateResult(
            passed=True,
            initial_fatal=0,
            remaining_fatal=0,
            rounds_run=0,
            revised=False,
            report={"skipped": True},
        )

    # fail-open 覆盖整个入口：转换 chapter_outlines / 跑闸门 / 重载大纲任一环节
    # 异常，都不应让流水线 fail-closed 中止（尤其 GUI 侧会 emit(False)），
    # 与 run_quality_gate 主体「异常不阻断」的哲学保持一致。
    try:
        chapters = [
            asdict(c) if c is not None else None
            for c in content_generator.chapter_outlines
        ]
        result = run_quality_gate(
            chapters,
            outline_model,
            enable_llm=gen_cfg.get("outline_quality_gate_llm_review", True),
            max_rounds=gen_cfg.get("outline_quality_gate_max_rounds", 1),
            output_dir=getattr(config, "generator_config", {}).get("output_dir"),
        )
        if result.revised:
            content_generator._load_outline()
        return result
    except Exception as exc:
        logger.error("大纲质量闸门入口异常，fail-open 放行：%s", exc, exc_info=True)
        return QualityGateResult(
            passed=True,
            initial_fatal=0,
            remaining_fatal=0,
            rounds_run=0,
            revised=False,
            report={"passed": True, "error": str(exc), "fail_open": True},
        )
