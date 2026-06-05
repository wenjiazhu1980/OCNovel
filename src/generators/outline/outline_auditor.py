# -*- coding: utf-8 -*-
"""大纲全局审计器核心 - 检测剧情不闭环 / 伏笔不回收等结构性缺陷

对整本大纲（章节 dict 列表）做全局静态审计，输出结构化问题清单 List[Finding]。
弥补逐章一致性检查（ConsistencyChecker / ThunderPointValidator）无法覆盖的
"跨章伏笔闭环 / 事件线收口 / 人物身份一致性"盲区。

- 算法层（O1-O5）：纯算法初筛，不调 LLM，高召回标记嫌疑。
- LLM 层（llm_review_task_closure）：对算法初筛做语义裁决（需传入 model）。

CLI 封装见 tools/audit_outline.py；流水线终局闸门见 OutlineGenerator._run_outline_audit。
"""

from __future__ import annotations

import json as _json
import re
from dataclasses import dataclass
from typing import Dict, List, Optional


# =====================================================================
# 数据结构
# =====================================================================

@dataclass
class Finding:
    """单条审计发现"""
    rule_id: str             # "O1".."O5" / "O3-LLM"
    severity: str            # "fatal" | "warning" | "info"
    title: str               # 规则名
    chapter: Optional[int]   # 相关章节号（埋设章/首现章等），无则 None
    message: str             # 具体描述
    evidence: Optional[Dict] = None  # 供报告消费的结构化证据


@dataclass
class LLMReviewResult:
    """LLM 复核结果与运行统计。"""
    findings: List[Finding]
    stats: Dict[str, int]
    superseded_task_keys: Optional[set] = None


