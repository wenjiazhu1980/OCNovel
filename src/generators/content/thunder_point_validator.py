"""
雷点验证器（Thunder-Point Validator）

将《宁河图创作思路》文档第 567-1515 行的 18 类"雷点"清单，
转化为可执行的章节自检规则。

设计原则：
    - 启发式优先：能用正则/统计搞定的，绝不动用 LLM（节省 token）。
    - LLM 只做"语义级"判断（人设矛盾、主线偏离、情感生硬等）。
    - 输出结构化 JSON，便于 ContentGenerator 决定是否触发重写。
    - 每条规则可独立开关，避免一次全检拖慢生成流水线。

使用方式：
    validator = ThunderPointValidator(content_model)
    report, needs_revision = validator.check(
        chapter_content=...,
        chapter_outline=...,
        novel_config=...,
        prev_chapter_summary=...,
        rules=("R1", "R3", "R5", "R11"),  # 可选，默认全检
    )
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Callable, Set


# =====================================================================
# 规则元数据
# =====================================================================

@dataclass
class RuleResult:
    """单条规则的检查结果"""
    rule_id: str
    rule_name: str
    passed: bool
    severity: str          # "fatal" | "warning" | "info"
    score: int             # 0-100，仅供参考
    findings: List[str] = field(default_factory=list)
    suggestion: str = ""

    def format(self) -> str:
        status = "✓" if self.passed else "✗"
        lines = [f"[{status}] {self.rule_id} {self.rule_name}（{self.severity}, {self.score}/100）"]
        for f in self.findings:
            lines.append(f"   - {f}")
        if self.suggestion and not self.passed:
            lines.append(f"   建议：{self.suggestion}")
        return "\n".join(lines)


# =====================================================================
# 雷点验证器主类
# =====================================================================

class ThunderPointValidator:
    """18 雷点验证器"""

    # 规则注册表：rule_id → (rule_name, severity, default_enabled)
    RULES = {
        "R1":  ("开篇拖沓/平淡/信息轰炸",        "warning",  True),
        "R2":  ("世界观模糊或强行灌输",          "warning",  True),
        "R3":  ("人设矛盾/节奏混乱/配角工具人",   "fatal",    True),
        "R4":  ("视角杂乱或叙事方式不当",        "warning",  True),
        "R5":  ("剧情主线不明/平淡/混乱",        "fatal",    True),
        "R6":  ("描写无效/排版不规范/文笔失衡",   "warning",  True),
        "R7":  ("主线偏离/情节停滞",            "fatal",    True),
        "R8":  ("冲突乏力/爽点缺失",            "warning",  True),
        "R9":  ("节奏失控/过渡生硬",            "warning",  True),
        "R10": ("人设前后矛盾/目标频繁更换",     "fatal",    True),
        "R11": ("人物形象单薄/扁平化",           "warning",  True),
        "R12": ("情感表达生硬/AI 味",           "warning",  True),
        "R13": ("世界观脱离现实/设定吃书",       "fatal",    True),
        "R14": ("金手指失衡（过强/过弱/闲置）",   "warning",  True),
        "R15": ("爽点不足/冲突乏力（疲劳）",     "info",     False),  # 与 R8 重叠，默认关闭
        "R16": ("开篇问题（与 R1 重复）",        "info",     False),  # 与 R1 重复，默认关闭
        "R17": ("作品包装缺乏吸引力",            "info",     False),  # 仅书名/简介阶段，不作用于章节
        "R18": ("文笔不佳/排版不规范",           "warning",  True),
    }

    def __init__(self, content_model):
        self.content_model = content_model
        # 启发式规则映射
        self._heuristic_handlers: Dict[str, Callable] = {
            "R1":  self._check_opening,
            "R4":  self._check_pov,
            "R6":  self._check_paragraph_format,
            "R12": self._check_ai_flavor,
            "R18": self._check_writing_quality,
        }
        # LLM 规则映射（语义级判断）
        self._llm_rules: Set[str] = {"R2", "R3", "R5", "R7", "R8", "R9", "R10", "R11", "R13", "R14"}

    # -----------------------------------------------------------------
    # 入口
    # -----------------------------------------------------------------
    def check(
        self,
        chapter_content: str,
        chapter_outline: Dict,
        novel_config: Optional[Dict] = None,
        prev_chapter_summary: str = "",
        is_opening_chapter: bool = False,
        rules: Optional[Tuple[str, ...]] = None,
    ) -> Tuple[str, bool]:
        """
        执行雷点检查。

        Args:
            chapter_content: 当前章节正文
            chapter_outline: 当前章节大纲
            novel_config: 小说全局配置（含人设、世界观）
            prev_chapter_summary: 上一章节摘要（用于一致性判断）
            is_opening_chapter: 是否为开篇前 3 章（控制 R1 是否启用）
            rules: 指定要执行的规则 id；None 表示按 default_enabled 执行

        Returns:
            (report_str, needs_revision)
        """
        active_rules = self._select_rules(rules, is_opening_chapter)
        results: List[RuleResult] = []

        for rule_id in active_rules:
            try:
                if rule_id in self._heuristic_handlers:
                    res = self._heuristic_handlers[rule_id](
                        chapter_content, chapter_outline, novel_config
                    )
                elif rule_id in self._llm_rules:
                    res = self._llm_check(
                        rule_id, chapter_content, chapter_outline,
                        novel_config, prev_chapter_summary
                    )
                else:
                    continue
                results.append(res)
            except Exception as e:
                logging.error(f"雷点 {rule_id} 检查失败: {e}")
                results.append(RuleResult(
                    rule_id=rule_id,
                    rule_name=self.RULES[rule_id][0],
                    passed=False,
                    severity="warning",
                    score=0,
                    findings=[f"检查器异常：{e}"],
                ))

        # 汇总：任何 fatal 不通过 → 需要修改；warning 累计 ≥3 也触发
        fatal_failures = [r for r in results if not r.passed and r.severity == "fatal"]
        warning_failures = [r for r in results if not r.passed and r.severity == "warning"]
        needs_revision = bool(fatal_failures) or len(warning_failures) >= 3

        report = self._format_report(results, needs_revision)
        return report, needs_revision

    # -----------------------------------------------------------------
    # 规则选择
    # -----------------------------------------------------------------
    def _select_rules(
        self,
        rules: Optional[Tuple[str, ...]],
        is_opening_chapter: bool,
    ) -> List[str]:
        if rules is not None:
            return [r for r in rules if r in self.RULES]
        # 默认按 default_enabled 选择
        active = [rid for rid, (_, _, enabled) in self.RULES.items() if enabled]
        # 非开篇章节关闭 R1
        if not is_opening_chapter:
            active = [r for r in active if r != "R1"]
        return active

    # =================================================================
    # 启发式检查器（不调用 LLM）
    # =================================================================

    def _check_opening(self, content: str, outline: Dict, config: Optional[Dict]) -> RuleResult:
        """R1 开篇：前 500 字必须出现冲突/动作动词，且段落不超长。"""
        findings = []
        head = content[:600]
        # 信号词：冲突/动作
        action_signals = re.findall(
            r"(突然|猛地|砰|撞|抽出|举起|怒|杀|逃|追|喊|骂|血|刀|枪|拳|踹|扑)",
            head
        )
        if len(action_signals) < 2:
            findings.append("前 600 字内动作/冲突信号词 < 2 个，开篇可能过于平淡")

        # 段落长度
        paragraphs = [p for p in head.split("\n") if p.strip()]
        if paragraphs and any(len(p) > 250 for p in paragraphs[:3]):
            findings.append("开篇前 3 段中存在 > 250 字的长段，疑似信息轰炸")

        # 信息密度：前 200 字未出现人物代词或姓名
        if not re.search(r"(他|她|我|你|主角|[A-Z][a-z]+|[一-龥]{2,3}(?:道|说|笑|看))", head[:200]):
            findings.append("前 200 字未锁定主角，读者无法快速代入")

        passed = len(findings) == 0
        return RuleResult(
            rule_id="R1",
            rule_name=self.RULES["R1"][0],
            passed=passed,
            severity="warning",
            score=100 - len(findings) * 25,
            findings=findings,
            suggestion="开篇 1 章用动作或冲突切入；信息分层植入，避免大段背景独白",
        )

    def _check_pov(self, content: str, outline: Dict, config: Optional[Dict]) -> RuleResult:
        """R4 视角杂乱：第一/第三人称是否混用，单章视角切换次数。"""
        findings = []
        # 第一人称信号
        first_person = len(re.findall(r"(?<![一-龥])我(?![们的国家])", content))
        # 第三人称信号
        third_person = len(re.findall(r"(?:他|她)(?:[说想看走道笑])", content))

        if first_person > 5 and third_person > 5:
            findings.append(f"第一人称({first_person})与第三人称({third_person})疑似混用")

        # 段间视角硬切：段落开头突然出现新角色名占比
        paragraphs = [p.strip() for p in content.split("\n") if p.strip()]
        if len(paragraphs) >= 10:
            switches = sum(
                1 for i in range(1, len(paragraphs))
                if re.match(r"^[一-龥]{2,4}[说道想看]", paragraphs[i])
                and not re.match(r"^[一-龥]{2,4}[说道想看]", paragraphs[i-1])
            )
            if switches > len(paragraphs) // 3:
                findings.append(f"段间视角切换次数过多（{switches} 次 / {len(paragraphs)} 段）")

        passed = len(findings) == 0
        return RuleResult(
            rule_id="R4",
            rule_name=self.RULES["R4"][0],
            passed=passed,
            severity="warning",
            score=100 - len(findings) * 30,
            findings=findings,
            suggestion="确定单一主视角，配角视角集中处理或用上帝视角统一切换",
        )

    def _check_paragraph_format(self, content: str, outline: Dict, config: Optional[Dict]) -> RuleResult:
        """R6 排版：段落长度 + 标点频率。"""
        findings = []
        paragraphs = [p for p in content.split("\n") if p.strip()]
        if not paragraphs:
            return RuleResult("R6", self.RULES["R6"][0], False, "warning", 0,
                              ["章节为空"], "重新生成章节内容")

        long_paragraphs = [p for p in paragraphs if len(p) > 200]
        long_ratio = len(long_paragraphs) / len(paragraphs)
        if long_ratio > 0.3:
            findings.append(f"超长段落（>200 字）占比 {long_ratio:.0%}，移动端阅读疲劳")

        # 标点频率：每段平均句号 < 2 → 段落过于"绵长"
        avg_periods = sum(p.count("。") + p.count("！") + p.count("？") for p in paragraphs) / len(paragraphs)
        if avg_periods < 1.5:
            findings.append(f"平均每段句末标点 {avg_periods:.1f} 个，段落过于绵长")

        # 形容词堆砌检测（连续 3 个以上"的"字）
        stacked_de = re.findall(r"(?:[一-龥]{2,4}的){3,}", content)
        if len(stacked_de) > 3:
            findings.append(f"发现 {len(stacked_de)} 处形容词堆砌（连续 3+ 个'的'结构）")

        passed = len(findings) == 0
        return RuleResult(
            rule_id="R6",
            rule_name=self.RULES["R6"][0],
            passed=passed,
            severity="warning",
            score=max(0, 100 - len(findings) * 25),
            findings=findings,
            suggestion="段落控制在 3-5 行（60-150 字），减少形容词堆砌，多用动词",
        )

    def _check_ai_flavor(self, content: str, outline: Dict, config: Optional[Dict]) -> RuleResult:
        """R12 AI 味：高频 AI 词汇 + 转折词密度。"""
        findings = []

        # AI 高频陈词
        ai_phrases = [
            "璀璨夺目", "熠熠生辉", "不禁颤抖", "心中暗道", "心中一凛",
            "深以为然", "颇为", "不由得", "暗自", "微微一笑",
            "若有所思", "意味深长", "不动声色", "一时间",
        ]
        hits = [(p, content.count(p)) for p in ai_phrases if content.count(p) > 0]
        ai_total = sum(c for _, c in hits)
        if ai_total >= 5:
            findings.append(f"AI 高频陈词出现 {ai_total} 次：{hits[:5]}")

        # 转折词密度
        transitions = sum(content.count(w) for w in ["虽然", "但是", "然而", "却", "尽管"])
        word_count = len(content)
        if word_count > 0 and transitions / (word_count / 1000) > 8:
            findings.append(f"转折词密度过高（每 1000 字 {transitions / (word_count / 1000):.1f} 个）")

        # 直白抒情：直接陈述情绪
        direct_emotion = len(re.findall(r"(?:他|她|我)(?:感到|觉得|心想)(?:非常|十分|极其)", content))
        if direct_emotion > 3:
            findings.append(f"直白抒情 {direct_emotion} 处，违反 Show don't tell")

        passed = len(findings) == 0
        return RuleResult(
            rule_id="R12",
            rule_name=self.RULES["R12"][0],
            passed=passed,
            severity="warning",
            score=max(0, 100 - len(findings) * 30),
            findings=findings,
            suggestion="替换 AI 陈词为具体动作；用细节展示情绪，禁止直接陈述'感到/觉得'",
        )

    def _check_writing_quality(self, content: str, outline: Dict, config: Optional[Dict]) -> RuleResult:
        """R18 文笔与排版综合（与 R6/R12 互补）。"""
        findings = []

        # 句子长度方差：太均匀 → 机械感
        sentences = re.split(r"[。！？]", content)
        sentences = [s for s in sentences if s.strip()]
        if len(sentences) >= 20:
            lengths = [len(s) for s in sentences]
            avg = sum(lengths) / len(lengths)
            variance = sum((l - avg) ** 2 for l in lengths) / len(lengths)
            std = variance ** 0.5
            if std < 8:
                findings.append(f"句长标准差 {std:.1f}（< 8），节奏机械，缺乏长短句变化")

        # "了"字泛滥检测
        liao_count = content.count("了")
        if word_count_safe(content) > 0:
            liao_density = liao_count / (len(content) / 100)
            if liao_density > 5:
                findings.append(f"'了'字密度 {liao_density:.1f}/100 字，过高")

        passed = len(findings) == 0
        return RuleResult(
            rule_id="R18",
            rule_name=self.RULES["R18"][0],
            passed=passed,
            severity="warning",
            score=max(0, 100 - len(findings) * 30),
            findings=findings,
            suggestion="加入短句（5 字以内）打破节奏；减少'了'字，多用'过/着'或省略",
        )

    # =================================================================
    # LLM 检查器（语义级）
    # =================================================================

    def _llm_check(
        self,
        rule_id: str,
        content: str,
        outline: Dict,
        config: Optional[Dict],
        prev_summary: str,
    ) -> RuleResult:
        """统一的 LLM 检查入口，根据 rule_id 选择子 prompt。"""
        prompt = self._build_llm_prompt(rule_id, content, outline, config, prev_summary)
        try:
            raw = self.content_model.generate(prompt)
        except Exception as e:
            return RuleResult(
                rule_id=rule_id,
                rule_name=self.RULES[rule_id][0],
                passed=False,
                severity=self.RULES[rule_id][1],
                score=0,
                findings=[f"LLM 调用失败：{e}"],
            )
        return self._parse_llm_response(rule_id, raw)

    def _build_llm_prompt(
        self,
        rule_id: str,
        content: str,
        outline: Dict,
        config: Optional[Dict],
        prev_summary: str,
    ) -> str:
        """根据 rule_id 拼装专项检查 prompt。"""
        # 抽取章节大纲关键信息
        ch_no = outline.get("chapter_number", "?")
        ch_title = outline.get("title", "?")
        key_points = ", ".join(outline.get("key_points", []))
        characters = ", ".join(outline.get("characters", []))
        conflicts = ", ".join(outline.get("conflicts", []))

        # 抽取人设档案（可选）
        protagonist = ""
        if config:
            character_guide = config.get("writing_guide", {}).get("character_guide", {})
            protagonist = character_guide.get("protagonist", {}).get("background", "")

        # 规则专项指令
        rule_specific = {
            "R2":  "判断本章世界观/设定是否清晰：是否存在'强行灌输'式背景独白？关键设定是否在剧情中自然带出？",
            "R3":  "判断人物行为是否符合既定人设；配角是否有独立动机，还是只为推剧情存在？",
            "R5":  "判断本章主线是否明确：核心目标是否推进？是否被无关支线掩盖？是否流水账？",
            "R7":  "判断主线推进有效性：本章是否相比上一章在主线目标上有可观察的进展？还是停滞或偏离？",
            "R8":  "判断冲突强度与爽点：本章有冲突吗？冲突双方实力是否合理？是否存在突兀爽点（无铺垫直接打脸）？",
            "R9":  "判断节奏与过渡：场景切换是否自然？是否存在突兀跳跃（如丛林→都市无过渡）？",
            "R10": "判断人设前后一致性：本章主角行为是否与既定人设/前一章动机矛盾？是否存在跳跃式能力成长？",
            "R11": "判断人物立体度：主角是否有'核心标签 + 反差细节'？配角是否扁平化、脸谱化？",
            "R13": "判断世界观与现实合理性：是否存在时代错乱（如历史文出现现代物品）？设定是否落地（通过具体行动体现）？",
            "R14": "判断金手指/系统使用：本章是否使用了金手指？使用是否有限制和代价？还是过强或闲置？",
        }.get(rule_id, "对本章进行综合质量判断。")

        prev_block = f"\n[上一章摘要]\n{prev_summary}\n" if prev_summary else ""
        protagonist_block = f"\n[主角设定]\n{protagonist}\n" if protagonist else ""

        return f"""你是港综同人小说责任编辑，正在执行雷点专项检查。

