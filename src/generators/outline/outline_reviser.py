# -*- coding: utf-8 -*-
"""根据大纲审计报告修订 outline.json。

该模块只提供显式修订能力，不改变现有大纲生成后的只读审计闸门。
默认仅处理 fatal 级审计发现；warning 噪声需用户显式选择后才纳入。
"""

from __future__ import annotations

import copy
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


AUDIT_REVISION_GENERATE_KWARGS = {"temperature": 0}
REVISION_MAX_FINDINGS_PER_CALL = 8
REVISION_MAX_CONTEXT_CANDIDATES_PER_FINDING = 8
REVISION_TEXT_LIMIT = 700
REVISION_LIST_LIMIT = 10
# _build_revision_prompt 内部保守字符预算，留余量给数组缩进与省略标注，
# 避免上下文累加撑爆 prompt 导致尾部 [输出格式] 被砍掉。
REVISION_PROMPT_CHAR_BUDGET = 58000

_ALLOWED_FIELDS = {
    "title",
    "key_points",
    "characters",
    "settings",
    "conflicts",
    "emotion_tone",
    "character_goals",
    "scene_sequence",
    "foreshadowing",
    "pov_character",
}
_LIST_FIELDS = {"key_points", "characters", "settings", "conflicts", "scene_sequence", "foreshadowing"}
_DICT_FIELDS = {"character_goals"}
_STRING_FIELDS = {"title", "emotion_tone", "pov_character"}
_CHAPTER_REF_RE = re.compile(r"第\s*(\d+)\s*章")


@dataclass
class OutlineRevision:
    """单章修订补丁。"""

    chapter_number: int
    fields: Dict
    reason: str = ""
    finding_refs: List[str] = field(default_factory=list)


@dataclass
class OutlineRevisionResult:
    """大纲修订结果。"""

    revised_chapters: List[dict]
    revisions: List[OutlineRevision]
    stats: Dict
    raw_response: str = ""


def _extract_json(text: str):
    """从 LLM 输出中提取首个 JSON 对象。"""
    if not text:
        return None
    cleaned = re.sub(r"```(?:json)?", "", str(text)).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(cleaned[start:end + 1])
    except Exception:
        return None


def _chapter_number(chapter: dict) -> Optional[int]:
    """兼容 chapter_number / chapter 两种章节号字段。"""
    if not isinstance(chapter, dict):
        return None
    num = chapter.get("chapter_number", chapter.get("chapter"))
    return num if isinstance(num, int) else None


def _finding_ref(finding: dict) -> str:
    """生成紧凑 finding 引用，便于报告追踪。"""
    rule = finding.get("rule") or finding.get("rule_id") or "?"
    chapter = finding.get("chapter")
    message = str(finding.get("message", ""))[:80]
    return f"{rule}@{chapter}: {message}"


def _message_chapter_numbers(finding: dict, max_chapter: int) -> List[int]:
    """兼容旧审计报告：从 message 中提取“第 N 章”作为可修订上下文。"""
    nums = set()
    for match in _CHAPTER_REF_RE.finditer(str(finding.get("message", ""))):
        try:
            n = int(match.group(1))
        except ValueError:
            continue
        if 1 <= n <= max_chapter:
            nums.add(n)
    return sorted(nums)


def select_actionable_findings(
    audit_report: dict,
    severities: Sequence[str] = ("fatal",),
    rules: Optional[Sequence[str]] = None,
) -> List[dict]:
    """从审计报告中筛出需要自动修订的发现。"""
    allowed_severities = set(severities or ())
    allowed_rules = set(rules or ())
    selected: List[dict] = []
    for finding in audit_report.get("findings", []) or []:
        if not isinstance(finding, dict):
            continue
        if allowed_severities and finding.get("severity") not in allowed_severities:
            continue
        if allowed_rules and finding.get("rule") not in allowed_rules:
            continue
        selected.append(finding)
    return selected


