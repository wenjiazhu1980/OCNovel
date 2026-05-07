# -*- coding: utf-8 -*-
"""
测试定稿处理器模块 - NovelFinalizer
"""

import os
import json
import pytest
from unittest.mock import MagicMock, patch
from dataclasses import asdict
from src.generators.finalizer.finalizer import NovelFinalizer
from src.generators.common.data_structures import ChapterOutline


class TestNovelFinalizer:
    """NovelFinalizer 测试"""

    @pytest.fixture
    def mock_content_model(self):
        model = MagicMock()
        model.model_name = "mock-content"
        model.generate.return_value = "这是一段模拟生成的摘要内容"
        return model

    @pytest.fixture
    def mock_kb(self):
        kb = MagicMock()
        kb.search.return_value = []
        kb.is_built = True
        kb.embedding_model = MagicMock()
        kb.embedding_model.model_name = "mock"
        kb.reranker_config = None
        return kb

    @pytest.fixture
    def finalizer(self, mock_config, mock_content_model, mock_kb, output_dir_with_outline):
        return NovelFinalizer(mock_config, mock_content_model, mock_kb)

    @pytest.fixture
    def finalizer_with_chapter(self, finalizer, output_dir_with_outline, sample_chapter_outlines):
        """创建带有章节文件的 finalizer"""
        outline = sample_chapter_outlines[0]
        chapter_file = os.path.join(output_dir_with_outline, f"第1章_{outline.title}.txt")
        with open(chapter_file, "w", encoding="utf-8") as f:
            f.write("第1章 第1章标题\n\n这是第一章的内容，讲述了主角的冒险故事。" * 10)
        return finalizer

    def test_init(self, finalizer, mock_config):
        assert finalizer.output_dir == mock_config.output_config["output_dir"]

    def test_finalize_chapter_success(self, finalizer_with_chapter):
        result = finalizer_with_chapter.finalize_chapter(1)
        assert result is True

    def test_finalize_chapter_no_outline(self, mock_config, mock_content_model, mock_kb):
        """没有大纲文件时应失败"""
        output_dir = mock_config.output_config["output_dir"]
        # 确保没有 outline.json
        outline_path = os.path.join(output_dir, "outline.json")
        if os.path.exists(outline_path):
            os.remove(outline_path)
        finalizer = NovelFinalizer(mock_config, mock_content_model, mock_kb)
        result = finalizer.finalize_chapter(1)
        assert result is False

    def test_finalize_chapter_no_chapter_file(self, finalizer):
        """章节文件不存在时应失败"""
        result = finalizer.finalize_chapter(1)
        assert result is False

    def test_finalize_chapter_out_of_range(self, finalizer):
        result = finalizer.finalize_chapter(999)
        assert result is False

    def test_clean_filename(self, finalizer):
        assert finalizer._clean_filename("正常标题") == "正常标题"
        assert finalizer._clean_filename('包含"特殊"字符') == "包含特殊字符"
        assert finalizer._clean_filename("a/b\\c*d?e") == "abcde"
        assert finalizer._clean_filename("") != ""  # 空字符串应返回默认名
        assert finalizer._clean_filename("  . ") != ""

    def test_update_summary(self, finalizer_with_chapter, mock_content_model):
        mock_content_model.generate.return_value = "生成的摘要内容"
        result = finalizer_with_chapter._update_summary(1, "章节内容")
        assert result is True
        summary_file = os.path.join(finalizer_with_chapter.output_dir, "summary.json")
        assert os.path.exists(summary_file)

    def test_clean_summary(self, finalizer):
        assert finalizer._clean_summary("章节摘要：实际内容") == "实际内容"
        assert finalizer._clean_summary("摘要：实际内容") == "实际内容"
        assert finalizer._clean_summary("本章讲述了主角的冒险") == "主角的冒险"
        assert finalizer._clean_summary("  空白内容  ") == "空白内容"
        assert finalizer._clean_summary("") == ""
        assert finalizer._clean_summary("正常内容不需要清理") == "正常内容不需要清理"

    def test_should_trigger_auto_imitation_disabled(self, finalizer):
        assert finalizer._should_trigger_auto_imitation(1) is False

    def test_should_trigger_auto_imitation_enabled(self, mock_config, mock_content_model, mock_kb, output_dir_with_outline):
        mock_config.imitation_config = {
            "enabled": True,
            "auto_imitation": {
                "enabled": True,
                "trigger_all_chapters": True,
            },
        }
        finalizer = NovelFinalizer(mock_config, mock_content_model, mock_kb)
        assert finalizer._should_trigger_auto_imitation(1) is True

    def test_should_trigger_auto_imitation_specific_chapters(self, mock_config, mock_content_model, mock_kb, output_dir_with_outline):
        mock_config.imitation_config = {
            "enabled": True,
            "auto_imitation": {
                "enabled": True,
                "trigger_chapters": [5, 10, 15],
            },
        }
        finalizer = NovelFinalizer(mock_config, mock_content_model, mock_kb)
        assert finalizer._should_trigger_auto_imitation(5) is True
        assert finalizer._should_trigger_auto_imitation(3) is False

    def test_get_current_progress_no_file(self, finalizer):
        result = finalizer._get_current_progress("/nonexistent/sync_info.json")
        assert result is None

    def test_get_current_progress_with_file(self, finalizer):
        sync_file = os.path.join(finalizer.output_dir, "sync_info.json")
        with open(sync_file, "w", encoding="utf-8") as f:
            json.dump({"最后更新章节": 5}, f)
        result = finalizer._get_current_progress(sync_file)
        assert result == 5

    def test_backup_sync_info(self, finalizer):
        sync_file = os.path.join(finalizer.output_dir, "sync_info.json")
        with open(sync_file, "w", encoding="utf-8") as f:
            json.dump({"test": True}, f)
        result = finalizer._backup_sync_info(sync_file)
        assert result is True

    def test_backup_sync_info_no_file(self, finalizer):
        result = finalizer._backup_sync_info("/nonexistent/sync_info.json")
        assert result is True  # 不存在时返回 True（无需备份）
