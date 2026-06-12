# -*- coding: utf-8 -*-
"""章节内容审计器核心。

对已生成的单章正文做只读审计，覆盖：
- C0：输入完整性预检；
- C1：章节正文与章节大纲是否一致或基本一致；
- C2：当前章开头与上一章结尾的衔接是否自然紧密。

审计报告字段与大纲审计器保持一致，便于 GUI / CLI 统一消费。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple


# =====================================================================
# 数据结构
# =====================================================================


@dataclass
class Finding:
    """单条章节内容审计发现。"""

    rule_id: str
    severity: str
    title: str
    chapter: Optional[int]
    message: str
    evidence: Optional[Dict[str, Any]] = None


@dataclass
class ChapterInput:
    """参与审计的单章输入。"""

    chapter_number: int
    outline: Dict[str, Any]
    content: str
    path: str
    candidates: List[str]


@dataclass
class LLMReviewResult:
    """章节内容审计结果与运行统计。"""

    findings: List[Finding]
    stats: Dict[str, int]
    audit_scope: Optional[Dict[str, Any]] = None


def serialize_finding(finding: Finding) -> Dict[str, Any]:
    """把 Finding 转为报告可直接落盘的 dict。"""
    data: Dict[str, Any] = {
        "rule": finding.rule_id,
        "severity": finding.severity,
        "title": finding.title,
        "chapter": finding.chapter,
        "message": finding.message,
    }
    if finding.evidence is not None:
        data["evidence"] = finding.evidence
    return data


# =====================================================================
# 常量与文本工具
# =====================================================================


# 调试证据显示 reasoning 模型会把接近 2K completion token 用在 reasoning_content，
# 导致最终 JSON 被截断或流式阶段没有可见 content；审计 JSON 任务需要更高输出预算。
CONTENT_AUDIT_GENERATE_KWARGS = {"max_tokens": 8192}
CONTENT_AUDIT_PROMPT_MAX_CHARS = 16000

_CONTENT_FILE_RE = re.compile(r"^第(\d+)章_(.+)\.txt$")
_INVALID_FILENAME_CHARS_RE = re.compile(r"[\\/*?:\"<>|]")
_LEADING_HEADING_RE = re.compile(r"^\s*#+\s*")
_VALID_SEVERITIES = {"fatal", "warning", "info"}


def _empty_stats() -> Dict[str, int]:
    """统一统计字段，报告中即使为 0 也显式展示。"""
    return {
        "outline_chapters": 0,
        "audited_chapters": 0,
        "missing_chapters": 0,
        "duplicate_outline_chapters": 0,
        "non_dict_outline_items": 0,
        "chapters_with_multiple_candidates": 0,
        "chapter_checks": 0,
        "transition_checks": 0,
        "llm_calls": 0,
        "llm_batch_items": 0,
        "llm_batch_max_items": 0,
        "llm_findings": 0,
        "llm_fatal_findings": 0,
        "llm_warning_findings": 0,
        "llm_info_findings": 0,
        "llm_call_failures": 0,
        "llm_parse_failures": 0,
        "llm_findings_missing_chapter": 0,
        "llm_findings_unknown_chapter": 0,
        "llm_findings_unknown_rule": 0,
        "llm_prompt_over_budget": 0,
        "llm_prompt_max_chars": 0,
        "llm_prompt_total_chars": 0,
        "llm_prompt_avg_chars": 0,
        "requested_chapters": 0,
        "selected_chapters": 0,
        "skipped_unselected_chapters": 0,
        "selection_missing_outline_chapters": 0,
        "selection_missing_content_chapters": 0,
        "context_chapters_loaded": 0,
        "chapter_check_batches": 0,
        "transition_check_batches": 0,
        "stopped": 0,
    }


def _clean_filename(filename: str) -> str:
    """清理章节标题中的非法文件名字符。"""
    cleaned = _INVALID_FILENAME_CHARS_RE.sub("", filename or "")
    return cleaned.strip().strip(".")


def _strip_markdown_heading(content: str) -> str:
    """剥离首行 leading '#'，兼容历史正文中残留的 Markdown 标题。"""
    if not content:
        return content
    newline_index = content.find("\n")
    first, rest = (content, "") if newline_index == -1 else (content[:newline_index], content[newline_index:])
    new_first = _LEADING_HEADING_RE.sub("", first, count=1)
    return new_first + rest if new_first != first else content


def _is_cancelled(stop_event: Any = None) -> bool:
    """判断外部停止事件是否已触发。"""
    return bool(stop_event is not None and getattr(stop_event, "is_set", lambda: False)())


def _normalize_severity(value: Any) -> str:
    """归一化 LLM 返回的严重程度。"""
    severity = str(value or "warning").strip().lower()
    return severity if severity in _VALID_SEVERITIES else "warning"


def _compact_text(text: str, head: int = 3000, middle: int = 1600, tail: int = 3000) -> str:
    """压缩长文本，保留首尾与中段，避免提示词超预算。"""
    text = text or ""
    limit = head + middle + tail
    if len(text) <= limit:
        return text
    mid_start = max(0, len(text) // 2 - middle // 2)
    return (
        text[:head]
        + f"\n\n……（中间省略 {len(text) - limit} 字）……\n\n"
        + text[mid_start:mid_start + middle]
        + "\n\n……（跳至章节末尾）……\n\n"
        + text[-tail:]
    )


def _safe_json_dumps(data: Any) -> str:
    """以中文友好的方式序列化 JSON。"""
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _outline_text(outline: Dict[str, Any]) -> str:
    """提取参与 C1 审计的大纲字段。"""
    fields = {
        "chapter_number": outline.get("chapter_number"),
        "title": outline.get("title"),
        "key_points": outline.get("key_points", []),
        "characters": outline.get("characters", []),
        "settings": outline.get("settings", []),
        "conflicts": outline.get("conflicts", []),
        "emotion_tone": outline.get("emotion_tone", ""),
        "character_goals": outline.get("character_goals", {}),
        "scene_sequence": outline.get("scene_sequence", []),
        "foreshadowing": outline.get("foreshadowing", []),
        "pov_character": outline.get("pov_character", ""),
    }
    return _safe_json_dumps(fields)


def _normalize_chapter_numbers(chapter_numbers: Optional[Iterable[int]]) -> Optional[Set[int]]:
    """归一化用户请求的审计章节集合，None 表示整部审计。"""
    if chapter_numbers is None:
        return None
    normalized: Set[int] = set()
    for value in chapter_numbers:
        try:
            chapter_number = int(value)
        except (TypeError, ValueError):
            continue
        if chapter_number > 0:
            normalized.add(chapter_number)
    return normalized


def _normalize_batch_size(batch_size: Optional[int]) -> int:
    """归一化批大小，<=1 使用兼容的逐项审计。"""
    try:
        value = int(batch_size or 1)
    except (TypeError, ValueError):
        value = 1
    return max(1, value)


def _iter_batches(items: Sequence[Any], batch_size: int) -> Iterable[List[Any]]:
    """按固定大小切分列表，保持原始顺序。"""
    for index in range(0, len(items), batch_size):
        yield list(items[index:index + batch_size])


def _iter_prompt_budget_batches(
    items: Sequence[Any],
    batch_size: int,
    prompt_builder: Any,
) -> Iterable[Tuple[List[Any], str]]:
    """按批大小与提示词预算自适应切分审计批次。"""
    normalized_batch_size = _normalize_batch_size(batch_size)
    index = 0
    while index < len(items):
        max_end = min(len(items), index + normalized_batch_size)
        # 先整批构建一次：未超预算（常见情形）时避免逐项扩展的 O(k²) 重复构建
        full_batch = list(items[index:max_end])
        full_prompt = prompt_builder(full_batch)
        if len(full_prompt) <= CONTENT_AUDIT_PROMPT_MAX_CHARS or len(full_batch) == 1:
            # 单个章节/转场已经超预算时无法继续拆分，保留统计并交由 LLM 返回处理。
            yield full_batch, full_prompt
            index += len(full_batch)
            continue

        # 整批超预算：从单项起逐项扩展，取最长不超预算前缀
        selected_batch: List[Any] = []
        selected_prompt = ""
        probe_end = index
        while probe_end < max_end:
            candidate = list(items[index:probe_end + 1])
            candidate_prompt = prompt_builder(candidate)
            if len(candidate_prompt) <= CONTENT_AUDIT_PROMPT_MAX_CHARS:
                selected_batch = candidate
                selected_prompt = candidate_prompt
                probe_end += 1
                continue
            if not selected_batch:
                # 单个章节/转场已经超预算时无法继续拆分，保留统计并交由 LLM 返回处理。
                selected_batch = candidate
                selected_prompt = candidate_prompt
            break

        yield selected_batch, selected_prompt
        index += len(selected_batch)


def _update_prompt_stats(stats: Dict[str, int], prompt: str, item_count: int = 1) -> None:
    """记录 LLM 提示词与批量调用统计。"""
    prompt_len = len(prompt or "")
    stats["llm_prompt_max_chars"] = max(stats["llm_prompt_max_chars"], prompt_len)
    stats["llm_prompt_total_chars"] += prompt_len
    if prompt_len > CONTENT_AUDIT_PROMPT_MAX_CHARS:
        stats["llm_prompt_over_budget"] += 1
    stats["llm_calls"] += 1
    stats["llm_batch_items"] += max(1, int(item_count or 1))
    stats["llm_batch_max_items"] = max(stats["llm_batch_max_items"], max(1, int(item_count or 1)))


def _build_audit_scope(
    selected_chapters: Optional[Set[int]],
    batch_size: int,
    selected_records: Sequence[ChapterInput],
) -> Dict[str, Any]:
    """构造报告中的审计范围元数据。"""
    audited_numbers = [record.chapter_number for record in selected_records]
    requested = sorted(selected_chapters) if selected_chapters is not None else []
    return {
        "mode": "selected" if selected_chapters is not None else "all",
        "requested_chapters": requested,
        "audited_chapters": audited_numbers,
        "batch_size": batch_size,
    }


def _filter_outline_findings_for_scope(findings: List[Finding], selected_chapters: Optional[Set[int]]) -> List[Finding]:
    """局部审计时过滤范围外的大纲缺洞 fatal，避免干扰指定章节审计。"""
    if selected_chapters is None:
        return findings
    filtered: List[Finding] = []
    for finding in findings:
        if finding.rule_id == "C0" and finding.severity == "fatal" and finding.chapter not in selected_chapters:
            continue
        filtered.append(finding)
    return filtered


def _filter_content_findings_for_scope(findings: List[Finding], selected_chapters: Optional[Set[int]]) -> List[Finding]:
    """局部审计时过滤仅作为 C2 上下文加载章节产生的正文缺失问题。"""
    if selected_chapters is None:
        return findings
    return [finding for finding in findings if finding.chapter in selected_chapters or finding.chapter is None]


def _build_transition_context_findings(
    selected_chapters: Optional[Set[int]],
    outline_map: Dict[int, Dict[str, Any]],
    record_map: Dict[int, ChapterInput],
    content_findings: List[Finding],
) -> List[Finding]:
    """局部审计时显式提示上一章上下文缺失导致 C2 无法检查。"""
    if selected_chapters is None:
        return []

    source_findings = {
        finding.chapter: finding
        for finding in content_findings
        if finding.rule_id == "C0" and finding.chapter is not None and finding.severity == "fatal"
    }
    findings: List[Finding] = []
    for chapter_number in sorted(selected_chapters):
        if chapter_number <= 1 or chapter_number not in record_map:
            continue
        previous_chapter = chapter_number - 1
        if previous_chapter in record_map:
            continue
        if previous_chapter not in outline_map:
            reason = f"outline.json 缺少第 {previous_chapter} 章大纲。"
            evidence: Dict[str, Any] = {
                "previous_chapter": previous_chapter,
                "current_chapter": chapter_number,
                "context_role": "transition_previous_outline",
            }
        else:
            source = source_findings.get(previous_chapter)
            reason = source.message if source is not None else f"第 {previous_chapter} 章正文缺失或不可读取。"
            evidence = {
                "previous_chapter": previous_chapter,
                "current_chapter": chapter_number,
                "context_role": "transition_previous_content",
                "source_message": reason,
            }
        findings.append(Finding(
            "C0",
            "warning",
            "内容审计输入完整性",
            chapter_number,
            f"无法检查第 {previous_chapter} 章到第 {chapter_number} 章衔接：{reason}",
            evidence=evidence,
        ))
    return findings


# =====================================================================
# 输入加载与 C0 预检
# =====================================================================


def load_outline_map(outline_path: str) -> Tuple[Dict[int, Dict[str, Any]], List[Finding], Dict[str, int]]:
    """读取 outline.json 并按 chapter_number 建立映射。"""
    stats = _empty_stats()
    findings: List[Finding] = []
    with open(outline_path, "r", encoding="utf-8") as fp:
        outline_data = json.load(fp)

    chapters = outline_data.get("chapters", outline_data) if isinstance(outline_data, dict) else outline_data
    if not isinstance(chapters, list):
        findings.append(Finding(
            "C0",
            "fatal",
            "内容审计输入完整性",
            None,
            "outline.json 顶层格式无法识别，应为章节列表或包含 chapters 键的字典。",
            evidence={"outline_path": outline_path},
        ))
        return {}, findings, stats

    outline_map: Dict[int, Dict[str, Any]] = {}
    for index, item in enumerate(chapters):
        if item is None:
            continue
        if not isinstance(item, dict):
            stats["non_dict_outline_items"] += 1
            findings.append(Finding(
                "C0",
                "warning",
                "内容审计输入完整性",
                None,
                f"outline.json 第 {index + 1} 个条目不是对象，已跳过。",
                evidence={"index": index, "value_type": type(item).__name__},
            ))
            continue
        try:
            chapter_number = int(item.get("chapter_number"))
        except (TypeError, ValueError):
            findings.append(Finding(
                "C0",
                "warning",
                "内容审计输入完整性",
                None,
                f"outline.json 第 {index + 1} 个条目缺少有效 chapter_number，已跳过。",
                evidence={"index": index, "item": item},
            ))
            continue
        if chapter_number <= 0:
            findings.append(Finding(
                "C0",
                "warning",
                "内容审计输入完整性",
                None,
                f"outline.json 第 {index + 1} 个条目的 chapter_number 非正数，已跳过。",
                evidence={"index": index, "chapter_number": chapter_number},
            ))
            continue
        if chapter_number in outline_map:
            stats["duplicate_outline_chapters"] += 1
            findings.append(Finding(
                "C0",
                "warning",
                "内容审计输入完整性",
                chapter_number,
                f"outline.json 存在重复 chapter_number={chapter_number}，审计采用首次出现版本。",
                evidence={"chapter_number": chapter_number, "duplicate_index": index},
            ))
            continue
        outline_map[chapter_number] = item

    stats["outline_chapters"] = len(outline_map)
    if outline_map:
        max_chapter = max(outline_map)
        missing_outline_slots = [n for n in range(1, max_chapter + 1) if n not in outline_map]
        for chapter_number in missing_outline_slots:
            findings.append(Finding(
                "C0",
                "fatal",
                "内容审计输入完整性",
                chapter_number,
                f"outline.json 缺少第 {chapter_number} 章大纲，无法完整审计整部小说。",
                evidence={"chapter_number": chapter_number},
            ))
    return outline_map, findings, stats


def _is_content_candidate(filename: str, chapter_number: int) -> bool:
    """判断文件名是否可作为指定章节的正文候选。"""
    if not filename.endswith(".txt"):
        return False
    if "_摘要" in filename or "_imitated" in filename or "_original" in filename:
        return False
    match = _CONTENT_FILE_RE.match(filename)
    return bool(match and int(match.group(1)) == chapter_number)


def _safe_mtime(path: str) -> float:
    """获取文件修改时间；文件在排序期间被删除时返回 0 而非中断审计。"""
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def find_chapter_candidates(
    output_dir: str,
    chapter_number: int,
    outline: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """查找指定章节的正文候选文件，优先返回当前大纲标题对应文件。"""
    candidates: List[str] = []
    title = str((outline or {}).get("title") or "")
    if title:
        expected = os.path.join(output_dir, f"第{chapter_number}章_{_clean_filename(title)}.txt")
        if os.path.exists(expected):
            candidates.append(expected)

    try:
        for filename in os.listdir(output_dir):
            if not _is_content_candidate(filename, chapter_number):
                continue
            path = os.path.join(output_dir, filename)
            if path not in candidates:
                candidates.append(path)
    except OSError:
        return candidates

    candidates.sort(key=_safe_mtime, reverse=True)
    if title:
        expected_name = f"第{chapter_number}章_{_clean_filename(title)}.txt"
        candidates.sort(key=lambda path: 0 if os.path.basename(path) == expected_name else 1)
    return candidates


def load_chapter_inputs(
    output_dir: str,
    outline_map: Dict[int, Dict[str, Any]],
) -> Tuple[List[ChapterInput], List[Finding], Dict[str, int]]:
    """按大纲加载所有可审计的章节正文。"""
    stats = _empty_stats()
    findings: List[Finding] = []
    records: List[ChapterInput] = []

    for chapter_number in sorted(outline_map):
        outline = outline_map[chapter_number]
        candidates = find_chapter_candidates(output_dir, chapter_number, outline)
        if not candidates:
            stats["missing_chapters"] += 1
            findings.append(Finding(
                "C0",
                "fatal",
                "内容审计输入完整性",
                chapter_number,
                f"未找到第 {chapter_number} 章正文文件，无法审计该章正文与衔接。",
                evidence={"chapter_number": chapter_number, "output_dir": output_dir},
            ))
            continue
        if len(candidates) > 1:
            stats["chapters_with_multiple_candidates"] += 1
            findings.append(Finding(
                "C0",
                "warning",
                "内容审计输入完整性",
                chapter_number,
                f"第 {chapter_number} 章发现 {len(candidates)} 个候选正文文件，审计将使用最新/最匹配版本。",
                evidence={
                    "selected": candidates[0],
                    "candidates": candidates,
                },
            ))
        selected_path = candidates[0]
        try:
            with open(selected_path, "r", encoding="utf-8") as fp:
                content = _strip_markdown_heading(fp.read())
        except OSError as exc:
            findings.append(Finding(
                "C0",
                "fatal",
                "内容审计输入完整性",
                chapter_number,
                f"读取第 {chapter_number} 章正文失败：{exc}",
                evidence={"path": selected_path, "error": str(exc)},
            ))
            continue
        if not content.strip():
            stats["missing_chapters"] += 1
            findings.append(Finding(
                "C0",
                "fatal",
                "内容审计输入完整性",
                chapter_number,
                f"第 {chapter_number} 章正文为空，无法审计该章。",
                evidence={"path": selected_path},
            ))
            continue
        records.append(ChapterInput(chapter_number, outline, content, selected_path, candidates))

    stats["audited_chapters"] = len(records)
    return records, findings, stats


# =====================================================================
# LLM 审计
# =====================================================================


def _extract_json(raw: str) -> Optional[Any]:
    """从 LLM 返回中提取 JSON 对象或数组。"""
    text = str(raw or "").strip()
    if not text:
        return None
    # 优先尝试代码块内容，但失败时回退全文扫描——首个代码块可能是思考/示例而非结果
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.S | re.I)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except Exception:
            pass
    try:
        return json.loads(text)
    except Exception:
        pass

    starts = [idx for idx in (text.find("{"), text.find("[")) if idx >= 0]
    if not starts:
        return None
    start = min(starts)
    end_char = "}" if text[start] == "{" else "]"
    end = text.rfind(end_char)
    if end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return None


def _payload_items(payload: Any) -> List[Dict[str, Any]]:
    """把 LLM JSON 结果归一化为 finding item 列表。"""
    if payload is None:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("findings", "issues", "problems"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    if payload.get("severity") or payload.get("message"):
        return [payload]
    return []


def _build_chapter_prompt(record: ChapterInput) -> str:
    """构造 C1 章节正文与大纲一致性审计提示词。"""
    content = _compact_text(record.content)
    return f"""你在审核一部长篇小说已经生成的章节正文是否与章节大纲一致。

