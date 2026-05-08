# -*- coding: utf-8 -*-
"""[P0] _save_outline 始终持久化扩展字段 + 覆盖率统计

历史问题: outline_generator.py 的 _save_outline 用 `if outline.emotion_tone:`
守护扩展字段写入,导致 LLM 漏输出时静默丢失,事后无法分辨"该章本就无要求"
还是"LLM 没听话",且 400 章实测产物中 0% 字段落地。

修复目标:
1. 扩展字段(emotion_tone / character_goals / scene_sequence / foreshadowing /
   pov_character)始终写入,即便为空亦以默认值('' / {} / [])落盘
2. 保存完成后输出覆盖率统计(INFO);emotion_tone 覆盖率 < 50% 升级为 WARNING
3. 不破坏现有的 chapter_number 去重 / 升序排列 / 重复跳过等不变量
"""

import json
import logging
import os
from unittest.mock import MagicMock

import pytest
from src.generators.common.data_structures import ChapterOutline
from src.generators.outline.outline_generator import OutlineGenerator


@pytest.fixture
def gen_with_outlines(mock_config):
    """构造一个 OutlineGenerator,允许测试动态注入 chapter_outlines"""
    mock_model = MagicMock()
    mock_model.model_name = "mock"
    mock_kb = MagicMock()
    mock_kb.is_built = False

    output_dir = mock_config.output_config["output_dir"]
    os.makedirs(output_dir, exist_ok=True)
    # 写一个空 outline.json,避免 _load_outline 报错
    with open(os.path.join(output_dir, "outline.json"), "w", encoding="utf-8") as f:
        json.dump([], f)

    return OutlineGenerator(mock_config, mock_model, mock_kb)


