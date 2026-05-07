# -*- coding: utf-8 -*-
"""
测试数据结构模块 - ChapterOutline, NovelOutline, Character
"""

import pytest
from dataclasses import asdict
from src.generators.common.data_structures import ChapterOutline, NovelOutline, Character


class TestChapterOutline:
    """ChapterOutline 数据结构测试"""

    def test_create_basic(self):
        outline = ChapterOutline(
            chapter_number=1,
            title="测试章节",
            key_points=["点1", "点2"],
            characters=["角色A"],
            settings=["场景A"],
            conflicts=["冲突A"],
        )
        assert outline.chapter_number == 1
        assert outline.title == "测试章节"
        assert len(outline.key_points) == 2
        assert "角色A" in outline.characters

    def test_asdict_roundtrip(self, sample_chapter_outline):
        d = asdict(sample_chapter_outline)
        restored = ChapterOutline(**d)
        assert restored.chapter_number == sample_chapter_outline.chapter_number
        assert restored.title == sample_chapter_outline.title
        assert restored.key_points == sample_chapter_outline.key_points

    def test_empty_lists(self):
        outline = ChapterOutline(
            chapter_number=0,
            title="",
            key_points=[],
            characters=[],
            settings=[],
            conflicts=[],
        )
        assert outline.key_points == []
        assert outline.characters == []


class TestNovelOutline:
    """NovelOutline 数据结构测试"""

    def test_create_with_chapters(self, sample_chapter_outlines):
        novel = NovelOutline(title="测试小说", chapters=sample_chapter_outlines)
        assert novel.title == "测试小说"
        assert len(novel.chapters) == 5

    def test_empty_chapters(self):
        novel = NovelOutline(title="空小说", chapters=[])
        assert len(novel.chapters) == 0


class TestCharacter:
    """Character 数据结构测试"""

    def test_create_with_defaults(self):
        char = Character(
            name="林小凡",
            role="主角",
            personality={"坚韧": 0.9, "善良": 0.7},
            goals=["逆天改命"],
            relationships={"王大锤": "好友"},
            development_stage="初期",
        )
        assert char.name == "林小凡"
        assert char.alignment == "中立"
        assert char.realm == "凡人"
        assert char.level == 1
        assert char.cultivation_method == "无"
        assert char.magic_treasure == []
        assert char.stamina == 100
        assert char.sect == "无门无派"

    def test_create_with_custom_fields(self):
        char = Character(
            name="张三丰",
            role="导师",
            personality={"睿智": 0.95},
            goals=["传道授业"],
            relationships={},
            development_stage="巅峰",
            alignment="正派",
            realm="元婴期",
            level=50,
            cultivation_method="太极功",
            magic_treasure=["太极剑"],
            sect="武当派",
            position="掌门",
        )
        assert char.realm == "元婴期"
        assert char.level == 50
        assert "太极剑" in char.magic_treasure
        assert char.sect == "武当派"

    def test_mutable_default_fields_isolation(self):
        """确保 field(default_factory=list) 不会在实例间共享"""
        c1 = Character(name="A", role="r", personality={}, goals=[], relationships={}, development_stage="s")
        c2 = Character(name="B", role="r", personality={}, goals=[], relationships={}, development_stage="s")
        c1.magic_treasure.append("剑")
        assert c2.magic_treasure == []
        c1.emotions_history.append("开心")
        assert c2.emotions_history == []
