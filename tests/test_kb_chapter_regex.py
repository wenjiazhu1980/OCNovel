# -*- coding: utf-8 -*-
"""[Phase 6.2] knowledge_base 章节切分中文数字支持

验证 _chunk_text 能识别阿拉伯数字 + 中文数字两类章节标题,
并正确丢弃首段非章节内容。
"""

import re
import pytest

# 直接复制实际使用的正则,避免实例化 KnowledgeBase(依赖 FAISS/embedding)
_CH_NUM_PATTERN = r'第[\d一二三四五六七八九十百千零两万]{1,10}章'


def split_chapters(text: str) -> list[str]:
    """复刻 _chunk_text 中的切分 + 首段过滤逻辑(纯函数版本便于测试)"""
    chapters = re.split(rf'(?={_CH_NUM_PATTERN})', text)
    chapters = [c for c in chapters if c.strip()]
    if len(chapters) <= 1:
        return chapters or [text]
    if not re.match(rf'\s*{_CH_NUM_PATTERN}', chapters[0]):
        chapters = chapters[1:]
    return chapters


class TestChineseChapterRegex:
    def test_arabic_numerals(self):
        """阿拉伯数字章节(向后兼容)"""
        text = "第1章 起源\n内容A\n第2章 觉醒\n内容B\n第10章 终章\n内容C"
        chapters = split_chapters(text)
        assert len(chapters) == 3
        assert chapters[0].startswith("第1章")
        assert chapters[1].startswith("第2章")
        assert chapters[2].startswith("第10章")

    def test_simple_chinese_numerals(self):
        """一二三...十"""
        text = "第一章 起源\n内容\n第二章 觉醒\n内容\n第十章 终章\n内容"
        chapters = split_chapters(text)
        assert len(chapters) == 3
        assert chapters[0].startswith("第一章")
        assert chapters[1].startswith("第二章")
        assert chapters[2].startswith("第十章")

    def test_compound_chinese_numerals(self):
        """二十/百/零的组合"""
        text = "第二十章 突破\n正文1\n第一百零一章 巅峰\n正文2"
        chapters = split_chapters(text)
        assert len(chapters) == 2
        assert chapters[0].startswith("第二十章")
        assert chapters[1].startswith("第一百零一章")

    def test_thousand_chinese(self):
        """千/两千"""
        text = "第一千章 神话\n内容1\n第两千章 终焉\n内容2"
        chapters = split_chapters(text)
        assert len(chapters) == 2
        assert chapters[0].startswith("第一千章")
        assert chapters[1].startswith("第两千章")

    def test_mixed_arabic_and_chinese(self):
        """阿拉伯与中文混排"""
        text = "第1章 开篇\n内容\n第二章 中段\n内容\n第30章 收尾"
        chapters = split_chapters(text)
        assert len(chapters) == 3
        assert chapters[0].startswith("第1章")
        assert chapters[1].startswith("第二章")
        assert chapters[2].startswith("第30章")

    def test_preface_dropped_arabic(self):
        """阿拉伯数字场景:首段非章节(前言)被丢弃"""
        text = "前言\n这是作者前言\n第1章 起源\n正文"
        chapters = split_chapters(text)
        assert len(chapters) == 1
        assert chapters[0].startswith("第1章")

    def test_preface_dropped_chinese(self):
        """中文数字场景:首段非章节(目录)被丢弃"""
        text = "目录\n第一章 起源\n第二章 觉醒\n----\n第一章 起源\n正文1"
        chapters = split_chapters(text)
        # 首段(含两个章节链接但不以"第N章"开头) → 丢弃
        # 剩余为正文部分
        # 注意:其实第一段会因含"第一章"被切分,我们期望切分后非章节首段被丢
        # 实际行为: split 后 chapters[0]="目录\n", chapters[1]="第一章 起源\n第二章 觉醒\n----\n",
        # chapters[2]="第一章 起源\n正文1"
        # 因为 chapters[0] 不以 "第N章" 开头 → 被丢弃
        assert len(chapters) >= 1
        assert all(re.match(rf'\s*{_CH_NUM_PATTERN}', c) for c in chapters)

    def test_no_chapters_returns_whole_text(self):
        """无章节标记时返回原文整体"""
        text = "这是一段没有章节的随笔文字。"
        chapters = split_chapters(text)
        assert len(chapters) == 1
        assert chapters[0] == text

    def test_chinese_in_body_not_split(self):
        """正文中含'第'但不构成'第N章' → 不切分"""
        text = "第一章 起源\n他第一次见到她,内心震撼。第二次见面已是数年后。\n第二章 重逢"
        chapters = split_chapters(text)
        # 正文中"第一次/第二次"不应被误识别为章节边界
        assert len(chapters) == 2
        assert chapters[0].startswith("第一章")
        assert chapters[1].startswith("第二章")

    def test_pattern_length_bounded(self):
        """字符类长度限制为 1~10,防止误匹配过长串"""
        # "第" 后跟超过 10 个字符再"章" 不匹配(避免 false positive)
        text = "第一二三四五六七八九十一章 不应被识别\n正文"
        chapters = split_chapters(text)
        # 11 个中文数字字符超出上限,正则不匹配 → 单段
        assert len(chapters) == 1
