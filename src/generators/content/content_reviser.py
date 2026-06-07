# -*- coding: utf-8 -*-
"""根据章节内容审计报告修订章节正文。

该模块提供显式修订能力：默认只处理章节内容审计中的 fatal C1/C2
发现，优先消费局部审计报告，再回退整部审计报告。修订结果以完整章节
正文写回原章节文件，写回前自动备份。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from src.generators.content.content_auditor import (
    _compact_text,
    _safe_json_dumps,
    _strip_markdown_heading,
    find_chapter_candidates,
    load_outline_map,
)


CONTENT_REVISION_GENERATE_KWARGS = {"temperature": 0, "max_tokens": 8192}
DEFAULT_CONTENT_REVISION_RULES = ("C1", "C2")
CONTENT_REVISION_PROMPT_CHAR_BUDGET = 58000
_CHAPTER_REF_RE = re.compile(r"第\s*(\d+)\s*章")


@dataclass
class ContentRevision:
    """单章正文修订结果。"""

    chapter_number: int
    content: str
    path: str = ""
    reason: str = ""
    finding_refs: List[str] = field(default_factory=list)
    edits: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class ContentRevisionResult:
    """正文修订运行结果。"""

    revisions: List[ContentRevision]
    stats: Dict[str, Any]
    raw_response: str = ""
    skipped_findings: List[Dict[str, Any]] = field(default_factory=list)
    failed_revisions: List[Dict[str, Any]] = field(default_factory=list)


def _extract_json(text: str) -> Optional[Any]:
    """从 LLM 输出中提取首个 JSON 对象或数组。"""
    if not text:
        return None
    cleaned = str(text).strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.S | re.I)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    starts = [idx for idx in (cleaned.find("{"), cleaned.find("[")) if idx >= 0]
    if not starts:
        return None
    start = min(starts)
    end_char = "}" if cleaned[start] == "{" else "]"
    end = cleaned.rfind(end_char)
    if end <= start:
        return None
    try:
        return json.loads(cleaned[start:end + 1])
    except Exception:
        return None


def _normalize_rule(value: Any) -> str:
    return str(value or "").strip().upper()


def _normalize_path(path: str, base_dir: Optional[str] = None) -> str:
    if not path:
        return path
    if os.path.isabs(path):
        return path
    return os.path.abspath(os.path.join(base_dir or os.getcwd(), path))


def _report_basename_for(audit_report_path: str) -> str:
    return (
        "content_revision_report_scope.json"
        if os.path.basename(audit_report_path) == "content_audit_report_scope.json"
        else "content_revision_report.json"
    )


def resolve_content_audit_report_path(output_dir: str, audit_report_path: Optional[str] = None) -> str:
    """解析内容审计报告路径：显式路径 > 局部报告 > 完整报告。"""
    if audit_report_path:
        return _normalize_path(audit_report_path)
    scoped = os.path.join(output_dir, "content_audit_report_scope.json")
    if os.path.exists(scoped):
        return scoped
    return os.path.join(output_dir, "content_audit_report.json")


def select_actionable_findings(
    audit_report: Dict[str, Any],
    severities: Sequence[str] = ("fatal",),
    rules: Optional[Sequence[str]] = DEFAULT_CONTENT_REVISION_RULES,
) -> List[Dict[str, Any]]:
    """从内容审计报告中筛出可自动修订的 finding。"""
    allowed_severities = {str(item).strip().lower() for item in (severities or ())}
    allowed_rules = {_normalize_rule(item) for item in (rules or ())}
    selected: List[Dict[str, Any]] = []
    for finding in audit_report.get("findings", []) or []:
        if not isinstance(finding, dict):
            continue
        severity = str(finding.get("severity") or "").strip().lower()
        rule = _normalize_rule(finding.get("rule") or finding.get("rule_id"))
        if allowed_severities and severity not in allowed_severities:
            continue
        if allowed_rules and rule not in allowed_rules:
            continue
        selected.append(finding)
    return selected


def _skipped_findings(
    audit_report: Dict[str, Any],
    severities: Sequence[str],
    rules: Optional[Sequence[str]],
) -> List[Dict[str, Any]]:
    """记录同严重级别但不支持自动修订的 finding。"""
    allowed_severities = {str(item).strip().lower() for item in (severities or ())}
    allowed_rules = {_normalize_rule(item) for item in (rules or ())}
    skipped: List[Dict[str, Any]] = []
    for finding in audit_report.get("findings", []) or []:
        if not isinstance(finding, dict):
            continue
        severity = str(finding.get("severity") or "").strip().lower()
        if allowed_severities and severity not in allowed_severities:
            continue
        rule = _normalize_rule(finding.get("rule") or finding.get("rule_id"))
        if allowed_rules and rule in allowed_rules:
            continue
        reason = "unsupported_rule" if rule else "missing_rule"
        skipped.append({"reason": reason, "finding": finding})
    return skipped


def _finding_ref(finding: Dict[str, Any]) -> str:
    rule = finding.get("rule") or finding.get("rule_id") or "?"
    chapter = finding.get("chapter")
    message = str(finding.get("message", ""))[:100]
    return f"{rule}@{chapter}: {message}"


def _chapter_number_from_finding(finding: Dict[str, Any]) -> Optional[int]:
    for key in ("chapter", "chapter_number", "current_chapter"):
        try:
            chapter_number = int(finding.get(key))
        except (TypeError, ValueError):
            continue
        if chapter_number > 0:
            return chapter_number
    evidence = finding.get("evidence") or {}
    if isinstance(evidence, dict):
        for key in ("chapter", "chapter_number", "current_chapter"):
            try:
                chapter_number = int(evidence.get(key))
            except (TypeError, ValueError):
                continue
            if chapter_number > 0:
                return chapter_number
    for match in _CHAPTER_REF_RE.finditer(str(finding.get("message", ""))):
        try:
            return int(match.group(1))
        except ValueError:
            continue
    return None


def _preferred_content_path(
    output_dir: str,
    chapter_number: int,
    outline: Dict[str, Any],
    findings: Sequence[Dict[str, Any]],
) -> Optional[str]:
    """优先使用审计报告中的正文路径，否则按当前大纲查找候选文件。"""
    for finding in findings:
        evidence = finding.get("evidence") or {}
        if not isinstance(evidence, dict):
            continue
        for key in ("content_path", "current_path", "path"):
            path = evidence.get(key)
            if isinstance(path, str) and path and os.path.exists(path):
                return path
    candidates = find_chapter_candidates(output_dir, chapter_number, outline)
    return candidates[0] if candidates else None


def _read_file(path: Optional[str]) -> str:
    if not path or not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as fp:
        return _strip_markdown_heading(fp.read())


def _load_adjacent_content(output_dir: str, chapter_number: int, outline_map: Dict[int, Dict[str, Any]]) -> str:
    outline = outline_map.get(chapter_number)
    if not outline:
        return ""
    candidates = find_chapter_candidates(output_dir, chapter_number, outline)
    return _read_file(candidates[0] if candidates else None)


def _compact_outline(outline: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "chapter_number", "title", "key_points", "characters", "settings",
        "conflicts", "emotion_tone", "character_goals", "scene_sequence",
        "foreshadowing", "pov_character",
    )
    return {key: outline.get(key) for key in keys if key in outline}


def _build_revision_prompt(
    chapter_number: int,
    outline: Dict[str, Any],
    content: str,
    findings: Sequence[Dict[str, Any]],
    previous_content: str = "",
    next_content: str = "",
) -> str:
    """构造单章正文修订提示词。"""
    compact_findings = []
    for index, finding in enumerate(findings, 1):
        compact_findings.append({
            "id": index,
            "rule": finding.get("rule") or finding.get("rule_id"),
            "severity": finding.get("severity"),
            "chapter": finding.get("chapter"),
            "message": str(finding.get("message", ""))[:1200],
            "evidence": finding.get("evidence", {}),
        })

    payload = {
        "chapter_number": chapter_number,
        "outline": _compact_outline(outline),
        "findings": compact_findings,
        "previous_tail": previous_content[-2200:] if previous_content else "",
        "current_content": _compact_text(content, head=5200, middle=2200, tail=5200),
        "next_head": next_content[:1600] if next_content else "",
    }
    context = _safe_json_dumps(payload)
    if len(context) > CONTENT_REVISION_PROMPT_CHAR_BUDGET:
        payload["current_content"] = _compact_text(content, head=3600, middle=1400, tail=3600)
        context = _safe_json_dumps(payload)

    return f"""你是长篇小说正文编辑。请根据章节内容审计结果，对第 {chapter_number} 章正文做必要且最小的修订。