[规则编号] {rule_id}
[规则主题] {self.RULES[rule_id][0]}
[检查指令] {rule_specific}

[章节大纲]
第 {ch_no} 章《{ch_title}》
关键点：{key_points}
角色：{characters}
冲突：{conflicts}
{prev_block}{protagonist_block}
[章节正文]
{content[:4000]}

===== 输出格式（严格遵守）=====
[评分]: <0-100>
[通过]: <"是" 或 "否">
[问题]:
1. <具体问题描述，引用原文片段>
2. ...
[建议]: <一条具体可执行的修改建议>

注意：
- 只判断本规则对应的问题，不评论其他维度。
- 评分 < 60 视为不通过。
- 严禁输出"总体来说很好"这类无效评价。
"""

    def _parse_llm_response(self, rule_id: str, raw: str) -> RuleResult:
        """解析 LLM 输出。"""
        score_m = re.search(r"\[评分\]\s*[：:]\s*(\d+)", raw)
        passed_m = re.search(r"\[通过\]\s*[：:]\s*(.+?)(?:\n|$)", raw)
        findings_block = re.search(r"\[问题\]\s*[：:]?\s*\n(.*?)(?=\[建议\]|\Z)", raw, re.S)
        suggestion_m = re.search(r"\[建议\]\s*[：:]\s*(.+?)(?:\n\n|\Z)", raw, re.S)

        score = int(score_m.group(1)) if score_m else 0
        passed_val = passed_m.group(1).strip() if passed_m else ""
        passed = passed_val.startswith("是") and score >= 60

        findings = []
        if findings_block:
            for line in findings_block.group(1).strip().split("\n"):
                line = line.strip()
                if line and not line.startswith("["):
                    findings.append(re.sub(r"^\d+\.\s*", "", line))

        suggestion = suggestion_m.group(1).strip() if suggestion_m else ""

        return RuleResult(
            rule_id=rule_id,
            rule_name=self.RULES[rule_id][0],
            passed=passed,
            severity=self.RULES[rule_id][1],
            score=score,
            findings=findings,
            suggestion=suggestion,
        )

    # =================================================================
    # 报告格式化
    # =================================================================
    def _format_report(self, results: List[RuleResult], needs_revision: bool) -> str:
        lines = ["===== 雷点检查报告 ====="]
        passed = [r for r in results if r.passed]
        failed = [r for r in results if not r.passed]

        lines.append(f"通过：{len(passed)} / {len(results)}")
        lines.append(f"修改必要性：{'需要修改' if needs_revision else '无需修改'}")
        lines.append("")

        if failed:
            lines.append("--- 未通过项 ---")
            for r in failed:
                lines.append(r.format())
                lines.append("")

        if passed:
            lines.append("--- 通过项 ---")
            for r in passed:
                lines.append(f"[✓] {r.rule_id} {r.rule_name}（{r.score}/100）")

        # 末尾追加"修改必要性"以便上游正则解析（兼容 LogicValidator 的协议）
        lines.append("")
        lines.append(f"[修改必要性]: {'需要修改' if needs_revision else '无需修改'}")
        return "\n".join(lines)


# =====================================================================
# 工具函数
# =====================================================================
def word_count_safe(text: str) -> int:
    """安全字数统计（避免除零）"""
    return len(text) if text else 0