[规则 C1：章节正文与大纲一致性]
请判断正文是否与大纲一致或基本一致，重点看：关键事件、出场人物、场景、冲突、人物目标、场景顺序、伏笔、情绪基调。

严重程度标准：
- fatal：主线关键事件缺失/相反，核心人物状态或剧情目标明显冲突，导致该章不能视为按大纲完成。
- warning：局部关键点遗漏、顺序轻微错位、情绪或人物动机偏弱，但不影响章节主线成立。
- info：低风险提示或可接受差异。

只输出 JSON，不要多余文字。格式：
{{"findings":[{{"severity":"fatal|warning|info","message":"问题描述","evidence":{{"reason":"简短依据"}}}}]}}
若没有问题，输出：{{"findings":[]}}

[章节大纲]
{_outline_text(record.outline)}

[章节正文]
{content}
"""


def _build_transition_prompt(previous: ChapterInput, current: ChapterInput) -> str:
    """构造 C2 相邻章节衔接审计提示词。"""
    previous_tail = previous.content[-2200:]
    current_head = current.content[:2200]
    return f"""你在审核一部长篇小说相邻章节的衔接是否自然紧密。

[规则 C2：相邻章节衔接自然度]
请判断当前章开头是否自然承接上一章结尾，重点看：时间线、地点切换、人物状态、未完成动作、情绪延续、因果关系。

