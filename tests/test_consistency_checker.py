# -*- coding: utf-8 -*-
"""
测试一致性检查器模块 - ConsistencyChecker
"""

import os
import json
import pytest
from unittest.mock import MagicMock, patch
from src.generators.content.consistency_checker import ConsistencyChecker


class TestConsistencyChecker:
    """ConsistencyChecker 测试"""

    @pytest.fixture
    def checker(self, tmp_path):
        mock_model = MagicMock()
        mock_model.generate.return_value = "[总体评分]: 85\n[修改必要性]: 无需修改"
        return ConsistencyChecker(mock_model, str(tmp_path))

    @pytest.fixture
    def checker_needs_revision(self, tmp_path):
        mock_model = MagicMock()
        mock_model.generate.return_value = '[总体评分]: 50\n[修改必要性]: "需要修改"'
        return ConsistencyChecker(mock_model, str(tmp_path))

    def test_init_defaults(self, checker):
        assert checker.min_acceptable_score == 75
        assert checker.max_revision_attempts == 3

    def test_check_passes(self, checker):
        outline = {"chapter_number": 1, "title": "测试", "key_points": ["点1"], "characters": ["A"], "settings": ["B"], "conflicts": ["C"]}
        sync_info = {"世界观": {}, "人物设定": {"人物信息": []}, "剧情发展": {"主线梗概": "", "进行中冲突": [], "悬念伏笔": []}}
        report, needs_revision, score = checker.check_chapter_consistency(
            chapter_content="测试内容",
            chapter_outline=outline,
            chapter_idx=0,
            sync_info=sync_info,
        )
        assert score == 85
        assert needs_revision is False

    def test_check_needs_revision(self, checker_needs_revision):
        outline = {"chapter_number": 1, "title": "测试", "key_points": [], "characters": [], "settings": [], "conflicts": []}
        sync_info = {"世界观": {}, "人物设定": {"人物信息": []}, "剧情发展": {"主线梗概": "", "进行中冲突": [], "悬念伏笔": []}}
        report, needs_revision, score = checker_needs_revision.check_chapter_consistency(
            chapter_content="测试内容",
            chapter_outline=outline,
            chapter_idx=0,
            sync_info=sync_info,
        )
        assert score == 50
        assert needs_revision is True

    def test_check_model_error(self, tmp_path):
        mock_model = MagicMock()
        mock_model.generate.side_effect = Exception("API错误")
        checker = ConsistencyChecker(mock_model, str(tmp_path))
        outline = {"chapter_number": 1, "title": "测试", "key_points": [], "characters": [], "settings": [], "conflicts": []}
        sync_info = {"世界观": {}, "人物设定": {"人物信息": []}, "剧情发展": {"主线梗概": "", "进行中冲突": [], "悬念伏笔": []}}
        report, needs_revision, score = checker.check_chapter_consistency(
            chapter_content="内容", chapter_outline=outline, chapter_idx=0, sync_info=sync_info,
        )
        assert "出错" in report
        assert needs_revision is True
        assert score == 0

    def test_revise_chapter(self, tmp_path):
        mock_model = MagicMock()
        mock_model.generate.return_value = "修正后的章节内容"
        checker = ConsistencyChecker(mock_model, str(tmp_path))
        outline = {"chapter_number": 1, "title": "测试", "key_points": [], "characters": [], "settings": [], "conflicts": []}
        result = checker.revise_chapter("原始内容", "需要修改人物行为", outline, 0)
        assert result == "修正后的章节内容"

    def test_revise_chapter_error_returns_original(self, tmp_path):
        mock_model = MagicMock()
        mock_model.generate.side_effect = Exception("API错误")
        checker = ConsistencyChecker(mock_model, str(tmp_path))
        outline = {"chapter_number": 1, "title": "测试", "key_points": [], "characters": [], "settings": [], "conflicts": []}
        result = checker.revise_chapter("原始内容", "报告", outline, 0)
        assert result == "原始内容"

    def test_ensure_chapter_consistency_passes_first_try(self, checker):
        outline = {"chapter_number": 1, "title": "测试", "key_points": [], "characters": [], "settings": [], "conflicts": []}
        sync_info = {"世界观": {}, "人物设定": {"人物信息": []}, "剧情发展": {"主线梗概": "", "进行中冲突": [], "悬念伏笔": []}}
        result = checker.ensure_chapter_consistency(
            chapter_content="好内容", chapter_outline=outline, chapter_idx=0, sync_info=sync_info,
        )
        assert result == "好内容"

    def test_get_previous_summary_no_file(self, checker):
        result = checker._get_previous_summary(1)
        assert result == ""

    def test_get_previous_summary_with_file(self, tmp_path):
        mock_model = MagicMock()
        checker = ConsistencyChecker(mock_model, str(tmp_path))
        summary_file = os.path.join(str(tmp_path), "summary.json")
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump({"1": "第一章摘要内容"}, f)
        result = checker._get_previous_summary(1)
        assert result == "第一章摘要内容"

    def test_get_previous_summary_chapter_zero(self, checker):
        result = checker._get_previous_summary(0)
        assert result == ""

    def test_score_extraction_regex(self, tmp_path):
        """测试不同格式的评分提取"""
        mock_model = MagicMock()
        mock_model.generate.return_value = "[总体评分]: 92\n[修改必要性]: 无需修改"
        checker = ConsistencyChecker(mock_model, str(tmp_path))
        outline = {"chapter_number": 1, "title": "t", "key_points": [], "characters": [], "settings": [], "conflicts": []}
        sync_info = {"世界观": {}, "人物设定": {"人物信息": []}, "剧情发展": {"主线梗概": "", "进行中冲突": [], "悬念伏笔": []}}
        _, _, score = checker.check_chapter_consistency("内容", outline, 0, sync_info=sync_info)
        assert score == 92
