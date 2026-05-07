# -*- coding: utf-8 -*-
"""
测试验证器模块 - LogicValidator, DuplicateValidator
"""

import pytest
from unittest.mock import MagicMock
from src.generators.content.validators import LogicValidator, DuplicateValidator


class TestLogicValidator:
    """逻辑验证器测试"""

    def test_check_logic_needs_revision(self):
        mock_model = MagicMock()
        mock_model.generate.return_value = "[总体评分]: 50\n[修改必要性]: 需要修改"
        validator = LogicValidator(mock_model)
        report, needs_revision = validator.check_logic(
            chapter_content="测试内容",
            chapter_outline={"chapter_number": 1, "title": "测试", "key_points": [], "characters": [], "settings": [], "conflicts": []},
        )
        assert needs_revision is True
        assert "50" in report

    def test_check_logic_no_revision(self):
        mock_model = MagicMock()
        mock_model.generate.return_value = "[总体评分]: 90\n[修改必要性]: 无需修改"
        validator = LogicValidator(mock_model)
        report, needs_revision = validator.check_logic(
            chapter_content="测试内容",
            chapter_outline={"chapter_number": 1, "title": "测试", "key_points": [], "characters": [], "settings": [], "conflicts": []},
        )
        assert needs_revision is False

    def test_check_logic_with_sync_info(self):
        mock_model = MagicMock()
        mock_model.generate.return_value = "[修改必要性]: 无需修改"
        validator = LogicValidator(mock_model)
        report, needs_revision = validator.check_logic(
            chapter_content="内容",
            chapter_outline={"chapter_number": 1, "title": "t", "key_points": [], "characters": [], "settings": [], "conflicts": []},
            sync_info="同步信息",
        )
        # 验证 prompt 中包含了 sync_info
        call_args = mock_model.generate.call_args[0][0]
        assert "同步信息" in call_args

    def test_check_logic_model_error(self):
        mock_model = MagicMock()
        mock_model.generate.side_effect = Exception("API错误")
        validator = LogicValidator(mock_model)
        report, needs_revision = validator.check_logic(
            chapter_content="内容",
            chapter_outline={"chapter_number": 1, "title": "t", "key_points": [], "characters": [], "settings": [], "conflicts": []},
        )
        assert "出错" in report
        assert needs_revision is True


class TestDuplicateValidator:
    """重复文字验证器测试"""

    def test_no_duplicates(self):
        mock_model = MagicMock()
        validator = DuplicateValidator(mock_model)
        report, needs_revision = validator.check_duplicates("这是一段完全不重复的文本内容。")
        assert needs_revision is False
        assert "未发现" in report

    def test_internal_duplicates(self):
        mock_model = MagicMock()
        validator = DuplicateValidator(mock_model)
        validator.min_duplicate_length = 10
        # 构造内部重复
        repeated = "这是一段需要重复检测的文本内容" * 5
        padding = "A" * 200
        content = repeated + padding + repeated
        report, needs_revision = validator.check_duplicates(content)
        assert needs_revision is True

    def test_cross_chapter_duplicates(self):
        mock_model = MagicMock()
        validator = DuplicateValidator(mock_model)
        validator.min_duplicate_length = 10
        shared_text = "这是两个章节之间共享的一段很长的文本内容，用于测试跨章节重复检测功能"
        current = shared_text + "当前章节的独有内容" * 20
        prev = shared_text + "上一章节的独有内容" * 20
        report, needs_revision = validator.check_duplicates(current, prev_content=prev)
        assert needs_revision is True
        assert "跨章节" in report or "上一章" in report

    def test_empty_content(self):
        mock_model = MagicMock()
        validator = DuplicateValidator(mock_model)
        report, needs_revision = validator.check_duplicates("")
        assert needs_revision is False

    def test_performance_protection(self):
        """验证性能保护参数生效"""
        mock_model = MagicMock()
        validator = DuplicateValidator(mock_model)
        assert validator.max_scan_chars == 6000
        assert validator.window_stride == 5
        assert validator.max_report_items == 50

    def test_generate_report_format(self):
        mock_model = MagicMock()
        validator = DuplicateValidator(mock_model)
        report = validator._generate_report([], [])
        assert "重复文字验证报告" in report
        assert "未发现" in report
        assert "总计发现 0 处重复" in report

    def test_generate_report_with_duplicates(self):
        mock_model = MagicMock()
        validator = DuplicateValidator(mock_model)
        internal = [("重复内容片段", 0, 100)]
        cross = [("prev", "跨章节重复", 50, 200)]
        report = validator._generate_report(internal, cross)
        assert "章节内部重复" in report
        assert "跨章节重复" in report
        assert "总计发现 2 处重复" in report