严重程度标准：
- fatal：上一章结尾与当前章开头在时间、地点、人物状态或因果上明显冲突/断裂。
- warning：可以理解但过渡生硬、信息跳跃、承接句不足。
- info：低风险提示。

只输出 JSON，不要多余文字。格式：
{{"findings":[{{"severity":"fatal|warning|info","message":"问题描述","evidence":{{"reason":"简短依据"}}}}]}}
若没有问题，输出：{{"findings":[]}}

[上一章信息]
第{previous.chapter_number}章：{previous.outline.get('title', '')}

[上一章结尾]
{previous_tail}

[当前章信息]
第{current.chapter_number}章：{current.outline.get('title', '')}

[当前章开头]
{current_head}
"""


def _build_chapter_batch_prompt(records: Sequence[ChapterInput]) -> str:
    """构造 C1 多章节批量审计提示词。"""
    chapters = []
    for record in records:
        chapters.append({
            "chapter": record.chapter_number,
            "outline": _outline_text(record.outline),
            "content": _compact_text(record.content),
        })
    return f"""你在批量审核一部长篇小说已经生成的章节正文是否与章节大纲一致。

[规则 C1：章节正文与大纲一致性]
请分别判断每一章正文是否与对应大纲一致或基本一致，重点看：关键事件、出场人物、场景、冲突、人物目标、场景顺序、伏笔、情绪基调。