要求：
1. 只能基于原文做局部修订，严禁重新生成整章，严禁省略或改写无关段落。
2. C1 表示正文与大纲不一致：修订后必须覆盖大纲中的关键事件、人物、场景、冲突、伏笔与情绪基调。
3. C2 表示相邻章节衔接断裂：优先修订当前章开头或必要过渡段，保持上一章结尾和后续章节大方向不变。
4. 保持章节号、章节标题、主线人物、人称和整体文风一致。
5. 不要输出完整章节正文；只输出 edits。每个 old_text 必须逐字来自 [修订上下文] 的 current_content，且应尽量短小、可唯一定位。
6. new_text 必须以 old_text 为基础做最小必要改动，不得承接 old_text 以外的大段重写。
7. 如果无法定位可精确替换的原文片段，输出空 revisions，不要猜测重写。
8. 只输出 JSON，不要输出解释性文字。

输出格式：
{{
  "summary": "本次修订摘要",
  "revisions": [
    {{
      "chapter_number": {chapter_number},
      "reason": "为什么这样修订",
      "finding_refs": ["C1@{chapter_number}: ..."],
      "edits": [
        {{
          "old_text": "从原文中逐字复制、可唯一定位的待替换片段",
          "new_text": "在 old_text 基础上做最小必要修订后的片段"
        }}
      ]
    }}
  ]
}}