def _context_chapter_numbers(findings: Iterable[dict], max_chapter: int) -> Tuple[List[int], List[int]]:
    """按优先级返回给 LLM 的上下文章节号，分两级便于预算紧张时分层裁剪：

    - core：各 finding 的 chapter±1（直接修订目标，必须尽量保留）
    - extra：chapter+2 与 evidence 候选/样本/首尾章节（背景参考，可优先省略）
    """
    core = set()
    extra = set()
    for finding in findings:
        chapter = finding.get("chapter")
        if isinstance(chapter, int) and chapter > 0:
            for n in (chapter - 1, chapter, chapter + 1):
                if 1 <= n <= max_chapter:
                    core.add(n)
            if 1 <= chapter + 2 <= max_chapter:
                extra.add(chapter + 2)
        for n in _message_chapter_numbers(finding, max_chapter):
            core.add(n)
        evidence = finding.get("evidence") or {}
        for key in ("target_chapters", "affected_chapters"):
            for n in list(evidence.get(key, []) or []):
                if isinstance(n, int) and 1 <= n <= max_chapter:
                    core.add(n)
        for key in ("candidate_chapters", "sample_occurrences"):
            values = list(evidence.get(key, []) or [])
            if key == "candidate_chapters":
                values = values[:REVISION_MAX_CONTEXT_CANDIDATES_PER_FINDING]
            for n in values:
                if isinstance(n, int) and 1 <= n <= max_chapter:
                    extra.add(n)
        for key in ("first_chapter", "last_chapter"):
            n = evidence.get(key)
            if isinstance(n, int) and 1 <= n <= max_chapter:
                extra.add(n)
    extra -= core
    return sorted(core), sorted(extra)


def _shorten_text(value, limit: int = REVISION_TEXT_LIMIT) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + f"...（已截断 {len(text) - limit} 字）"


def _compact_prompt_value(value, depth: int = 0):
    """压缩 prompt 中的证据/章节字段，避免修订调用触发模型层硬截断。"""
    if depth >= 4:
        return _shorten_text(value)
    if isinstance(value, str):
        return _shorten_text(value)
    if isinstance(value, list):
        items = [_compact_prompt_value(item, depth + 1) for item in value[:REVISION_LIST_LIMIT]]
        omitted = len(value) - len(items)
        if omitted > 0:
            items.append(f"...（已省略 {omitted} 项）")
        return items
    if isinstance(value, dict):
        return {
            str(key): _compact_prompt_value(val, depth + 1)
            for key, val in value.items()
        }
    return value


def _compact_chapter(chapter: dict) -> dict:
    """压缩章节上下文，保留可修订字段。"""
    return {
        key: _compact_prompt_value(chapter.get(key))
        for key in ("chapter_number", "title", "key_points", "characters",
                    "settings", "conflicts", "emotion_tone", "character_goals",
                    "scene_sequence", "foreshadowing", "pov_character")
        if key in chapter
    }


def _build_revision_prompt(chapters: List[dict], findings: List[dict]) -> str:
    by_num = {_chapter_number(ch): ch for ch in chapters if _chapter_number(ch) is not None}
    max_chapter = max(by_num) if by_num else 0
    core_nums, extra_nums = _context_chapter_numbers(findings, max_chapter)

    compact_findings = []
    for idx, finding in enumerate(findings, 1):
        compact_findings.append({
            "id": idx,
            "rule": finding.get("rule"),
            "severity": finding.get("severity"),
            "chapter": finding.get("chapter"),
            "message": _shorten_text(finding.get("message", "")),
            "evidence": _compact_prompt_value(finding.get("evidence", {})),
        })

    # 指令、输出格式、审计发现统一前置：即便上下文过长触发模型层硬截断，
    # 这些关键信息也不会被砍掉（旧实现把输出格式放末尾，超长时丢失导致修订失败）。
    header = f"""你是长篇小说大纲编辑。请根据审计结果，对 outline.json 做必要且最小的修订。

要求：
1. 只修订能直接解决 fatal 问题的章节；不要重写整本大纲。
2. 如果任务/伏笔其实已在上下文中闭环，优先补充明确的“任务完成/回收/收口”表述，而不是新增大事件。
3. 如果确实缺少闭环，请在最合适的现有章节中补上收束动作、后果或 foreshadowing 回收项。
4. 对 O4 人物身份一致性问题，优先修订 affected/target 章节的 characters 字段：同一角色人设漂移时统一身份；确为不同人物重名时改名或加可区分称谓，并同步修订 key_points/scene_sequence 中直接引用的名称。
5. 对 O3/O3-LLM 任务闭环问题，修订内容必须包含明确闭环信号（如“任务完成”“正式办结”“回收：第N章...任务”）。如果只是选择“否”或转入暂缓，请写成“非任务状态提示/阶段性办结”，不要再生成新的“系统发布任务/系统更新任务”文本。
6. 保持章节号不变，保持未涉及字段不变。
7. 只输出 JSON，不要输出解释性文字。

输出格式：
{{
  "summary": "本次修订摘要",
  "revisions": [
    {{
      "chapter_number": 37,
      "reason": "为什么修订这一章",
      "finding_refs": ["O3-LLM@28: ..."],
      "fields": {{
        "key_points": ["该章完整 key_points 列表"],
        "foreshadowing": ["该章完整 foreshadowing 列表"]
      }}
    }}
  ]
}}

[审计发现]
{json.dumps(compact_findings, ensure_ascii=False, indent=2)}

[可修订章节上下文]
"""

    # 上下文章节受字符预算约束：core（修订目标）优先纳入，extra（背景）次之，
    # 超预算的章节省略并在末尾标注，确保整体 prompt 落在内部保守预算内。
    budget = REVISION_PROMPT_CHAR_BUDGET - len(header)
    selected: List[Tuple[int, dict]] = []
    used = 0
    omitted = 0
    for n in core_nums + extra_nums:
        ch = by_num.get(n)
        if ch is None:
            continue
        compact = _compact_chapter(ch)
        piece_len = len(json.dumps(compact, ensure_ascii=False, indent=2)) + 2
        if selected and used + piece_len > budget:
            omitted += 1
            continue
        selected.append((n, compact))
        used += piece_len

    selected.sort(key=lambda item: item[0])
    context = [compact for _, compact in selected]
    context_json = json.dumps(context, ensure_ascii=False, indent=2)
    if omitted:
        context_json += (
            f"\n（注：因长度限制省略 {omitted} 章背景上下文，"
            "已优先保留与审计发现直接相关的章节）"
        )
    return header + context_json


