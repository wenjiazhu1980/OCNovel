# -*- coding: utf-8 -*-
"""[5.6] _chapter_content_exists 多版本章节匹配测试

旧实现遇多版本历史标题时依赖 os.listdir() 顺序;新实现按 mtime 倒序选最新并 warning。
"""

import os
import time
import json
import pytest
from unittest.mock import MagicMock
from src.generators.content.content_generator import ContentGenerator


@pytest.fixture
def generator(mock_config, output_dir_with_outline):
    """复用 conftest.py 的 mock_config + output_dir_with_outline"""
    mock_model = MagicMock()
    mock_model.model_name = "mock"
    mock_model.generate.return_value = "内容"
    mock_model.embed.return_value = __import__("numpy").random.rand(128).astype("float32")
    mock_kb = MagicMock()
    mock_kb.search.return_value = []
    mock_kb.is_built = True
    mock_kb.embedding_model = MagicMock()
    mock_kb.embedding_model.model_name = "mock"
    mock_kb.reranker_config = None
    gen = ContentGenerator(mock_config, mock_model, mock_kb)
    gen._load_outline()
    return gen


class TestChapterContentExistsMultiVersion:
    def test_no_matching_file_returns_none(self, generator, output_dir_with_outline):
        """无匹配文件 → None"""
        assert generator._chapter_content_exists(99) is None

    def test_single_match_returned(self, generator, output_dir_with_outline):
        """唯一候选直接返回"""
        path = os.path.join(output_dir_with_outline, "第1章_test_v1.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("v1")
        result = generator._chapter_content_exists(1)
        assert result is not None
        assert os.path.basename(result) == "第1章_test_v1.txt"

    def test_multiple_versions_picks_newest(self, generator, output_dir_with_outline):
        """多版本: 按 mtime 倒序,返回最新"""
        old_path = os.path.join(output_dir_with_outline, "第1章_old_title.txt")
        new_path = os.path.join(output_dir_with_outline, "第1章_new_title.txt")
        with open(old_path, "w", encoding="utf-8") as f:
            f.write("old")
        # 强制 mtime 较旧
        old_time = time.time() - 3600
        os.utime(old_path, (old_time, old_time))
        # 写新文件,mtime 自然更新
        with open(new_path, "w", encoding="utf-8") as f:
            f.write("new")

        result = generator._chapter_content_exists(1)
        assert result is not None
        assert os.path.basename(result) == "第1章_new_title.txt"

    def test_excludes_imitated_and_summary_files(self, generator, output_dir_with_outline):
        """排除 _imitated / _摘要 后缀文件"""
        # 仅写仿写版与摘要,无原版
        with open(os.path.join(output_dir_with_outline, "第1章_test_imitated.txt"), "w") as f:
            f.write("仿写")
        with open(os.path.join(output_dir_with_outline, "第1章_test_摘要.txt"), "w") as f:
            f.write("摘要")
        # 应该返回 None,因为这些文件被排除
        result = generator._chapter_content_exists(1)
        assert result is None

    def test_expected_path_short_circuit(self, generator, output_dir_with_outline):
        """优先用 outline 标题构造预期路径,命中即返回(不进入扫描)"""
        # generator.chapter_outlines[0].title 来自 fixture
        outline = generator.chapter_outlines[0]
        cleaned_title = generator._clean_filename(outline.title)
        expected_path = os.path.join(
            output_dir_with_outline, f"第1章_{cleaned_title}.txt"
        )
        with open(expected_path, "w", encoding="utf-8") as f:
            f.write("expected")
        # 同时写一个干扰版本
        with open(os.path.join(output_dir_with_outline, "第1章_其他版本.txt"), "w") as f:
            f.write("other")
        result = generator._chapter_content_exists(1)
        # 优先返回 expected_path
        assert result == expected_path