[修订上下文]
{context}
"""


def parse_revision_response(raw_response: str) -> Tuple[str, List[ContentRevision]]:
    """解析模型返回的正文修订 JSON。"""
    data = _extract_json(raw_response)
    if data is None:
        raise ValueError("模型未返回可解析的 JSON 修订结果")
    if isinstance(data, list):
        raw_revisions = data
        summary = ""
    elif isinstance(data, dict):
        raw_revisions = data.get("revisions", []) or []
        summary = str(data.get("summary", ""))
    else:
        raw_revisions = []
        summary = ""

    revisions: List[ContentRevision] = []
    for raw in raw_revisions:
        if not isinstance(raw, dict):
            continue
        try:
            chapter_number = int(raw.get("chapter_number") or raw.get("chapter"))
        except (TypeError, ValueError):
            continue
        raw_edits = raw.get("edits") or raw.get("replacements") or []
        if not isinstance(raw_edits, list):
            raw_edits = []
        edits: List[Dict[str, str]] = []
        for item in raw_edits:
            if not isinstance(item, dict):
                continue
            old_text = str(item.get("old_text") or item.get("source_text") or "")
            new_text = str(item.get("new_text") or item.get("replacement_text") or "")
            if old_text and new_text and old_text != new_text:
                edits.append({"old_text": old_text, "new_text": new_text})
        legacy_content = raw.get("content") or raw.get("revised_content") or raw.get("chapter_content")
        legacy_content = _strip_markdown_heading(str(legacy_content or "")).strip()
        if chapter_number <= 0 or (not edits and not legacy_content):
            continue
        finding_refs = raw.get("finding_refs", []) or []
        revisions.append(ContentRevision(
            chapter_number=chapter_number,
            content=legacy_content if not edits else "",
            reason=str(raw.get("reason", "")),
            finding_refs=[str(item) for item in finding_refs],
            edits=edits,
        ))
    return summary, revisions


def _apply_revision_to_original(original: str, revision: ContentRevision) -> Tuple[Optional[str], Optional[str]]:
    """把模型返回的精确 edits 应用到原文，拒绝无法唯一定位的替换。"""
    if revision.edits:
        updated = original
        applied = 0
        for edit in revision.edits:
            old_text = edit.get("old_text", "")
            new_text = edit.get("new_text", "")
            count = updated.count(old_text)
            if count == 0:
                return None, "old_text_not_found"
            if count > 1:
                return None, "old_text_not_unique"
            updated = updated.replace(old_text, new_text, 1)
            applied += 1
        if applied <= 0 or updated.strip() == original.strip():
            return None, "unchanged_content"
        return updated, None

    if revision.content:
        return None, "missing_precise_edits"
    return None, "missing_precise_edits"


def _group_findings_by_chapter(findings: Iterable[Dict[str, Any]]) -> Tuple[Dict[int, List[Dict[str, Any]]], List[Dict[str, Any]]]:
    grouped: Dict[int, List[Dict[str, Any]]] = {}
    skipped: List[Dict[str, Any]] = []
    for finding in findings:
        chapter_number = _chapter_number_from_finding(finding)
        if chapter_number is None:
            skipped.append({"reason": "missing_chapter", "finding": finding})
            continue
        grouped.setdefault(chapter_number, []).append(finding)
    return grouped, skipped


def revise_content_from_audit(
    output_dir: str,
    outline_path: str,
    audit_report: Dict[str, Any],
    model: Any,
    severities: Sequence[str] = ("fatal",),
    rules: Optional[Sequence[str]] = DEFAULT_CONTENT_REVISION_RULES,
    stop_event: Any = None,
) -> ContentRevisionResult:
    """根据内容审计报告调用模型生成正文修订，不写回文件。"""
    actionable = select_actionable_findings(audit_report, severities=severities, rules=rules)
    skipped = _skipped_findings(audit_report, severities=severities, rules=rules)
    grouped, skipped_without_chapter = _group_findings_by_chapter(actionable)
    skipped.extend(skipped_without_chapter)

    stats: Dict[str, Any] = {
        "total_findings": len(audit_report.get("findings", []) or []),
        "actionable_findings": len(actionable),
        "skipped_findings": len(skipped),
        "requested_revisions": 0,
        "applied_revisions": 0,
        "written_revisions": 0,
        "changed_chapters": [],
        "model_called": False,
        "revision_batches": 0,
        "max_prompt_chars": 0,
        "failed_revisions": 0,
        "stopped": 0,
    }
    if not grouped:
        return ContentRevisionResult([], stats, skipped_findings=skipped)

    outline_map, outline_findings, _ = load_outline_map(outline_path)
    for finding in outline_findings:
        skipped.append({"reason": "outline_input_warning", "finding": asdict(finding)})
    revisions: List[ContentRevision] = []
    failed: List[Dict[str, Any]] = []
    raw_responses: List[str] = []

    for chapter_number in sorted(grouped):
        if stop_event is not None and getattr(stop_event, "is_set", lambda: False)():
            stats["stopped"] = 1
            break
        findings = grouped[chapter_number]
        outline = outline_map.get(chapter_number)
        if not outline:
            failed.append({"chapter_number": chapter_number, "reason": "missing_outline"})
            continue
        content_path = _preferred_content_path(output_dir, chapter_number, outline, findings)
        if not content_path:
            failed.append({"chapter_number": chapter_number, "reason": "missing_content"})
            continue
        content = _read_file(content_path)
        if not content.strip():
            failed.append({"chapter_number": chapter_number, "reason": "empty_content", "path": content_path})
            continue

        previous_content = _load_adjacent_content(output_dir, chapter_number - 1, outline_map)
        next_content = _load_adjacent_content(output_dir, chapter_number + 1, outline_map)
        prompt = _build_revision_prompt(
            chapter_number,
            outline,
            content,
            findings,
            previous_content=previous_content,
            next_content=next_content,
        )
        stats["max_prompt_chars"] = max(stats["max_prompt_chars"], len(prompt))
        raw = model.generate(prompt, **CONTENT_REVISION_GENERATE_KWARGS)
        stats["model_called"] = True
        stats["revision_batches"] += 1
        raw_responses.append(str(raw))

        try:
            _, requested = parse_revision_response(raw)
        except ValueError as exc:
            failed.append({"chapter_number": chapter_number, "reason": "parse_failed", "error": str(exc)})
            continue
        stats["requested_revisions"] += len(requested)
        returned_chapters = [revision.chapter_number for revision in requested]
        matching = [revision for revision in requested if revision.chapter_number == chapter_number]
        if not matching:
            failed.append({
                "chapter_number": chapter_number,
                "reason": "no_target_revision",
                "returned_chapters": returned_chapters,
            })
            continue
        revision = matching[0]
        revision.path = content_path
        revised_content, failure_reason = _apply_revision_to_original(content, revision)
        if failure_reason or not revised_content:
            failed.append({
                "chapter_number": chapter_number,
                "reason": failure_reason or "empty_revision_result",
                "path": content_path,
            })
            continue
        revision.content = revised_content
        if revision.content.strip() == content.strip():
            failed.append({"chapter_number": chapter_number, "reason": "unchanged_content", "path": content_path})
            continue
        if not revision.finding_refs:
            revision.finding_refs = [_finding_ref(finding) for finding in findings]
        revisions.append(revision)

    stats["applied_revisions"] = len(revisions)
    stats["changed_chapters"] = [revision.chapter_number for revision in revisions]
    stats["failed_revisions"] = len(failed)
    return ContentRevisionResult(
        revisions=revisions,
        stats=stats,
        raw_response="\n\n--- batch ---\n\n".join(raw_responses),
        skipped_findings=skipped,
        failed_revisions=failed,
    )


def _backup_path(path: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{path}.bak.{stamp}"


def _revision_to_report(revision: ContentRevision) -> Dict[str, Any]:
    data = asdict(revision)
    data["content_length"] = len(revision.content)
    data["content_preview"] = revision.content[:300]
    return data


def revise_content_files(
    output_dir: str,
    model: Any,
    outline_path: Optional[str] = None,
    audit_report_path: Optional[str] = None,
    output_report_path: Optional[str] = None,
    severities: Sequence[str] = ("fatal",),
    rules: Optional[Sequence[str]] = DEFAULT_CONTENT_REVISION_RULES,
    dry_run: bool = False,
    stop_event: Any = None,
) -> Dict[str, Any]:
    """读取内容审计报告，执行正文修订，写回章节与修订报告。"""
    output_dir = _normalize_path(output_dir)
    outline_path = _normalize_path(outline_path or os.path.join(output_dir, "outline.json"))
    audit_report_path = resolve_content_audit_report_path(output_dir, audit_report_path)

    if not os.path.isdir(output_dir):
        raise FileNotFoundError(f"未找到输出目录: {output_dir}")
    if not os.path.exists(outline_path):
        raise FileNotFoundError(f"未找到 outline.json: {outline_path}")
    if not os.path.exists(audit_report_path):
        raise FileNotFoundError(
            "未找到内容审计报告，请先运行章节内容审计: "
            f"{audit_report_path}"
        )

    with open(audit_report_path, "r", encoding="utf-8") as fp:
        audit_report = json.load(fp)
    if not isinstance(audit_report, dict):
        raise RuntimeError("content_audit_report.json 顶层应为对象")

    result = revise_content_from_audit(
        output_dir=output_dir,
        outline_path=outline_path,
        audit_report=audit_report,
        model=model,
        severities=severities,
        rules=rules,
        stop_event=stop_event,
    )

    backup_paths: Dict[str, str] = {}
    if not dry_run:
        for revision in result.revisions:
            backup = _backup_path(revision.path)
            with open(revision.path, "r", encoding="utf-8") as fp:
                original = fp.read()
            with open(backup, "w", encoding="utf-8") as fp:
                fp.write(original)
            with open(revision.path, "w", encoding="utf-8") as fp:
                fp.write(revision.content.rstrip() + "\n")
            backup_paths[str(revision.chapter_number)] = backup
        result.stats["written_revisions"] = len(backup_paths)

    if output_report_path is None:
        output_report_path = os.path.join(os.path.dirname(audit_report_path), _report_basename_for(audit_report_path))
    else:
        output_report_path = _normalize_path(output_report_path)

    report = {
        "content_dir": output_dir,
        "outline": outline_path,
        "audit_report": audit_report_path,
        "dry_run": dry_run,
        "backup_paths": backup_paths,
        "revision_report": output_report_path,
        "stats": result.stats,
        "revisions": [_revision_to_report(revision) for revision in result.revisions],
        "skipped_findings": result.skipped_findings,
        "failed_revisions": result.failed_revisions,
        "raw_response": result.raw_response,
    }
    with open(output_report_path, "w", encoding="utf-8") as fp:
        json.dump(report, fp, ensure_ascii=False, indent=2, default=str)
    return report
