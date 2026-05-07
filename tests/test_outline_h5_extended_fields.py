# -*- coding: utf-8 -*-
"""H5 回归测试：大纲扩展字段透传

关联：
- 评审报告 docs/reviews/2026-05-07-codex-review.md §H5
- 修复路线图 docs/reviews/2026-05-07-fix-roadmap.md §Phase 4
"""

import pytest
from src.generators.outline.outline_generator import OutlineGenerator
from src.generators.common.data_structures import ChapterOutline


class TestNormalizeExtendedFields:
    """[H5] _normalize_extended_outline_fields 类型归一化测试"""

    def test_full_payload_preserved(self):
        """完整字段应原样保留(经清洗)"""
        raw = {
            "emotion_tone": "压抑→爆发",
            "character_goals": {"林小凡": "突破筑基", "苏婉清": "守护宗门"},
            "scene_sequence": ["山门遇袭", "雷劫渡劫", "破境而出"],
            "foreshadowing": ["苏师姐的玉佩异动", "宗主秘密日记"],
            "pov_character": "林小凡",
        }
        normalized = OutlineGenerator._normalize_extended_outline_fields(raw)
        assert normalized["emotion_tone"] == "压抑→爆发"
        assert normalized["character_goals"] == {"林小凡": "突破筑基", "苏婉清": "守护宗门"}
        assert normalized["scene_sequence"] == ["山门遇袭", "雷劫渡劫", "破境而出"]
        assert normalized["foreshadowing"] == ["苏师姐的玉佩异动", "宗主秘密日记"]
        assert normalized["pov_character"] == "林小凡"

    def test_missing_fields_use_defaults(self):
        """缺字段时使用空默认值"""
        normalized = OutlineGenerator._normalize_extended_outline_fields({})
        assert normalized == {
            "emotion_tone": "",
            "character_goals": {},
            "scene_sequence": [],
            "foreshadowing": [],
            "pov_character": "",
        }

    def test_none_values_use_defaults(self):
        """字段值为 None 时使用空默认值"""
        raw = {k: None for k in [
            "emotion_tone", "character_goals", "scene_sequence",
            "foreshadowing", "pov_character"
        ]}
        normalized = OutlineGenerator._normalize_extended_outline_fields(raw)
        assert normalized["emotion_tone"] == ""
        assert normalized["character_goals"] == {}
        assert normalized["scene_sequence"] == []
        assert normalized["foreshadowing"] == []
        assert normalized["pov_character"] == ""

    def test_wrong_type_falls_back(self):
        """类型错误时兜底为默认值,不抛异常"""
        raw = {
            "emotion_tone": ["不该是列表"],          # 期望 str
            "character_goals": "不该是字符串",        # 期望 dict
            "scene_sequence": {"a": 1},              # 期望 list
            "foreshadowing": "不该是字符串",          # 期望 list
            "pov_character": {"key": "v"},           # 期望 str
        }
        normalized = OutlineGenerator._normalize_extended_outline_fields(raw)
        assert normalized["emotion_tone"] == ""
        assert normalized["character_goals"] == {}
        assert normalized["scene_sequence"] == []
        assert normalized["foreshadowing"] == []
        assert normalized["pov_character"] == ""

    def test_strings_are_stripped(self):
        """字符串字段应去首尾空白"""
        raw = {"emotion_tone": "  压抑  ", "pov_character": "\t林小凡\n"}
        normalized = OutlineGenerator._normalize_extended_outline_fields(raw)
        assert normalized["emotion_tone"] == "压抑"
        assert normalized["pov_character"] == "林小凡"

    def test_list_items_coerced_to_str(self):
        """列表元素混入非字符串时强制转字符串"""
        raw = {"scene_sequence": ["第一场", 2, 3.14, None, "最后一场"]}
        normalized = OutlineGenerator._normalize_extended_outline_fields(raw)
        # None 被过滤
        assert normalized["scene_sequence"] == ["第一场", "2", "3.14", "最后一场"]


class TestChapterOutlineConstruction:
    """[H5] ChapterOutline 构造时扩展字段被实际写入"""

    def test_construct_with_extended_fields(self):
        """ChapterOutline 直接构造扩展字段应写入实例属性"""
        normalized = OutlineGenerator._normalize_extended_outline_fields({
            "emotion_tone": "紧张",
            "character_goals": {"主角": "活下去"},
            "scene_sequence": ["开篇", "高潮"],
            "foreshadowing": ["神秘信物"],
            "pov_character": "主角",
        })
        outline = ChapterOutline(
            chapter_number=1,
            title="试炼",
            key_points=["遭遇袭击"],
            characters=["主角"],
            settings=["山林"],
            conflicts=["人vs妖"],
            **normalized,
        )
        assert outline.emotion_tone == "紧张"
        assert outline.character_goals == {"主角": "活下去"}
        assert outline.scene_sequence == ["开篇", "高潮"]
        assert outline.foreshadowing == ["神秘信物"]
        assert outline.pov_character == "主角"

    def test_construct_without_extended_fields_uses_defaults(self):
        """旧流程不传扩展字段时使用 ChapterOutline 的默认值(向后兼容)"""
        outline = ChapterOutline(
            chapter_number=1,
            title="测试",
            key_points=["要点"],
            characters=["角色"],
            settings=["场景"],
            conflicts=["冲突"],
        )
        assert outline.emotion_tone == ""
        assert outline.character_goals == {}
        assert outline.scene_sequence == []
        assert outline.foreshadowing == []
        assert outline.pov_character == ""

    def test_dataclass_serialization_roundtrip(self):
        """asdict 序列化后能还原扩展字段(用于 outline.json 落盘回读)"""
        from dataclasses import asdict
        original = ChapterOutline(
            chapter_number=2,
            title="高潮",
            key_points=[],
            characters=[],
            settings=[],
            conflicts=[],
            emotion_tone="决断",
            character_goals={"主角": "出关"},
            scene_sequence=["闭关", "突破"],
            foreshadowing=["天劫预兆"],
            pov_character="主角",
        )
        data = asdict(original)
        restored = ChapterOutline(**data)
        assert restored == original