def _read_saved_outline(output_dir):
    with open(os.path.join(output_dir, "outline.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def _make_chapter(chapter_num, **kwargs):
    """便捷构造工具:其他扩展字段使用 ChapterOutline 默认值"""
    return ChapterOutline(
        chapter_number=chapter_num,
        title=f"第{chapter_num}章",
        key_points=["要点A"],
        characters=["主角"],
        settings=["场景"],
        conflicts=["冲突"],
        **kwargs,
    )


class TestExtendedFieldsAlwaysWritten:
    """[P0] 扩展字段 5 个永久落盘,而非 if-guarded"""

    def test_empty_extensions_still_persisted(self, gen_with_outlines):
        """全部扩展字段为默认空值时,JSON 中仍含 5 个字段(空字符串/空 dict/空 list)"""
        gen_with_outlines.chapter_outlines = [_make_chapter(1)]
        assert gen_with_outlines._save_outline() is True

        data = _read_saved_outline(gen_with_outlines.output_dir)
        assert len(data) == 1
        ch = data[0]
        # 必填基础字段
        assert ch["chapter_number"] == 1
        # 关键: 5 个扩展字段全部存在,与默认值类型对齐
        assert ch["emotion_tone"] == ""
        assert ch["character_goals"] == {}
        assert ch["scene_sequence"] == []
        assert ch["foreshadowing"] == []
        assert ch["pov_character"] == ""

    def test_partial_extensions_preserve_filled_values(self, gen_with_outlines):
        """部分填充时,有值的字段保留原值,空字段仍以默认值出现"""
        gen_with_outlines.chapter_outlines = [
            _make_chapter(
                1,
                emotion_tone="紧张→释然",
                pov_character="林小凡",
            )
        ]
        gen_with_outlines._save_outline()

        ch = _read_saved_outline(gen_with_outlines.output_dir)[0]
        assert ch["emotion_tone"] == "紧张→释然"
        assert ch["pov_character"] == "林小凡"
        # 未填的依然写出,而非缺失
        assert ch["character_goals"] == {}
        assert ch["scene_sequence"] == []
        assert ch["foreshadowing"] == []

    def test_full_extensions_roundtrip(self, gen_with_outlines):
        """所有扩展字段都填值时,JSON 落盘 + 重读后值不丢失"""
        gen_with_outlines.chapter_outlines = [
            _make_chapter(
                1,
                emotion_tone="压抑→爆发",
                character_goals={"主角": "破境", "反派": "阻挠"},
                scene_sequence=["山门", "古洞", "山顶"],
                foreshadowing=["埋设:玉佩光芒", "回收:第3章伏笔"],
                pov_character="主角",
            )
        ]
        gen_with_outlines._save_outline()

        ch = _read_saved_outline(gen_with_outlines.output_dir)[0]
        assert ch["emotion_tone"] == "压抑→爆发"
        assert ch["character_goals"] == {"主角": "破境", "反派": "阻挠"}
        assert ch["scene_sequence"] == ["山门", "古洞", "山顶"]
        assert ch["foreshadowing"] == ["埋设:玉佩光芒", "回收:第3章伏笔"]
        assert ch["pov_character"] == "主角"

    def test_field_order_in_json_is_predictable(self, gen_with_outlines):
        """落盘字段顺序: 基础 6 字段 → 扩展 5 字段(便于人工 diff)"""
        gen_with_outlines.chapter_outlines = [_make_chapter(1)]
        gen_with_outlines._save_outline()
        ch = _read_saved_outline(gen_with_outlines.output_dir)[0]
        keys = list(ch.keys())
        # 至少前 6 个为基础字段
        assert keys[:6] == [
            "chapter_number", "title", "key_points",
            "characters", "settings", "conflicts",
        ]
        # 5 个扩展字段紧随其后
        assert set(keys[6:]) == {
            "emotion_tone", "character_goals",
            "scene_sequence", "foreshadowing", "pov_character",
        }


class TestCoverageStats:
    """[P0] 保存后输出覆盖率统计,低覆盖率升级为 WARNING"""

    def test_low_emotion_coverage_logs_warning(self, gen_with_outlines, caplog):
        """emotion_tone 覆盖率 < 50% 时 → WARNING + 提示 backfill 工具"""
        # 10 章,只有 1 章有 emotion_tone (10% 覆盖率)
        outlines = [_make_chapter(i) for i in range(1, 11)]
        outlines[0].emotion_tone = "紧张"
        gen_with_outlines.chapter_outlines = outlines

        with caplog.at_level(logging.WARNING):
            gen_with_outlines._save_outline()

        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        # 至少有一条提及 emotion_tone 覆盖率
        emotion_warns = [w for w in warnings if "emotion_tone" in w.getMessage()]
        assert emotion_warns, "应该 WARNING 提示 emotion_tone 覆盖率偏低"
        # 提示中应当指向 backfill 工具
        assert any("backfill_emotion_tone" in w.getMessage() for w in emotion_warns)

    def test_high_emotion_coverage_logs_info_only(self, gen_with_outlines, caplog):
        """emotion_tone 覆盖率 >= 50% 时 → 仅 INFO,无 WARNING"""
        outlines = [_make_chapter(i) for i in range(1, 11)]
        # 6/10 = 60% 覆盖率
        for o in outlines[:6]:
            o.emotion_tone = "成长"
        gen_with_outlines.chapter_outlines = outlines

        with caplog.at_level(logging.DEBUG):
            gen_with_outlines._save_outline()

        # 不应有覆盖率相关的 WARNING
        warnings = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING and "emotion_tone" in r.getMessage()
            and "覆盖率" in r.getMessage()
        ]
        assert not warnings
        # 但应当存在 INFO 级别的覆盖率统计
        info_msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
        assert any("扩展字段覆盖率统计" in m for m in info_msgs)

    def test_stats_count_correct_per_field(self, gen_with_outlines, caplog):
        """每字段独立计数,不串扰"""
        outlines = [_make_chapter(i) for i in range(1, 5)]
        outlines[0].emotion_tone = "A"
        outlines[1].emotion_tone = "B"
        outlines[2].pov_character = "主角"
        # outlines[3] 完全空
        gen_with_outlines.chapter_outlines = outlines

        with caplog.at_level(logging.INFO):
            gen_with_outlines._save_outline()

        all_msgs = "\n".join(r.getMessage() for r in caplog.records)
        # emotion_tone 应统计为 2/4
        assert "emotion_tone: 2/4" in all_msgs
        # pov_character 应统计为 1/4
        assert "pov_character: 1/4" in all_msgs


class TestInvariantsPreserved:
    """[P0] 重构后原 _save_outline 的不变量必须保持"""

    def test_none_slots_skipped(self, gen_with_outlines):
        """稀疏 None 槽位继续被跳过(保留位置语义但不落盘)"""
        gen_with_outlines.chapter_outlines = [
            _make_chapter(1),
            None,
            _make_chapter(3),
        ]
        gen_with_outlines._save_outline()
        data = _read_saved_outline(gen_with_outlines.output_dir)
        chapter_nums = [d["chapter_number"] for d in data]
        assert chapter_nums == [1, 3]

    def test_duplicate_chapter_number_kept_first(self, gen_with_outlines):
        """重复 chapter_number 仅保留首次出现的版本"""
        first = _make_chapter(1, emotion_tone="第一次")
        dup = _make_chapter(1, emotion_tone="重复-应被丢弃")
        gen_with_outlines.chapter_outlines = [first, dup]
        gen_with_outlines._save_outline()
        data = _read_saved_outline(gen_with_outlines.output_dir)
        assert len(data) == 1
        assert data[0]["emotion_tone"] == "第一次"

    def test_chapter_number_ascending(self, gen_with_outlines):
        """无论内存中顺序,落盘后必须按 chapter_number 升序"""
        gen_with_outlines.chapter_outlines = [
            _make_chapter(3),
            _make_chapter(1),
            _make_chapter(2),
        ]
        gen_with_outlines._save_outline()
        data = _read_saved_outline(gen_with_outlines.output_dir)
        nums = [d["chapter_number"] for d in data]
        assert nums == [1, 2, 3]

    def test_empty_outlines_returns_false(self, gen_with_outlines):
        """完全没有有效大纲时返回 False(与原行为一致)"""
        gen_with_outlines.chapter_outlines = []
        assert gen_with_outlines._save_outline() is False