严重程度标准：
- fatal：主线关键事件缺失/相反，核心人物状态或剧情目标明显冲突，导致该章不能视为按大纲完成。
- warning：局部关键点遗漏、顺序轻微错位、情绪或人物动机偏弱，但不影响章节主线成立。
- info：低风险提示或可接受差异。

只输出 JSON，不要多余文字。每条 finding 必须包含 rule="C1" 和 chapter。格式：
{{"findings":[{{"rule":"C1","chapter":1,"severity":"fatal|warning|info","message":"问题描述","evidence":{{"reason":"简短依据"}}}}]}}
若没有问题，输出：{{"findings":[]}}

[待审计章节]
{_safe_json_dumps(chapters)}
"""


def _build_transition_batch_prompt(pairs: Sequence[Tuple[ChapterInput, ChapterInput]]) -> str:
    """构造 C2 多个相邻章节对的批量审计提示词。"""
    transitions = []
    for previous, current in pairs:
        transitions.append({
            "previous_chapter": previous.chapter_number,
            "previous_title": previous.outline.get("title", ""),
            "previous_tail": previous.content[-2200:],
            "chapter": current.chapter_number,
            "current_title": current.outline.get("title", ""),
            "current_head": current.content[:2200],
        })
    return f"""你在批量审核一部长篇小说相邻章节的衔接是否自然紧密。