def serialize_finding(finding: Finding) -> Dict:
    """把 Finding 转为报告可直接落盘的 dict。"""
    data = {
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
# 文本工具
# =====================================================================

def _hanzi_bigrams(text: str) -> set:
    """提取文本中的汉字 2-gram 集合，用于实体级模糊匹配。"""
    bigrams = set()
    for seg in re.findall(r"[一-鿿]+", text or ""):
        for i in range(len(seg) - 1):
            bigrams.add(seg[i:i + 2])
    return bigrams


_PREFIX_RE = re.compile(r"^\s*([^：:]{1,12})[：:]\s*(.*)$", re.S)
_RECOVER_KEYS = ("回收", "呼应", "揭晓", "兑现", "收束", "应验", "揭破")
_BURY_KEYS = ("埋设", "埋下", "铺垫", "伏笔", "预示", "暗示")


def _classify_foreshadow(item: str):
    """解析一条 foreshadowing，返回 (kind, body)。

    kind: 'bury' | 'recover' | 'other'
    复合前缀（如"回收并埋设"）只要含回收关键词即视为 recover（回收优先）。
    """
    m = _PREFIX_RE.match(item or "")
    prefix = m.group(1) if m else ""
    body = m.group(2) if m else (item or "")
    if any(k in prefix for k in _RECOVER_KEYS):
        return "recover", body
    if any(k in prefix for k in _BURY_KEYS):
        return "bury", body
    return "other", body


# =====================================================================
# O1 伏笔埋设-回收配对
# =====================================================================

# 匹配阈值：埋设与某回收条目共享的汉字 bigram 数 ≥ 此值即视为已回收。
# 取 2 偏严：宁可把"已回收但措辞差异大"的误报为悬挂（人工/LLM 复核排除），
# 也不漏报真正悬挂的伏笔（初筛高召回优先）。
_O1_MATCH_THRESHOLD = 2


def audit_foreshadowing(chapters: List[dict]) -> List[Finding]:
    """O1：找出全书埋设却未见回收的悬挂伏笔。"""
    buries = []    # [(chapter_number, body, bigrams)]
    recover_kw: List[set] = []
    for ch in chapters:
        if not ch:
            continue
        n = ch.get("chapter_number")
        for item in ch.get("foreshadowing", []) or []:
            kind, body = _classify_foreshadow(item)
            kw = _hanzi_bigrams(body)
            if kind == "bury":
                buries.append((n, body, kw))
            elif kind == "recover":
                recover_kw.append(kw)

    findings: List[Finding] = []
    for n, body, kw in buries:
        if not kw:
            continue
        recovered = any(len(kw & rkw) >= _O1_MATCH_THRESHOLD for rkw in recover_kw)
        if not recovered:
            findings.append(Finding(
                rule_id="O1",
                severity="warning",
                title="伏笔埋设-回收配对",
                chapter=n,
                message=f"第{n}章埋设的伏笔疑似全书未回收：{body[:50]}",
            ))
    return findings


# =====================================================================
# O2 命名实体生命线断裂
# =====================================================================

def _normalize_name(name: str) -> str:
    """归一化角色名：去除括号注释与首尾空白。

    '张铁柱（退休老刑警）' / '张铁柱(引荐人)' → '张铁柱'
    """
    return re.sub(r"[（(].*?[）)]", "", name or "").strip()


_ENTITY_ALIAS = {
    "晏天官": "律法监察使",
    "天庭监察使": "律法监察使",
    "监察使": "律法监察使",
    "花璇玑": "律法监察使",
    "旧世家老祖": "世家老祖",
    "明月": "澹台明月",
}

_IMPORTANT_ENTITY_RE = re.compile(
    r"(主角|女主|男主|红颜|导师|师尊|师父|师傅|道侣|伙伴|挚友|主反派|反派|"
    r"宁芷|澹台明月|马爷|魔猿|少年祖师)"
)
_MINOR_ENTITY_RE = re.compile(
    r"(部下|斥候|统领|领队|教众|群众|士兵|军团|部众|先遣|暗桩|留耳|精锐|弟子)$"
)
_DEFINITE_CLOSURE_RE = re.compile(
    r"(死亡|死去|战死|阵亡|身亡|陨灭|陨落|被杀|杀死|斩杀|击杀|轰碎|"
    r"斩灭|斩碎|粉碎|秒杀|压成肉泥|打得粉碎|形神俱灭|神魂俱灭|"
    r"魂飞魄散|一分为二|生机彻底断绝|灵魂永远|彻底切断|"
    r"一击轰碎|肉身压成肉泥)"
)
_SOFT_CLOSURE_RE = re.compile(
    r"(重创|击退|败退|退兵|隐去|断后|归隐|告别|拜别|离去|离开|"
    r"摆脱宿命|建立了?新的传承|立下.*契约|收束|化解|暂时守住)"
)


def _canonical_entity_name(raw: str) -> str:
    """实体名归一化：去括号、处理常见别名。"""
    nm = _normalize_name(raw)
    if not nm:
        return ""
    if nm in _ENTITY_ALIAS:
        return _ENTITY_ALIAS[nm]
    if "监察使" in nm:
        return "律法监察使"
    return nm


def _entity_importance(name: str) -> str:
    """粗粒度区分功能性群体与普通/重要实体。"""
    if _MINOR_ENTITY_RE.search(name or ""):
        return "minor"
    if _IMPORTANT_ENTITY_RE.search(name or ""):
        return "important"
    return "normal"


def _text_mentions_entity(text: str, entity: str) -> bool:
    """判断自由文本是否提到某个已归一化实体。"""
    text = text or ""
    if not entity:
        return False
    if entity in text or _canonical_entity_name(text) == entity:
        return True
    for alias, canonical in _ENTITY_ALIAS.items():
        if canonical == entity and alias in text:
            return True
    if entity == "律法监察使" and "监察使" in text:
        return True
    return False


def _chapter_entity_context(ch: dict, entity: str) -> str:
    """提取实体所在章节的紧凑上下文，供 evidence 展示。"""
    parts: List[str] = []
    title = ch.get("title") or ""
    if title:
        parts.append(f"标题：{title}")
    for field in ("characters", "key_points", "conflicts", "settings", "foreshadowing"):
        values = ch.get(field, []) or []
        for item in values:
            text = str(item)
            if _text_mentions_entity(text, entity):
                parts.append(text)
    if not parts:
        parts.extend(str(x) for x in (ch.get("key_points", []) or [])[:2])
    return " / ".join(parts)[:500]


def _detect_entity_closure(ch: dict, entity: str) -> Optional[Dict[str, str]]:
    """识别实体末次出现上下文中的退场/收口信号。"""
    context = _chapter_entity_context(ch, entity)
    m = _DEFINITE_CLOSURE_RE.search(context)
    if m:
        return {"type": "definitive", "keyword": m.group(0), "context": context}
    m = _SOFT_CLOSURE_RE.search(context)
    if m:
        return {"type": "soft", "keyword": m.group(0), "context": context}
    return None


def _sample_occurrences(chs: List[int]) -> List[int]:
    """保留首尾样本，避免报告过长。"""
    if len(chs) <= 8:
        return chs
    return chs[:4] + chs[-4:]


def audit_entities(
    chapters: List[dict],
    min_occurrences: int = 3,
    early_cutoff_ratio: float = 0.6,
) -> List[Finding]:
    """O2：找出前期有存在感、却在中前期就断崖消失的命名实体。

    Args:
        min_occurrences: 至少出现这么多次才算"有存在感的线索"（滤掉一次性龙套）
        early_cutoff_ratio: 末次出现位置 / 总章数 < 此值即视为中前期消失
    """
    nums = [c.get("chapter_number") for c in chapters if c and c.get("chapter_number")]
    total = max(nums) if nums else 0
    appear: Dict[str, List[int]] = {}
    by_num = {c.get("chapter_number"): c for c in chapters if c and c.get("chapter_number")}
    for ch in chapters:
        if not ch:
            continue
        n = ch.get("chapter_number")
        names = {_canonical_entity_name(x) for x in (ch.get("characters", []) or [])}
        for nm in names:
            if nm:
                appear.setdefault(nm, []).append(n)

    findings: List[Finding] = []
    for nm, chs in sorted(appear.items(), key=lambda kv: kv[1][0]):
        chs = sorted(chs)
        if len(chs) < min_occurrences:
            continue
        last = chs[-1]
        if total > 0 and last / total < early_cutoff_ratio:
            last_context_chapter = by_num.get(last, {})
            closure = _detect_entity_closure(last_context_chapter, nm)
            if closure and closure["type"] == "definitive":
                continue
            importance = _entity_importance(nm)
            severity = "info" if importance == "minor" or closure else "warning"
            closure_suffix = ""
            if closure:
                closure_suffix = f"，但末次出现含疑似收口信号“{closure['keyword']}”"
            findings.append(Finding(
                rule_id="O2",
                severity=severity,
                title="命名实体生命线断裂",
                chapter=chs[0],
                message=(
                    f"实体『{nm}』在第{chs[0]}–{last}章出现{len(chs)}次后消失"
                    f"（末次第{last}章/共{total}章）{closure_suffix}，疑似线索中断未收口"
                ),
                evidence={
                    "entity": nm,
                    "importance": importance,
                    "first_chapter": chs[0],
                    "last_chapter": last,
                    "occurrence_count": len(chs),
                    "sample_occurrences": _sample_occurrences(chs),
                    "last_context": _chapter_entity_context(last_context_chapter, nm),
                    "possible_closure_context": closure["context"] if closure else "",
                    "closure_type": closure["type"] if closure else "",
                    "closure_keyword": closure["keyword"] if closure else "",
                },
            ))
    return findings


# =====================================================================
# O3 系统任务闭环
# =====================================================================

_TASK_MARKER_RE = re.compile(
    r"系统[^。；\n]{0,32}(?:发布|更新|下达|推送|布置|追加|弹出|触发|出现|浮现)[^。；\n]{0,18}(?:新)?任务(?!完成|达成|办结|结算|完结)|"
    r"系统任务(?:弹出|出现|浮现|触发)"
)
_TASK_METADATA_RE = re.compile(
    r"(?:任务奖励|奖励|评估|风险等级|警告|同时提示|并提示|系统提示)[：:]"
)
_TASK_DONE_RE = re.compile(
    r"任务(?:完成|达成|办结|结算|完结)|完成[^。；\n]{0,8}任务|"
    r"(?:至此)?正式办结|办结的结果|顺利进行|平静顺利|顺利完成|"
    r"最后的?[‘']?净化|初步解决|暂时解决|彻底解决|关键修复|"
    r"成功(?:净化|调解|引导|化解|清理|稳定)|"
    r"回收[：:][^。\n]{0,120}(?:第\d+章|任务|事件|线索|伏笔)"
)


def _split_context_units(text: str) -> List[str]:
    """按大纲条目/句段拆分文本，保留较长 key point 的完整相关上下文。"""
    units: List[str] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        units.append(line)
    return units


def _trim_task_metadata(desc: str) -> str:
    """去掉奖励/评估等非任务目标信息，保留任务主体。"""
    desc = (desc or "").strip(" \t\n\r：:'‘’“”「」")
    m = _TASK_METADATA_RE.search(desc)
    if m and m.start() >= 4:
        desc = desc[:m.start()]
    return desc.strip(" \t\n\r。；;，,：:'‘’“”「」")


def _capture_task_description(text: str, start: int) -> str:
    """从任务标记后捕获完整任务句段，尽量保留中文引号/括号/编号复合任务。"""
    tail = (text or "")[start:]
    title = ""
    title_match = re.match(r"\s*[：:]\s*【([^】]{1,40})】\s*(?:[—\-–-]{1,2})?", tail)
    if title_match:
        title = title_match.group(1).strip()
        tail = tail[title_match.end():]
    stripped = tail.lstrip()
    if stripped.startswith(("：", ":")):
        tail = stripped[1:]
    tail = tail.lstrip(" \t，,:：")
    if not tail:
        return title

    # 如果任务以引号包裹，优先截到“后接标点/行尾”的右引号，避免被内部名词引号截断。
    if tail[0] in "‘“「'\"":
        close_chars = {"‘": "’", "“": "”", "「": "」", "'": "'", '"': '"'}
        close = close_chars[tail[0]]
        for i, ch in enumerate(tail[1:], 1):
            if ch != close:
                continue
            nxt = tail[i + 1:i + 2]
            if not nxt or nxt in "。；;，,、）)]】》":
                desc = _trim_task_metadata(tail[1:i])
                return f"{title}：{desc}" if title and title not in desc else desc

    # 无明确外层引号时取整条大纲条目；复合编号任务常用分号连接，不能按第一个分号截断。
    desc = re.split(r"\n", tail, maxsplit=1)[0]
    desc = _trim_task_metadata(desc)
    return f"{title}：{desc}" if title and title not in desc else desc


def _extract_published_tasks_from_text(text: str) -> List[str]:
    """提取一个章节文本中的系统任务描述。"""
    tasks: List[str] = []
    for unit in _split_context_units(text):
        for m in _TASK_MARKER_RE.finditer(unit):
            desc = _capture_task_description(unit, m.end())
            if len(_hanzi_bigrams(desc)) >= 2:
                tasks.append(desc)
    return tasks


def _task_key(chapter: int, desc: str) -> tuple:
    """生成任务去重键；同章同任务由 LLM 结果覆盖算法 O3 结果。"""
    return chapter, "".join(re.findall(r"[一-鿿A-Za-z0-9]+", desc or ""))[:80]


def _chapter_fulltext(ch: dict) -> str:
    """汇总一章中承载情节的文本字段，供任务/身份检索。"""
    parts: List[str] = []
    parts += ch.get("key_points", []) or []
    parts += ch.get("foreshadowing", []) or []
    return "\n".join(parts)


def _relevant_context(text: str, task_kw: set, limit: int = 1200) -> str:
    """提取与任务/完成信号相关的完整条目，而不是固定截取前 N 字。"""
    selected: List[str] = []
    for unit in _split_context_units(text):
        if _TASK_DONE_RE.search(unit) or len(task_kw & _hanzi_bigrams(unit)) >= 1:
            selected.append(unit)
    if not selected:
        selected = _split_context_units(text)[:2]
    context = "\n".join(selected).strip()
    return context[:limit]


def audit_task_closure(chapters: List[dict], match_threshold: int = 2) -> List[Finding]:
    """O3：找出"系统发布任务"后全书无对应"任务完成"的悬置事件。"""
    published = []    # [(chapter, desc, kw)]
    completion = []   # [(chapter, fulltext_bigrams)]
    for ch in chapters:
        if not ch:
            continue
        n = ch.get("chapter_number")
        text = _chapter_fulltext(ch)
        for desc in _extract_published_tasks_from_text(text):
            published.append((n, desc, _hanzi_bigrams(desc)))
        if _TASK_DONE_RE.search(text):
            completion.append((n, _hanzi_bigrams(text)))

    findings: List[Finding] = []
    for n, desc, kw in published:
        if not kw:
            continue
        closed = any(
            cn >= n and len(kw & ckw) >= match_threshold
            for cn, ckw in completion
        )
        if not closed:
            findings.append(Finding(
                rule_id="O3",
                severity="fatal",
                title="系统任务闭环",
                chapter=n,
                message=(
                    f"第{n}章发布的系统任务疑似未闭环"
                    f"（后续无关键词匹配的'任务完成'）：{desc[:40]}"
                ),
                evidence={
                    "task_description": desc,
                    "task_key": _task_key(n, desc)[1],
                },
            ))
    return findings


# =====================================================================
# O4 人物身份一致性
# =====================================================================

# 明确的职业/社会角色词（通常互斥）；同义词通过 _IDENTITY_CANON 归并
_IDENTITY_WORDS = [
    "刑警", "警察", "警官", "捕快", "医生", "大夫", "郎中", "护士",
    "教师", "老师", "教授", "律师", "记者", "老板", "混混", "道士",
    "和尚", "尼姑", "商人", "工人", "司机", "保安", "会计", "侦探",
    "特工", "杀手", "佣兵", "镖师", "厨师", "木匠", "铁匠", "巫师",
    "法师", "骑士", "船长", "士兵", "将军", "学生", "教练",
]
_IDENTITY_CANON = {
    "大夫": "医生", "郎中": "医生",
    "警官": "警察", "刑警": "警察", "捕快": "警察",
    "教师": "老师", "教授": "老师",
}
_IDENTITY_NOTE_SPLIT_RE = re.compile(r"——|--|[，,。；;、]")
_IDENTITY_ACTION_PREFIX_RE = re.compile(
    r"^(本章核心|侧写|补充分析|"
    r"在|从|将|把|对|为|与|因|率|亲自|"
    r"执行|设计|发现|分析|决定|面对|追回|记录|允许|提出|宣布|下令|"
    r"接到|得知|巡视|做出|选择|抓捕|供述|展开|转述|确认|总结|观察|"
    r"处理|研发|主动|私下|夜间|清晨|午后|傍晚|深夜|完成|开始|继续|"
    r"透露|解释|感谢|告知|签订|试制)"
)
_IDENTITY_CONTEXT_SUFFIX = ("铺", "坊", "工具", "技艺", "工坊", "器械", "农具")


def _canon_identity(word: str) -> str:
    return _IDENTITY_CANON.get(word, word)


def _paren_note(raw: str) -> str:
    """提取角色条目的括号注释内容。'张铁柱（退休老刑警）' → '退休老刑警'。"""
    m = re.search(r"[（(](.*?)[）)]", raw or "")
    return m.group(1) if m else ""


def _extract_identity_from_note(note: str) -> List[str]:
    """从角色括号注释中提取可信身份词。

    仅把括号开头的短身份描述视为身份源，避免把长叙述中提到的其他人物、
    场景或道具误绑定到当前角色，例如“马平（追回陈木匠...）”不能判成
    “马平=木匠”，“陈渊（...比士兵好用...）”也不能判成“陈渊=士兵”。
    """
    first = _IDENTITY_NOTE_SPLIT_RE.split(note or "", maxsplit=1)[0].strip()
    if not first or len(first) > 24 or _IDENTITY_ACTION_PREFIX_RE.match(first):
        return []

    identities: List[str] = []
    for word in _IDENTITY_WORDS:
        start = 0
        while True:
            idx = first.find(word, start)
            if idx < 0:
                break
            suffix = first[idx + len(word):]
            if not any(suffix.startswith(item) for item in _IDENTITY_CONTEXT_SUFFIX):
                identities.append(_canon_identity(word))
                break
            start = idx + len(word)
    return sorted(set(identities))


def audit_identity(chapters: List[dict]) -> List[Finding]:
    """O4：找出同名角色被赋予互斥身份（重名冲突 / 人设漂移）。

    仅信任 characters 字段的括号注释（如"张铁柱（退休老刑警）"）作为权威身份源，
    不扫描 key_points 自由文本——后者在多角色同场时会因邻近污染产生大量误报。
    """
    name2ids: Dict[str, Dict[str, set]] = {}
    for ch in chapters:
        if not ch:
            continue
        n = ch.get("chapter_number")
        for raw in ch.get("characters", []) or []:
            nm = _normalize_name(raw)
            note = _paren_note(raw)
            if not nm or not note:
                continue
            for identity in _extract_identity_from_note(note):
                name2ids.setdefault(nm, {}).setdefault(identity, set()).add(n)

    findings: List[Finding] = []
    for nm, idmap in sorted(name2ids.items()):
        if len(idmap) >= 2:
            identities = [
                {"identity": ident, "chapters": sorted(chs)}
                for ident, chs in sorted(idmap.items(), key=lambda kv: min(kv[1]))
            ]
            target_chapters = sorted({
                n
                for chs in idmap.values()
                for n in chs
                if isinstance(n, int)
            })
            parts = [
                f"{ident}(第{min(chs)}章)"
                for ident, chs in sorted(idmap.items(), key=lambda kv: min(kv[1]))
            ]
            findings.append(Finding(
                rule_id="O4",
                severity="fatal",
                title="人物身份一致性",
                chapter=target_chapters[0] if target_chapters else None,
                message=(
                    f"角色『{nm}』在不同章节被赋予互斥身份：{'、'.join(parts)}，"
                    f"疑似重名冲突或人设漂移"
                ),
                evidence={
                    "character_name": nm,
                    "conflicting_identities": identities,
                    "target_chapters": target_chapters,
                    "candidate_chapters": target_chapters,
                },
            ))
    return findings


# =====================================================================
# O5 结局回收率
# =====================================================================

def audit_recovery_rate(chapters: List[dict], hang_warn_ratio: float = 0.4) -> List[Finding]:
    """O5：统计全书伏笔埋设/回收比与悬挂率，给出总览。"""
    bury = recover = 0
    for ch in chapters:
        if not ch:
            continue
        for item in ch.get("foreshadowing", []) or []:
            kind, _ = _classify_foreshadow(item)
            if kind == "bury":
                bury += 1
            elif kind == "recover":
                recover += 1
    n_hang = len(audit_foreshadowing(chapters))
    ratio = (n_hang / bury) if bury else 0.0
    severity = "warning" if ratio >= hang_warn_ratio else "info"
    return [Finding(
        rule_id="O5",
        severity=severity,
        title="结局回收率",
        chapter=None,
        message=(
            f"全书伏笔埋设 {bury} 条 / 回收 {recover} 条；"
            f"疑似悬挂 {n_hang} 条（悬挂率 {ratio:.0%}）"
        ),
    )]


# =====================================================================
# LLM 语义复核层（需传入有 .generate(prompt) 方法的模型）
# =====================================================================

AUDIT_LLM_GENERATE_KWARGS = {"temperature": 0}
AUDIT_LLM_PROMPT_MAX_CHARS = 60000
AUDIT_LLM_MAX_CANDIDATES = 32
AUDIT_LLM_CANDIDATE_CONTEXT_LIMIT = 1000

def _extract_json(text: str):
    """从 LLM 输出中提取首个 JSON 对象，容忍 markdown 围栏与前后缀文字。"""
    if not text:
        return None
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    s, e = cleaned.find("{"), cleaned.rfind("}")
    if s < 0 or e <= s:
        return None
    try:
        return _json.loads(cleaned[s:e + 1])
    except Exception:
        return None


def _candidate_completions(task_kw: set, chapters: List[dict],
                           task_chapter: int, threshold: int = 1):
    """宽松召回候选闭环章，含可能误配项，交由 LLM 裁决。"""
    cands = []
    for ch in chapters:
        if not ch:
            continue
        n = ch.get("chapter_number")
        if n is None or n < task_chapter:
            continue
        text = _chapter_fulltext(ch)
        if _TASK_DONE_RE.search(text) and len(task_kw & _hanzi_bigrams(text)) >= threshold:
            cands.append((n, _relevant_context(text, task_kw)))
    return cands


def _limit_candidate_completions(
    candidates,
    task_kw: set,
    max_candidates: int = AUDIT_LLM_MAX_CANDIDATES,
    context_limit: int = AUDIT_LLM_CANDIDATE_CONTEXT_LIMIT,
):
    """限制发给 LLM 的候选闭环上下文，避免单个任务 prompt 爆长。"""
    if len(candidates) <= max_candidates:
        return [(n, text[:context_limit]) for n, text in candidates]

    earliest = candidates[:4]
    scored = []
    for index, (chapter, text) in enumerate(candidates):
        overlap = len(task_kw & _hanzi_bigrams(text))
        done_signal = 1 if _TASK_DONE_RE.search(text) else 0
        distance = max(0, int(chapter or 0))
        scored.append((overlap, done_signal, -distance, -index, chapter, text))

    top = [
        (chapter, text)
        for _overlap, _done, _distance, _index, chapter, text
        in sorted(scored, reverse=True)[:max_candidates]
    ]

    selected = {}
    for chapter, text in earliest + top:
        selected.setdefault(chapter, text)
        if len(selected) >= max_candidates:
            break

    return [
        (chapter, selected[chapter][:context_limit])
        for chapter in sorted(selected)
    ]


def _build_closure_prompt(
    task_chapter: int,
    task_desc: str,
    publish_context: str,
    candidates,
    omitted_count: int = 0,
) -> str:
    blocks = "\n\n".join(
        f"[第{n}章候选闭环片段]\n{text}" for n, text in candidates
    ) or "（全书后续无任何疑似'任务完成'片段）"
    if omitted_count > 0:
        blocks += f"\n\n（另有 {omitted_count} 个低相关候选片段已省略，避免提示词过长。）"
    return f"""你在审核一部长篇小说大纲的"任务闭环"。

[待审任务] 第{task_chapter}章发布：{task_desc}

[发布章相关上下文]
{publish_context}

[后续疑似"任务完成/回收/收口"的片段]
{blocks}

判断：上述任务是否真的被完成/办结？
关键：
1. 要区分"完成的是同类但不同对象的任务"——若任务针对甲角色，而完成的只是乙角色的同类事件，则此任务【未闭环】。
2. "正式办结 / 顺利完成 / 平静顺利 / 初步解决 / 关键修复 / 回收第N章任务"都可以作为闭环证据，但只在对象与目标一致时成立。

只输出 JSON（不要多余文字）：{{"closed": true 或 false, "reason": "简短理由"}}"""


def llm_review_task_closure(chapters: List[dict], model,
                            candidate_threshold: int = 1) -> List[Finding]:
    """用 LLM 对系统任务闭环做语义裁决，补足算法因母题复用/顺带提及导致的假闭环漏报。

    model: 任意具备 generate(prompt, **kwargs) -> str 的对象（项目内 BaseModel 子类，测试可传 mock）。
    """
    return llm_review_task_closure_with_stats(
        chapters, model, candidate_threshold
    ).findings


def _empty_llm_stats() -> Dict[str, int]:
    """统一 LLM 复核统计字段，报告中即使为 0 也显式展示。"""
    return {
        "published_tasks": 0,
        "skipped_tasks": 0,
        "llm_reviewed_tasks": 0,
        "llm_calls": 0,
        "llm_findings": 0,
        "llm_fatal_findings": 0,
        "llm_warning_findings": 0,
        "llm_call_failures": 0,
        "llm_parse_failures": 0,
        "closed_tasks": 0,
        "open_tasks": 0,
        "uncertain_tasks": 0,
        "candidate_completion_chapters": 0,
        "candidate_completion_chapters_sent": 0,
        "candidate_completion_chapters_omitted": 0,
        "llm_prompt_over_budget": 0,
        "llm_prompt_max_chars": 0,
    }


def llm_review_task_closure_with_stats(
    chapters: List[dict],
    model,
    candidate_threshold: int = 1,
) -> LLMReviewResult:
    """用 LLM 复核任务闭环，并返回可审计的运行统计。"""
    published = []
    for ch in chapters:
        if not ch:
            continue
        n = ch.get("chapter_number")
        text = _chapter_fulltext(ch)
        for desc in _extract_published_tasks_from_text(text):
            published.append((n, desc, _hanzi_bigrams(desc), _relevant_context(text, _hanzi_bigrams(desc))))

    findings: List[Finding] = []
    stats = _empty_llm_stats()
    stats["published_tasks"] = len(published)
    superseded_task_keys = set()
    for n, desc, kw, publish_context in published:
        if not kw:
            stats["skipped_tasks"] += 1
            continue
        cands = _candidate_completions(kw, chapters, n, candidate_threshold)
        limited_cands = _limit_candidate_completions(cands, kw)
        omitted_count = max(0, len(cands) - len(limited_cands))
        stats["candidate_completion_chapters"] += len(cands)
        stats["candidate_completion_chapters_sent"] += len(limited_cands)
        stats["candidate_completion_chapters_omitted"] += omitted_count
        prompt = _build_closure_prompt(n, desc, publish_context, limited_cands, omitted_count)
        stats["llm_prompt_max_chars"] = max(stats["llm_prompt_max_chars"], len(prompt))
        if len(prompt) > AUDIT_LLM_PROMPT_MAX_CHARS:
            stats["llm_prompt_over_budget"] += 1
            limited_cands = _limit_candidate_completions(
                limited_cands,
                kw,
                max_candidates=12,
                context_limit=500,
            )
            omitted_count = max(0, len(cands) - len(limited_cands))
            prompt = _build_closure_prompt(n, desc, publish_context[:1200], limited_cands, omitted_count)
            stats["llm_prompt_max_chars"] = max(stats["llm_prompt_max_chars"], len(prompt))
        if len(prompt) > AUDIT_LLM_PROMPT_MAX_CHARS:
            limited_cands = [
                (cn, text[:400])
                for cn, text in limited_cands[:8]
            ]
            omitted_count = max(0, len(cands) - len(limited_cands))
            prompt = _build_closure_prompt(
                n,
                desc[:1200],
                publish_context[:800],
                limited_cands,
                omitted_count,
            )
            stats["llm_prompt_max_chars"] = max(stats["llm_prompt_max_chars"], len(prompt))
        stats["llm_reviewed_tasks"] += 1
        stats["llm_calls"] += 1
        candidate_chapters = [cn for cn, _ in cands]
        key = _task_key(n, desc)
        try:
            raw = model.generate(prompt, **AUDIT_LLM_GENERATE_KWARGS)
        except Exception as e:
            stats["llm_call_failures"] += 1
            findings.append(Finding(
                "O3-LLM", "warning", "任务闭环(LLM复核)", n,
                f"第{n}章任务 LLM 复核调用失败，需人工确认：{desc[:40]}（{e}）",
                evidence={
                    "task_description": desc,
                    "task_key": key[1],
                    "candidate_chapters": candidate_chapters,
                    "error": str(e),
                },
            ))
            continue
        verdict = _extract_json(raw)
        if verdict is None:
            stats["llm_parse_failures"] += 1
            stats["uncertain_tasks"] += 1
            findings.append(Finding(
                "O3-LLM", "warning", "任务闭环(LLM复核)", n,
                f"第{n}章任务 LLM 返回无法解析，需人工确认：{desc[:40]}",
                evidence={
                    "task_description": desc,
                    "task_key": key[1],
                    "candidate_chapters": candidate_chapters,
                    "raw_response": str(raw)[:500],
                },
            ))
            continue
        closed = verdict.get("closed")
        if closed is False:
            superseded_task_keys.add(key)
            stats["open_tasks"] += 1
            findings.append(Finding(
                "O3-LLM", "fatal", "任务闭环(LLM复核)", n,
                f"第{n}章发布的任务经 LLM 判定未闭环：{desc[:40]}"
                f"｜理由：{str(verdict.get('reason', ''))[:60]}",
                evidence={
                    "task_description": desc,
                    "task_key": key[1],
                    "candidate_chapters": candidate_chapters,
                    "llm_closed": False,
                    "llm_reason": str(verdict.get("reason", "")),
                },
            ))
        elif closed is not True:
            stats["uncertain_tasks"] += 1
            findings.append(Finding(
                "O3-LLM", "warning", "任务闭环(LLM复核)", n,
                f"第{n}章任务 LLM 未给明确闭环判定，需人工确认：{desc[:40]}",
                evidence={
                    "task_description": desc,
                    "task_key": key[1],
                    "candidate_chapters": candidate_chapters,
                    "llm_closed": closed,
                    "llm_reason": str(verdict.get("reason", "")),
                },
            ))
        else:
            superseded_task_keys.add(key)
            stats["closed_tasks"] += 1

    stats["llm_findings"] = len(findings)
    stats["llm_fatal_findings"] = len([f for f in findings if f.severity == "fatal"])
    stats["llm_warning_findings"] = len([f for f in findings if f.severity == "warning"])
    return LLMReviewResult(
        findings=findings,
        stats=stats,
        superseded_task_keys=superseded_task_keys,
    )


def _finding_task_key(finding: Finding) -> Optional[tuple]:
    """从 O3/O3-LLM finding 中恢复任务键，用于合并算法与 LLM 结论。"""
    if finding.rule_id not in ("O3", "O3-LLM") or finding.chapter is None:
        return None
    evidence = finding.evidence or {}
    desc = evidence.get("task_description")
    if desc:
        return _task_key(finding.chapter, str(desc))
    task_key = evidence.get("task_key")
    if task_key:
        return finding.chapter, str(task_key)
    return None


def merge_llm_task_review_findings(
    findings: List[Finding],
    llm_result: LLMReviewResult,
) -> List[Finding]:
    """合并算法审计与 LLM 复核结果，避免同一任务 O3/O3-LLM 重复计数。"""
    superseded = set(llm_result.superseded_task_keys or set())
    if not superseded:
        for finding in llm_result.findings:
            if finding.rule_id == "O3-LLM" and finding.severity == "fatal":
                key = _finding_task_key(finding)
                if key:
                    superseded.add(key)

    merged = [
        finding
        for finding in findings
        if not (finding.rule_id == "O3" and _finding_task_key(finding) in superseded)
    ]
    merged.extend(llm_result.findings)
    return merged


# =====================================================================
# 聚合
# =====================================================================

_ALL_RULES = [
    ("O1", audit_foreshadowing),
    ("O2", audit_entities),
    ("O3", audit_task_closure),
    ("O4", audit_identity),
    ("O5", audit_recovery_rate),
]


def run_audit(chapters: List[dict]) -> List[Finding]:
    """跑全部算法规则（O1-O5），返回汇总的 Finding 列表。"""
    findings: List[Finding] = []
    for _rid, fn in _ALL_RULES:
        findings.extend(fn(chapters))
    return findings
