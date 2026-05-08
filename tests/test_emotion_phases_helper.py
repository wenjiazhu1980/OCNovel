# -*- coding: utf-8 -*-
"""[P1 前置] EMOTION_PHASES 模块级常量与辅助函数测试

把 prompts.py 中原 ``_PHASES`` 局部变量提升为模块级 ``EMOTION_PHASES``，
并提供两个辅助函数:
- get_emotion_phase_for_arc_position(arc_pct)  按卷内进度
- get_emotion_phase_for_chapter(chapter_num, chapters_per_arc)  按章节号

本测试覆盖:
1. 常量结构合法性（threshold 升序、最后一项=1.0、6 个阶段）
2. arc_pct 边界（0/0.5/1.0/越界）
3. 按章节号查找（含 chapters_per_arc=0 的语义保护）
4. 与 prompts.py 中实际渲染的 prompt 行为一致
"""

import pytest
from src.generators.prompts import (
    EMOTION_PHASES,
    EmotionPhase,
    get_emotion_phase_for_arc_position,
    get_emotion_phase_for_chapter,
    get_outline_prompt,
)


class TestEmotionPhasesConstant:
    """EMOTION_PHASES 数据完整性"""

    def test_six_phases_defined(self):
        """雪花写作法螺旋上升模型固定 6 阶段"""
        assert len(EMOTION_PHASES) == 6

    def test_threshold_ascending(self):
        """threshold 必须严格升序（get_emotion_phase_for_arc_position 依赖此假设）"""
        thresholds = [p.threshold for p in EMOTION_PHASES]
        assert thresholds == sorted(thresholds)
        # 不允许重复阈值（否则会落入二义性区间）
        assert len(set(thresholds)) == len(thresholds)

    def test_last_threshold_is_one(self):
        """最后一个阈值必须 == 1.0，保证任何 arc_pct ∈ (0,1] 必有命中"""
        assert EMOTION_PHASES[-1].threshold == 1.0

    def test_phase_names_unique(self):
        """6 个阶段名互异，便于在 outline.json 中辨识"""
        names = [p.name for p in EMOTION_PHASES]
        assert len(set(names)) == 6
        assert set(names) == {"成长", "挫折", "绝境", "爆发", "跌落", "新局"}

    def test_phase_fields_non_empty(self):
        """每个阶段的描述/读者情绪/叙事指导/禁忌都不能为空（prompt 渲染依赖）"""
        for p in EMOTION_PHASES:
            assert p.name and p.desc and p.reader_emotion and p.narrative_guide and p.taboo, (
                f"阶段 {p} 存在空字段"
            )

    def test_namedtuple_immutable(self):
        """NamedTuple 应当不可变，避免运行时被误改"""
        p = EMOTION_PHASES[0]
        with pytest.raises(AttributeError):
            p.name = "tampered"  # type: ignore[misc]


class TestArcPositionLookup:
    """get_emotion_phase_for_arc_position 边界与连续性"""

    @pytest.mark.parametrize("pct,expected_name", [
        (0.001, "成长"),
        (0.10, "成长"),
        (0.23, "成长"),       # 上界归本阶段
        (0.231, "挫折"),
        (0.40, "挫折"),
        (0.41, "绝境"),
        (0.55, "绝境"),
        (0.56, "爆发"),
        (0.72, "爆发"),
        (0.73, "跌落"),
        (0.93, "跌落"),
        (0.94, "新局"),
        (1.00, "新局"),
    ])
    def test_phase_boundaries(self, pct, expected_name):
        """阶段边界点归属符合 ≤ 比较语义"""
        assert get_emotion_phase_for_arc_position(pct).name == expected_name

    def test_zero_returns_first_phase(self):
        """arc_pct == 0 视为卷首，归入第一个阶段"""
        assert get_emotion_phase_for_arc_position(0.0).name == "成长"

    def test_negative_clamped_to_first(self):
        """负数夹逼到第一个阶段（防御异常输入）"""
        assert get_emotion_phase_for_arc_position(-0.5).name == "成长"

    def test_above_one_clamped_to_last(self):
        """>1 夹逼到最后阶段（防御异常输入）"""
        assert get_emotion_phase_for_arc_position(1.5).name == "新局"
        assert get_emotion_phase_for_arc_position(99.0).name == "新局"

    def test_returns_namedtuple_instance(self):
        """返回的对象应是 EmotionPhase 实例（保证字段访问可用）"""
        p = get_emotion_phase_for_arc_position(0.5)
        assert isinstance(p, EmotionPhase)
        assert hasattr(p, "name") and hasattr(p, "taboo")