def _batched_findings(findings: List[dict], batch_size: int = REVISION_MAX_FINDINGS_PER_CALL):
    for i in range(0, len(findings), batch_size):
        yield findings[i:i + batch_size]


def _coerce_fields(raw: dict) -> Dict:
    """校验并清理 LLM 返回的字段补丁。"""
    fields = raw.get("fields") or raw.get("updates") or {}
    if not isinstance(fields, dict):
        fields = {
            key: raw[key]
            for key in _ALLOWED_FIELDS
            if key in raw
        }

    cleaned = {}
    for key, value in fields.items():
        if key not in _ALLOWED_FIELDS:
            continue
        if key in _LIST_FIELDS:
            if isinstance(value, list):
                cleaned[key] = [str(item) for item in value]
        elif key in _DICT_FIELDS:
            if isinstance(value, dict):
                cleaned[key] = {str(k): str(v) for k, v in value.items()}
        elif key in _STRING_FIELDS:
            if value is not None:
                cleaned[key] = str(value)
    return cleaned


def parse_revision_response(raw_response: str) -> Tuple[str, List[OutlineRevision]]:
    """解析模型返回的修订 JSON。"""
    data = _extract_json(raw_response)
    if data is None:
        raise ValueError("模型未返回可解析的 JSON 修订结果")

    revisions: List[OutlineRevision] = []
    for raw in data.get("revisions", []) or []:
        if not isinstance(raw, dict):
            continue
        chapter_number = raw.get("chapter_number")
        if not isinstance(chapter_number, int) or chapter_number <= 0:
            continue
        fields = _coerce_fields(raw)
        if not fields:
            continue
        finding_refs = raw.get("finding_refs", []) or []
        revisions.append(OutlineRevision(
            chapter_number=chapter_number,
            fields=fields,
            reason=str(raw.get("reason", "")),
            finding_refs=[str(item) for item in finding_refs],
        ))
    return str(data.get("summary", "")), revisions


def apply_revisions(chapters: List[dict], revisions: List[OutlineRevision]) -> Tuple[List[dict], List[OutlineRevision]]:
    """把修订补丁应用到章节列表，返回实际发生变化的补丁。"""
    revised = copy.deepcopy(chapters)
    index_by_num = {
        _chapter_number(chapter): idx
        for idx, chapter in enumerate(revised)
        if _chapter_number(chapter) is not None
    }
    applied: List[OutlineRevision] = []
    for revision in revisions:
        idx = index_by_num.get(revision.chapter_number)
        if idx is None:
            continue
        chapter = revised[idx]
        changed_fields = {}
        for key, value in revision.fields.items():
            if chapter.get(key) != value:
                chapter[key] = value
                changed_fields[key] = value
        if changed_fields:
            applied.append(OutlineRevision(
                chapter_number=revision.chapter_number,
                fields=changed_fields,
                reason=revision.reason,
                finding_refs=revision.finding_refs,
            ))
    return revised, applied