[规则 C2：相邻章节衔接自然度]
请分别判断每组当前章开头是否自然承接上一章结尾，重点看：时间线、地点切换、人物状态、未完成动作、情绪延续、因果关系。

严重程度标准：
- fatal：上一章结尾与当前章开头在时间、地点、人物状态或因果上明显冲突/断裂。
- warning：可以理解但过渡生硬、信息跳跃、承接句不足。
- info：低风险提示。

只输出 JSON，不要多余文字。每条 finding 必须包含 rule="C2"、previous_chapter 和 chapter，其中 chapter 表示当前章。格式：
{{"findings":[{{"rule":"C2","previous_chapter":1,"chapter":2,"severity":"fatal|warning|info","message":"问题描述","evidence":{{"reason":"简短依据"}}}}]}}
若没有问题，输出：{{"findings":[]}}

[待审计相邻章节对]
{_safe_json_dumps(transitions)}
"""


def _call_llm_for_findings(
    model: Any,
    prompt: str,
    rule_id: str,
    title: str,
    chapter_number: int,
    stats: Dict[str, int],
    base_evidence: Optional[Dict[str, Any]] = None,
) -> List[Finding]:
    """调用 LLM 并把返回 JSON 转换为 Finding 列表。"""
    _update_prompt_stats(stats, prompt, item_count=1)
    try:
        raw = model.generate(prompt, **CONTENT_AUDIT_GENERATE_KWARGS)
    except Exception as exc:
        stats["llm_call_failures"] += 1
        return [Finding(
            rule_id,
            "warning",
            title,
            chapter_number,
            f"第 {chapter_number} 章 {title} LLM 审计调用失败，需人工确认：{exc}",
            evidence={**(base_evidence or {}), "error": str(exc)},
        )]

    payload = _extract_json(raw)
    if payload is None:
        stats["llm_parse_failures"] += 1
        return [Finding(
            rule_id,
            "warning",
            title,
            chapter_number,
            f"第 {chapter_number} 章 {title} LLM 返回无法解析，需人工确认。",
            evidence={**(base_evidence or {}), "raw_response": str(raw)[:800]},
        )]

    findings: List[Finding] = []
    for item in _payload_items(payload):
        severity = _normalize_severity(item.get("severity"))
        message = str(item.get("message") or item.get("reason") or "LLM 标记了潜在问题")
        evidence = dict(base_evidence or {})
        item_evidence = item.get("evidence")
        if isinstance(item_evidence, dict):
            evidence.update(item_evidence)
        else:
            reason = item.get("reason")
            if reason:
                evidence["reason"] = str(reason)
        findings.append(Finding(rule_id, severity, title, chapter_number, message, evidence=evidence or None))
    return findings


def _call_llm_for_batch_findings(
    model: Any,
    prompt: str,
    default_rule_id: str,
    title_by_rule: Dict[str, str],
    allowed_rules: Set[str],
    evidence_by_key: Dict[Tuple[str, int], Dict[str, Any]],
    stats: Dict[str, int],
    item_count: int,
) -> List[Finding]:
    """调用 LLM 并解析批量章节/转场审计结果。"""
    _update_prompt_stats(stats, prompt, item_count=item_count)
    try:
        raw = model.generate(prompt, **CONTENT_AUDIT_GENERATE_KWARGS)
    except Exception as exc:
        stats["llm_call_failures"] += 1
        # 与逐项路径对齐：批量失败时为批内每个章节生成归属明确的 finding，
        # 避免只留一条无章节号的提示导致修订流程无法定位受影响章节。
        return [Finding(
            rule_id,
            "warning",
            title_by_rule.get(rule_id, "章节内容审计"),
            chapter_number,
            f"第 {chapter_number} 章批量 LLM 审计调用失败，需人工确认：{exc}",
            evidence={**evidence, "error": str(exc)},
        ) for (rule_id, chapter_number), evidence in sorted(evidence_by_key.items())]

    payload = _extract_json(raw)
    if payload is None:
        stats["llm_parse_failures"] += 1
        return [Finding(
            rule_id,
            "warning",
            title_by_rule.get(rule_id, "章节内容审计"),
            chapter_number,
            f"第 {chapter_number} 章批量 LLM 审计返回无法解析，需人工确认。",
            evidence={**evidence, "raw_response": str(raw)[:800]},
        ) for (rule_id, chapter_number), evidence in sorted(evidence_by_key.items())]

    findings: List[Finding] = []
    for item in _payload_items(payload):
        rule_id = str(item.get("rule") or item.get("rule_id") or default_rule_id).strip().upper()
        if rule_id not in allowed_rules:
            stats["llm_findings_unknown_rule"] += 1
            continue
        try:
            chapter_number = int(item.get("chapter") or item.get("chapter_number"))
        except (TypeError, ValueError):
            stats["llm_findings_missing_chapter"] += 1
            continue
        evidence = dict(evidence_by_key.get((rule_id, chapter_number), {}))
        if not evidence:
            stats["llm_findings_unknown_chapter"] += 1
            continue
        severity = _normalize_severity(item.get("severity"))
        message = str(item.get("message") or item.get("reason") or "LLM 标记了潜在问题")
        item_evidence = item.get("evidence")
        if isinstance(item_evidence, dict):
            evidence.update(item_evidence)
        elif item.get("reason"):
            evidence["reason"] = str(item.get("reason"))
        findings.append(Finding(
            rule_id,
            severity,
            title_by_rule.get(rule_id, "章节内容审计"),
            chapter_number,
            message,
            evidence=evidence or None,
        ))
    return findings


def audit_chapter_consistency(
    records: List[ChapterInput],
    model: Any,
    stats: Dict[str, int],
    stop_event: Any = None,
    batch_size: int = 1,
) -> List[Finding]:
    """C1：审计正文与大纲一致性，支持多章节批量调用。"""
    findings: List[Finding] = []
    batch_size = _normalize_batch_size(batch_size)
    if batch_size <= 1:
        for record in records:
            if _is_cancelled(stop_event):
                stats["stopped"] = 1
                break
            stats["chapter_checks"] += 1
            stats["chapter_check_batches"] += 1
            findings.extend(_call_llm_for_findings(
                model,
                _build_chapter_prompt(record),
                "C1",
                "章节正文与大纲一致性",
                record.chapter_number,
                stats,
                base_evidence={"content_path": record.path},
            ))
        return findings

    for batch, prompt in _iter_prompt_budget_batches(records, batch_size, _build_chapter_batch_prompt):
        if _is_cancelled(stop_event):
            stats["stopped"] = 1
            break
        stats["chapter_checks"] += len(batch)
        stats["chapter_check_batches"] += 1
        evidence_by_key = {
            ("C1", record.chapter_number): {"content_path": record.path}
            for record in batch
        }
        findings.extend(_call_llm_for_batch_findings(
            model,
            prompt,
            "C1",
            {"C1": "章节正文与大纲一致性"},
            {"C1"},
            evidence_by_key,
            stats,
            item_count=len(batch),
        ))
    return findings


def audit_transitions(
    records: List[ChapterInput],
    model: Any,
    stats: Dict[str, int],
    stop_event: Any = None,
    target_chapters: Optional[Set[int]] = None,
    batch_size: int = 1,
) -> List[Finding]:
    """C2：审计当前章开头与上一章结尾的衔接，支持批量调用。"""
    findings: List[Finding] = []
    record_map = {record.chapter_number: record for record in records}
    pairs: List[Tuple[ChapterInput, ChapterInput]] = []
    for chapter_number in sorted(record_map):
        if chapter_number <= 1:
            continue
        if target_chapters is not None and chapter_number not in target_chapters:
            continue
        previous = record_map.get(chapter_number - 1)
        current = record_map[chapter_number]
        if previous is None:
            continue
        pairs.append((previous, current))

    batch_size = _normalize_batch_size(batch_size)
    if batch_size <= 1:
        for previous, current in pairs:
            if _is_cancelled(stop_event):
                stats["stopped"] = 1
                break
            stats["transition_checks"] += 1
            stats["transition_check_batches"] += 1
            findings.extend(_call_llm_for_findings(
                model,
                _build_transition_prompt(previous, current),
                "C2",
                "相邻章节衔接自然度",
                current.chapter_number,
                stats,
                base_evidence={
                    "previous_chapter": previous.chapter_number,
                    "previous_path": previous.path,
                    "current_path": current.path,
                },
            ))
        return findings

    for batch, prompt in _iter_prompt_budget_batches(pairs, batch_size, _build_transition_batch_prompt):
        if _is_cancelled(stop_event):
            stats["stopped"] = 1
            break
        stats["transition_checks"] += len(batch)
        stats["transition_check_batches"] += 1
        evidence_by_key = {
            ("C2", current.chapter_number): {
                "previous_chapter": previous.chapter_number,
                "previous_path": previous.path,
                "current_path": current.path,
            }
            for previous, current in batch
        }
        findings.extend(_call_llm_for_batch_findings(
            model,
            prompt,
            "C2",
            {"C2": "相邻章节衔接自然度"},
            {"C2"},
            evidence_by_key,
            stats,
            item_count=len(batch),
        ))
    return findings


# =====================================================================
# 聚合与报告
# =====================================================================


def _merge_stats(target: Dict[str, int], source: Dict[str, int]) -> None:
    """把 source 统计累加到 target。"""
    for key, value in source.items():
        target[key] = target.get(key, 0) + int(value)


def run_audit(
    output_dir: str,
    outline_path: Optional[str] = None,
    model: Any = None,
    stop_event: Any = None,
    chapter_numbers: Optional[Iterable[int]] = None,
    batch_size: Optional[int] = None,
) -> LLMReviewResult:
    """运行小说章节内容审计，支持整部或指定章节范围。

    Args:
        output_dir: 章节正文所在输出目录。
        outline_path: outline.json 路径，默认使用 output_dir/outline.json。
        model: 可选 LLM 模型；未提供时只执行 C0 预检。
        stop_event: 可选停止事件，触发后在章节边界停止。
        chapter_numbers: 可选章节集合；为空时审计整部小说。
        batch_size: LLM 批量审计大小，None/1 表示逐项审计。

    Returns:
        结构化审计结果与统计。
    """
    outline_path = outline_path or os.path.join(output_dir, "outline.json")
    stats = _empty_stats()
    findings: List[Finding] = []
    selected_chapters = _normalize_chapter_numbers(chapter_numbers)
    resolved_batch_size = _normalize_batch_size(batch_size)

    outline_map, outline_findings, outline_stats = load_outline_map(outline_path)
    outline_findings = _filter_outline_findings_for_scope(outline_findings, selected_chapters)
    findings.extend(outline_findings)
    _merge_stats(stats, outline_stats)

    if selected_chapters is not None:
        stats["requested_chapters"] = len(selected_chapters)
        missing_outline = sorted(chapter for chapter in selected_chapters if chapter not in outline_map)
        stats["selection_missing_outline_chapters"] = len(missing_outline)
        for chapter_number in missing_outline:
            findings.append(Finding(
                "C0",
                "fatal",
                "内容审计输入完整性",
                chapter_number,
                f"请求审计第 {chapter_number} 章，但 outline.json 缺少该章大纲。",
                evidence={"chapter_number": chapter_number},
            ))

        load_chapters = set(selected_chapters & set(outline_map))
        load_chapters.update(chapter - 1 for chapter in selected_chapters if chapter > 1 and chapter - 1 in outline_map)
        scoped_outline_map = {chapter: outline_map[chapter] for chapter in sorted(load_chapters)}
    else:
        scoped_outline_map = outline_map

    records, content_findings, content_stats = load_chapter_inputs(output_dir, scoped_outline_map)
    record_map = {record.chapter_number: record for record in records}
    transition_context_findings = _build_transition_context_findings(
        selected_chapters,
        outline_map,
        record_map,
        content_findings,
    )
    content_findings = _filter_content_findings_for_scope(content_findings, selected_chapters)
    findings.extend(content_findings)
    findings.extend(transition_context_findings)
    _merge_stats(stats, content_stats)

    if selected_chapters is None:
        selected_records = records
        transition_records = records
    else:
        selected_records = [record_map[chapter] for chapter in sorted(selected_chapters) if chapter in record_map]
        transition_context_numbers = {
            record.chapter_number for record in records
            if record.chapter_number not in selected_chapters
        }
        stats["context_chapters_loaded"] = len(transition_context_numbers)
        stats["selected_chapters"] = len(selected_records)
        stats["audited_chapters"] = len(selected_records)
        stats["skipped_unselected_chapters"] = max(0, stats.get("outline_chapters", 0) - len(selected_chapters))
        stats["selection_missing_content_chapters"] = len([
            chapter for chapter in selected_chapters
            if chapter in outline_map and chapter not in record_map
        ])
        transition_records = records

    if selected_chapters is None:
        stats["selected_chapters"] = len(selected_records)

    if model is not None and selected_records and not _is_cancelled(stop_event):
        findings.extend(audit_chapter_consistency(
            selected_records,
            model,
            stats,
            stop_event=stop_event,
            batch_size=resolved_batch_size,
        ))
        if not _is_cancelled(stop_event):
            findings.extend(audit_transitions(
                transition_records,
                model,
                stats,
                stop_event=stop_event,
                target_chapters=selected_chapters,
                batch_size=resolved_batch_size,
            ))
    elif _is_cancelled(stop_event):
        stats["stopped"] = 1

    stats["llm_findings"] = len([f for f in findings if f.rule_id in ("C1", "C2")])
    stats["llm_fatal_findings"] = len([f for f in findings if f.rule_id in ("C1", "C2") and f.severity == "fatal"])
    stats["llm_warning_findings"] = len([f for f in findings if f.rule_id in ("C1", "C2") and f.severity == "warning"])
    stats["llm_info_findings"] = len([f for f in findings if f.rule_id in ("C1", "C2") and f.severity == "info"])
    if stats["llm_calls"]:
        stats["llm_prompt_avg_chars"] = stats["llm_prompt_total_chars"] // stats["llm_calls"]
    audit_scope = _build_audit_scope(selected_chapters, resolved_batch_size, selected_records)
    return LLMReviewResult(findings=findings, stats=stats, audit_scope=audit_scope)


def build_report(
    result: LLMReviewResult,
    output_dir: str,
    outline_path: str,
    llm_enabled: bool,
    llm_model_type: str = "unknown",
) -> Dict[str, Any]:
    """构造可落盘的章节内容审计报告。"""
    fatal = [finding for finding in result.findings if finding.severity == "fatal"]
    warning = [finding for finding in result.findings if finding.severity == "warning"]
    info = [finding for finding in result.findings if finding.severity == "info"]
    return {
        "content_dir": output_dir,
        "outline": outline_path,
        "chapters": result.stats.get("outline_chapters", 0),
        "audited_chapters": result.stats.get("audited_chapters", 0),
        "total_findings": len(result.findings),
        "fatal": len(fatal),
        "warning": len(warning),
        "info": len(info),
        "llm_enabled": llm_enabled,
        "llm_model_type": llm_model_type,
        "audit_scope": result.audit_scope or {"mode": "all", "requested_chapters": [], "audited_chapters": []},
        "llm_stats": result.stats,
        "findings": [serialize_finding(finding) for finding in result.findings],
    }
