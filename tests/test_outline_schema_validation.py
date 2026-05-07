# -*- coding: utf-8 -*-
"""[5.5] _looks_like_chapter_outline schema 校验测试

防止 JSON 流式恢复时把嵌套字典(character_goals 等)误捕为章节。
"""

import pytest
from src.generators.outline.outline_generator import OutlineGenerator


class TestLooksLikeChapterOutline:
    def test_with_chapter_number_field(self):
        """有 chapter_number 字段 → 视为章节"""
        assert OutlineGenerator._looks_like_chapter_outline({
            "chapter_number": 1, "title": "第一章"
        })

    def test_with_chapter_number_only(self):
        """仅有 chapter_number 也通过(优先信号)"""
        assert OutlineGenerator._looks_like_chapter_outline({"chapter_number": 5})

    def test_title_with_key_points(self):
        """title + key_points 通过"""
        assert OutlineGenerator._looks_like_chapter_outline({
            "title": "测试章", "key_points": ["要点1"]
        })

    def test_title_with_characters(self):
        """title + characters 通过"""
        assert OutlineGenerator._looks_like_chapter_outline({
            "title": "X", "characters": ["主角"]
        })

    def test_title_with_settings(self):
        """title + settings 通过"""
        assert OutlineGenerator._looks_like_chapter_outline({
            "title": "X", "settings": ["山林"]
        })

    def test_title_with_conflicts(self):
        """title + conflicts 通过"""
        assert OutlineGenerator._looks_like_chapter_outline({
            "title": "X", "conflicts": ["人vs妖"]
        })

    def test_title_alone_rejected(self):
        """仅 title 不足以判定为章节"""
        assert not OutlineGenerator._looks_like_chapter_outline({"title": "可疑"})

    def test_character_goals_nested_dict_rejected(self):
        """character_goals 嵌套字典不应被误判为章节"""
        # 模拟 LLM 返回中嵌套的 character_goals 子结构
        nested = {"林小凡": "突破", "苏婉清": "守宗门"}
        assert not OutlineGenerator._looks_like_chapter_outline(nested)

    def test_foreshadowing_dict_rejected(self):
        """伏笔/同步信息子结构不应被误判"""
        nested = {"信物": "玉佩", "回收点": "结局"}
        assert not OutlineGenerator._looks_like_chapter_outline(nested)

    def test_empty_dict_rejected(self):
        """空字典 → 拒绝"""
        assert not OutlineGenerator._looks_like_chapter_outline({})

    def test_non_dict_rejected(self):
        """非 dict 类型一律拒绝"""
        assert not OutlineGenerator._looks_like_chapter_outline(None)
        assert not OutlineGenerator._looks_like_chapter_outline([])
        assert not OutlineGenerator._looks_like_chapter_outline("不是dict")
        assert not OutlineGenerator._looks_like_chapter_outline(123)

    def test_full_chapter_outline(self):
        """完整章节大纲对象通过"""
        full = {
            "chapter_number": 3,
            "title": "试炼",
            "key_points": ["遭遇袭击", "突破筑基"],
            "characters": ["林小凡"],
            "settings": ["山林"],
            "conflicts": ["人vs妖"],
            "emotion_tone": "紧张",
        }
        assert OutlineGenerator._looks_like_chapter_outline(full)