def revise_outline_from_audit(
    chapters: List[dict],
    audit_report: dict,
    model,
    severities: Sequence[str] = ("fatal",),
    rules: Optional[Sequence[str]] = None,
) -> OutlineRevisionResult:
    """根据审计报告调用模型生成并应用大纲修订。"""
    actionable = select_actionable_findings(audit_report, severities=severities, rules=rules)
    stats = {
        "total_findings": len(audit_report.get("findings", []) or []),
        "actionable_findings": len(actionable),
        "requested_revisions": 0,
        "applied_revisions": 0,
        "changed_chapters": [],
        "model_called": False,
        "revision_batches": 0,
        "max_prompt_chars": 0,
    }
    if not actionable:
        return OutlineRevisionResult(
            revised_chapters=copy.deepcopy(chapters),
            revisions=[],
            stats=stats,
        )

    revised = copy.deepcopy(chapters)
    all_requested: List[OutlineRevision] = []
    all_applied: List[OutlineRevision] = []
    summaries: List[str] = []
    raw_responses: List[str] = []

    for batch in _batched_findings(actionable):
        prompt = _build_revision_prompt(revised, batch)
        stats["max_prompt_chars"] = max(stats["max_prompt_chars"], len(prompt))
        raw = model.generate(prompt, **AUDIT_REVISION_GENERATE_KWARGS)
        stats["model_called"] = True
        stats["revision_batches"] += 1
        raw_responses.append(str(raw))
        summary, requested = parse_revision_response(raw)
        if summary:
            summaries.append(summary)
        all_requested.extend(requested)
        revised, applied = apply_revisions(revised, requested)
        all_applied.extend(applied)

    stats["summary"] = "；".join(summaries)
    stats["requested_revisions"] = len(all_requested)
    stats["applied_revisions"] = len(all_applied)
    stats["changed_chapters"] = [item.chapter_number for item in all_applied]
    return OutlineRevisionResult(
        revised_chapters=revised,
        revisions=all_applied,
        stats=stats,
        raw_response="\n\n--- batch ---\n\n".join(raw_responses),
    )


def _backup_path(outline_path: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{outline_path}.bak.{stamp}"


def revise_outline_file(
    outline_path: str,
    audit_report_path: str,
    model,
    output_report_path: Optional[str] = None,
    severities: Sequence[str] = ("fatal",),
    rules: Optional[Sequence[str]] = None,
    dry_run: bool = False,
) -> Dict:
    """读取 outline/audit report，执行修订，写回 outline 与修订报告。"""
    with open(outline_path, "r", encoding="utf-8") as fp:
        chapters = json.load(fp)
    if not isinstance(chapters, list):
        raise RuntimeError("outline.json 顶层应为章节列表")

    with open(audit_report_path, "r", encoding="utf-8") as fp:
        audit_report = json.load(fp)
    if not isinstance(audit_report, dict):
        raise RuntimeError("outline_audit_report.json 顶层应为对象")

    result = revise_outline_from_audit(
        chapters,
        audit_report,
        model,
        severities=severities,
        rules=rules,
    )

    backup = ""
    if not dry_run and result.revisions:
        backup = _backup_path(outline_path)
        with open(backup, "w", encoding="utf-8") as fp:
            json.dump(chapters, fp, ensure_ascii=False, indent=2)
        with open(outline_path, "w", encoding="utf-8") as fp:
            json.dump(result.revised_chapters, fp, ensure_ascii=False, indent=2)

    if output_report_path is None:
        output_report_path = os.path.join(
            os.path.dirname(outline_path),
            "outline_revision_report.json",
        )

    report = {
        "outline": outline_path,
        "audit_report": audit_report_path,
        "dry_run": dry_run,
        "backup_path": backup,
        "revision_report": output_report_path,
        "stats": result.stats,
        "revisions": [asdict(item) for item in result.revisions],
    }
    with open(output_report_path, "w", encoding="utf-8") as fp:
        json.dump(report, fp, ensure_ascii=False, indent=2)
    return report