class TestChapterLookup:
    """get_emotion_phase_for_chapter 章节号 → 阶段映射"""

    def test_chapter_one_in_growth(self):
        """卷首第一章应在成长期"""
        # 第 1 章: arc_pos=1, arc_pct=1/40=0.025 → 成长
        assert get_emotion_phase_for_chapter(1, 40).name == "成长"

    def test_chapter_at_arc_end_in_new_world(self):
        """卷末（arc_pos == chapters_per_arc）应在新局"""
        # 第 40 章: arc_pos=40, arc_pct=1.0 → 新局
        assert get_emotion_phase_for_chapter(40, 40).name == "新局"

    def test_arc_boundary_resets(self):
        """跨卷时 arc_pos 重置（第 41 章应回到成长期）"""
        assert get_emotion_phase_for_chapter(41, 40).name == "成长"
        # 第 80 章 = 第二卷的最后一章 → 新局
        assert get_emotion_phase_for_chapter(80, 40).name == "新局"

    def test_invalid_chapters_per_arc_returns_none(self):
        """chapters_per_arc <= 0 时返回 None（语义：未配置卷长）"""
        assert get_emotion_phase_for_chapter(1, 0) is None
        assert get_emotion_phase_for_chapter(1, -1) is None

    def test_invalid_chapter_number_returns_none(self):
        """章节号 < 1 返回 None"""
        assert get_emotion_phase_for_chapter(0, 40) is None
        assert get_emotion_phase_for_chapter(-5, 40) is None

    @pytest.mark.parametrize("chapter,expected", [
        (1, "成长"),     # arc_pct=0.025
        (9, "成长"),     # arc_pct=0.225
        (10, "挫折"),    # arc_pct=0.25 > 0.23
        (16, "挫折"),    # arc_pct=0.40
        (17, "绝境"),    # arc_pct=0.425
        (22, "绝境"),    # arc_pct=0.55
        (23, "爆发"),    # arc_pct=0.575
        (28, "爆发"),    # arc_pct=0.70 (≤0.72)
        (29, "跌落"),    # arc_pct=0.725 > 0.72 → 进入跌落
        (37, "跌落"),    # arc_pct=0.925
        (38, "新局"),    # arc_pct=0.95
    ])
    def test_full_arc_progression_40_chapters(self, chapter, expected):
        """40 章一卷的逐阶段推进（与目标项目 chapters_per_arc=40 一致）"""
        result = get_emotion_phase_for_chapter(chapter, 40)
        assert result is not None
        assert result.name == expected, f"ch{chapter} expected {expected} got {result.name}"


class TestPromptIntegration:
    """常量被 get_outline_prompt 实际复用（回归保护）"""

    def test_growth_phase_appears_in_prompt(self):
        """卷首（成长期）的章节，prompt 应包含「成长」阶段标识"""
        prompt = get_outline_prompt(
            novel_type="末世",
            theme="生存",
            style="冷峻",
            current_start_chapter_num=1,
            current_batch_size=3,
            total_chapters=400,
            current_end_chapter_num=3,
            arc_config={"chapters_per_arc": 40},
        )
        # 第 1-3 章在第 1 卷成长期
        assert "🎭 成长" in prompt
        assert "享受红利" in prompt

    def test_collapse_phase_appears_for_late_arc_chapter(self):
        """卷末跌落期章节，prompt 应包含「跌落」阶段标识与禁忌"""
        # 第 37 章 = 卷 1 第 37 章, arc_pct=37/40=0.925 → 跌落
        prompt = get_outline_prompt(
            novel_type="末世",
            theme="生存",
            style="冷峻",
            current_start_chapter_num=37,
            current_batch_size=1,
            total_chapters=400,
            current_end_chapter_num=37,
            arc_config={"chapters_per_arc": 40},
        )
        assert "🎭 跌落" in prompt
        # 跌落阶段的核心禁忌：不能没收金手指
        assert "没收金手指" in prompt or "环境升维" in prompt

    def test_no_emotion_section_when_no_arc_config(self):
        """未配置 chapters_per_arc 时，prompt 不应出现卷内情绪节奏段落"""
        prompt = get_outline_prompt(
            novel_type="都市",
            theme="奇幻",
            style="轻松",
            current_start_chapter_num=1,
            current_batch_size=3,
            total_chapters=20,
            current_end_chapter_num=3,
            arc_config=None,  # 关键：不传
        )
        assert "卷内情绪节奏" not in prompt
