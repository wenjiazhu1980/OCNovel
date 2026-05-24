# -*- coding: utf-8 -*-
"""
测试内容生成器模块 - ContentGenerator
"""

import os
import json
import pytest
from unittest.mock import MagicMock, patch
from dataclasses import asdict
from src.generators.content.content_generator import ContentGenerator
from src.generators.common.data_structures import ChapterOutline


class TestContentGenerator:
    """ContentGenerator 测试"""

    @pytest.fixture
    def mock_content_model(self):
        model = MagicMock()
        model.model_name = "mock-content"
        model.generate.return_value = "第1章 废柴觉醒\n\n模拟生成的章节内容，林小凡开始了修炼之路。"
        model.embed.return_value = __import__("numpy").random.rand(128).astype("float32")
        return model

    @pytest.fixture
    def mock_kb(self):
        kb = MagicMock()
        kb.search.return_value = ["参考内容"]
        kb.is_built = True
        kb.embedding_model = MagicMock()
        kb.embedding_model.model_name = "mock-embed"
        kb.reranker_config = None
        return kb

    @pytest.fixture
    def generator(self, mock_config, mock_content_model, mock_kb, output_dir_with_outline):
        return ContentGenerator(mock_config, mock_content_model, mock_kb)

    def test_init(self, generator, mock_config):
        assert generator.output_dir == mock_config.output_config["output_dir"]
        assert generator.current_chapter >= 0
        assert generator.consistency_checker is not None
        assert generator.logic_validator is not None
        assert generator.duplicate_validator is not None

    def test_load_outline(self, generator):
        generator._load_outline()
        assert len(generator.chapter_outlines) == 5

    def test_load_progress_no_summary(self, generator):
        """没有 summary.json 时进度为 0"""
        assert generator.current_chapter == 0

    def test_load_progress_summary_only_treated_as_stale(
        self, mock_config, mock_content_model, mock_kb, output_dir_with_outline
    ):
        """[H3 回归] 仅有 summary 而无正文 → current_chapter 应为 0,且记录为 stale_summary_only"""
        summary_file = os.path.join(output_dir_with_outline, "summary.json")
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump({"1": "摘要1", "2": "摘要2", "3": "摘要3"}, f)
        # 不创建任何正文文件
        gen = ContentGenerator(mock_config, mock_content_model, mock_kb)
        # 完成态以正文存在为硬条件 → 0
        assert gen.current_chapter == 0
        # stale_summary_only 应捕获这 3 个异常章节
        assert gen._chapters_stale_summary_only == [1, 2, 3]

    def test_load_progress_with_content_and_summary(
        self, mock_config, mock_content_model, mock_kb, output_dir_with_outline
    ):
        """[H3 回归] 正文与摘要齐全时,current_chapter 等于连续前缀长度"""
        # 写入 3 章正文 + 摘要
        for i in range(1, 4):
            with open(
                os.path.join(output_dir_with_outline, f"第{i}章_测试.txt"),
                "w",
                encoding="utf-8",
            ) as f:
                f.write(f"第{i}章内容")
        summary_file = os.path.join(output_dir_with_outline, "summary.json")
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump({"1": "摘要1", "2": "摘要2", "3": "摘要3"}, f)
        gen = ContentGenerator(mock_config, mock_content_model, mock_kb)
        assert gen.current_chapter == 3
        assert gen._chapters_stale_summary_only == []
        assert gen._chapters_pending_finalize == []

    def test_load_progress_content_only_pending_finalize(
        self, mock_config, mock_content_model, mock_kb, output_dir_with_outline
    ):
        """[H3 回归] 仅有正文无摘要 → 进入 pending_finalize 待补"""
        for i in range(1, 4):
            with open(
                os.path.join(output_dir_with_outline, f"第{i}章_测试.txt"),
                "w",
                encoding="utf-8",
            ) as f:
                f.write(f"第{i}章内容")
        gen = ContentGenerator(mock_config, mock_content_model, mock_kb)
        # 正文存在 → current_chapter == 3
        assert gen.current_chapter == 3
        assert gen._chapters_pending_finalize == [1, 2, 3]
        assert gen._chapters_stale_summary_only == []

    def test_load_progress_middle_gap_in_content(
        self, mock_config, mock_content_model, mock_kb, output_dir_with_outline
    ):
        """[H3 回归] 中间缺正文(disk={1,3}, summary={1,2,3}) → current_chapter 应为 1,而非旧 union 逻辑的 3"""
        # 仅写第 1, 3 章正文
        for i in [1, 3]:
            with open(
                os.path.join(output_dir_with_outline, f"第{i}章_测试.txt"),
                "w",
                encoding="utf-8",
            ) as f:
                f.write(f"第{i}章内容")
        summary_file = os.path.join(output_dir_with_outline, "summary.json")
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump({"1": "摘要1", "2": "摘要2", "3": "摘要3"}, f)
        gen = ContentGenerator(mock_config, mock_content_model, mock_kb)
        # 第 2 章正文缺失 → 连续前缀只有 1 → 生成循环将从第 2 章重生成
        assert gen.current_chapter == 1
        # 第 2 章被正确识别为 stale_summary_only
        assert 2 in gen._chapters_stale_summary_only

    def test_get_style_prompt(self, generator):
        """测试获取风格提示词"""
        prompt = generator.get_style_prompt()
        assert isinstance(prompt, str)

    def test_get_style_reference(self, generator):
        """测试获取风格参考"""
        prompt, ref = generator.get_style_reference()
        assert isinstance(prompt, str)
        assert isinstance(ref, str)

    def test_process_single_chapter_uses_configured_max_retries(
        self, generator
    ):
        """单章处理应默认使用 generation_config.max_retries"""
        generator.config.generation_config["max_retries"] = 2
        generator.config.generation_config["retry_delay"] = 0
        generator._load_outline()

        with patch.object(generator, "_generate_chapter_content", return_value=None) as mock_generate:
            success = generator._process_single_chapter(1)

        assert success is False
        assert mock_generate.call_count == 2

    def test_process_single_chapter_explicit_max_retries_overrides_config(
        self, generator
    ):
        """显式传入 max_retries 时应覆盖配置值"""
        generator.config.generation_config["max_retries"] = 2
        generator.config.generation_config["retry_delay"] = 0
        generator._load_outline()

        with patch.object(generator, "_generate_chapter_content", return_value=None) as mock_generate:
            success = generator._process_single_chapter(1, max_retries=4)

        assert success is False
        assert mock_generate.call_count == 4


class TestContentGeneratorChapterSave:
    """章节保存相关测试"""

    @pytest.fixture
    def generator(self, mock_config, output_dir_with_outline):
        mock_model = MagicMock()
        mock_model.model_name = "mock"
        mock_model.generate.return_value = "模拟内容"
        mock_model.embed.return_value = __import__("numpy").random.rand(128).astype("float32")
        mock_kb = MagicMock()
        mock_kb.search.return_value = []
        mock_kb.is_built = True
        mock_kb.embedding_model = MagicMock()
        mock_kb.embedding_model.model_name = "mock"
        mock_kb.reranker_config = None
        return ContentGenerator(mock_config, mock_model, mock_kb)

    def test_save_chapter_content(self, generator):
        """测试 _save_chapter_content 方法"""
        generator._load_outline()
        result = generator._save_chapter_content(1, "测试内容")
        assert result is True
        # 验证文件存在（文件名基于大纲标题）
        expected_file = os.path.join(generator.output_dir, "第1章_第1章标题.txt")
        assert os.path.exists(expected_file)
        with open(expected_file, "r", encoding="utf-8") as f:
            assert f.read() == "测试内容"

    def test_save_chapter_content_invalid_num(self, generator):
        """无效章节号应返回 False"""
        generator._load_outline()
        result = generator._save_chapter_content(999, "内容")
        assert result is False


class TestMergeAllChapters:
    """章节合并测试"""

    @pytest.fixture
    def generator(self, mock_config, output_dir_with_outline):
        mock_model = MagicMock()
        mock_model.model_name = "mock"
        mock_model.generate.return_value = "模拟内容"
        mock_model.embed.return_value = __import__("numpy").random.rand(128).astype("float32")
        mock_kb = MagicMock()
        mock_kb.search.return_value = []
        mock_kb.is_built = True
        mock_kb.embedding_model = MagicMock()
        mock_kb.embedding_model.model_name = "mock"
        mock_kb.reranker_config = None
        return ContentGenerator(mock_config, mock_model, mock_kb)

    def test_merge_all_chapters(self, generator):
        """测试合并所有章节"""
        generator._load_outline()
        # 创建章节文件
        for outline in generator.chapter_outlines:
            cleaned = generator._clean_filename(outline.title)
            filepath = os.path.join(generator.output_dir, f"第{outline.chapter_number}章_{cleaned}.txt")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"第{outline.chapter_number}章内容")

        result = generator.merge_all_chapters(output_filename="测试合并.txt")
        assert result is not None
        assert isinstance(result, list)
        assert len(result) == 1
        assert os.path.exists(result[0])
        with open(result[0], "r", encoding="utf-8") as f:
            content = f.read()
        assert "第1章内容" in content
        assert "第5章内容" in content

    def test_merge_partial_chapters(self, generator):
        """部分章节缺失时仍能合并已有章节"""
        generator._load_outline()
        # 只创建前3章
        for outline in generator.chapter_outlines[:3]:
            cleaned = generator._clean_filename(outline.title)
            filepath = os.path.join(generator.output_dir, f"第{outline.chapter_number}章_{cleaned}.txt")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"第{outline.chapter_number}章内容")

        result = generator.merge_all_chapters(output_filename="部分合并.txt")
        assert result is not None
        assert isinstance(result, list)
        assert len(result) == 1
        with open(result[0], "r", encoding="utf-8") as f:
            content = f.read()
        assert "第1章内容" in content
        assert "第3章内容" in content
        assert "第4章内容" not in content

    def test_merge_no_chapters(self, generator):
        """没有任何章节文件时返回 None"""
        generator._load_outline()
        result = generator.merge_all_chapters()
        assert result is None

    def test_merge_empty_outline(self, mock_config):
        """大纲为空时返回 None"""
        output_dir = mock_config.output_config["output_dir"]
        # 创建空 outline.json
        with open(os.path.join(output_dir, "outline.json"), "w") as f:
            json.dump([], f)
        mock_model = MagicMock()
        mock_model.model_name = "mock"
        mock_model.generate.return_value = ""
        mock_model.embed.return_value = __import__("numpy").random.rand(128).astype("float32")
        mock_kb = MagicMock()
        mock_kb.search.return_value = []
        mock_kb.is_built = True
        mock_kb.embedding_model = MagicMock()
        mock_kb.embedding_model.model_name = "mock"
        mock_kb.reranker_config = None
        gen = ContentGenerator(mock_config, mock_model, mock_kb)
        result = gen.merge_all_chapters()
        assert result is None

    def test_merge_default_filename(self, generator):
        """测试默认文件名使用小说标题"""
        generator._load_outline()
        for outline in generator.chapter_outlines[:1]:
            cleaned = generator._clean_filename(outline.title)
            filepath = os.path.join(generator.output_dir, f"第{outline.chapter_number}章_{cleaned}.txt")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write("内容")

        result = generator.merge_all_chapters()
        assert result is not None
        assert isinstance(result, list)
        assert len(result) == 1
        assert "完整版" in os.path.basename(result[0])

    def test_merge_strips_markdown_heading_in_volume(self, generator):
        """合并时读取每章后剥离首行 #(修复历史脏数据)"""
        generator._load_outline()
        for outline in generator.chapter_outlines:
            cleaned = generator._clean_filename(outline.title)
            filepath = os.path.join(generator.output_dir, f"第{outline.chapter_number}章_{cleaned}.txt")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"# 第{outline.chapter_number}章 {outline.title}\n\n正文内容")

        result = generator.merge_all_chapters(output_filename="清理测试.txt")
        assert result is not None and len(result) == 1
        with open(result[0], "r", encoding="utf-8") as f:
            content = f.read()
        # 首行不再带 #
        assert not content.lstrip().startswith("#")
        assert "第1章 第1章标题" in content
        # 章节间分隔符保留
        assert "正文内容" in content

    def test_merge_splits_when_over_threshold(self, generator):
        """总字节超过 max_volume_size_mb 时按章节边界分卷"""
        generator._load_outline()
        # 5 章 × 600 字节(中文 200 字) = 3000+ 字节;阈值 1KB → 至少 2 卷
        generator.config.output_config["max_volume_size_mb"] = 0.001  # ~1KB
        for outline in generator.chapter_outlines:
            cleaned = generator._clean_filename(outline.title)
            filepath = os.path.join(generator.output_dir, f"第{outline.chapter_number}章_{cleaned}.txt")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write("章" * 200)  # 200 中文字 = 600 字节 UTF-8

        result = generator.merge_all_chapters()
        assert result is not None
        assert len(result) >= 2
        for path in result:
            assert "_第" in os.path.basename(path) and "卷.txt" in os.path.basename(path)
            assert os.path.exists(path)

    def test_merge_below_threshold_keeps_single_file(self, generator):
        """总字节小于阈值时保留原命名,不带卷号"""
        generator._load_outline()
        generator.config.output_config["max_volume_size_mb"] = 10  # 10MB 远超内容
        for outline in generator.chapter_outlines:
            cleaned = generator._clean_filename(outline.title)
            filepath = os.path.join(generator.output_dir, f"第{outline.chapter_number}章_{cleaned}.txt")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"第{outline.chapter_number}章内容")

        result = generator.merge_all_chapters()
        assert result is not None and len(result) == 1
        # 文件名不带 _第N卷 后缀
        assert "_第" not in os.path.basename(result[0])

    def test_merge_split_disabled_when_zero(self, generator):
        """max_volume_size_mb=0 时无论多大都不分卷"""
        generator._load_outline()
        generator.config.output_config["max_volume_size_mb"] = 0
        for outline in generator.chapter_outlines:
            cleaned = generator._clean_filename(outline.title)
            filepath = os.path.join(generator.output_dir, f"第{outline.chapter_number}章_{cleaned}.txt")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write("章" * 200)

        result = generator.merge_all_chapters()
        assert result is not None and len(result) == 1


class TestStripMarkdownHeading:
    """模块级 _strip_markdown_heading 工具函数测试"""

    def test_empty_string_returns_unchanged(self):
        from src.generators.content.content_generator import _strip_markdown_heading
        assert _strip_markdown_heading("") == ""

    def test_no_hash_returns_unchanged(self):
        from src.generators.content.content_generator import _strip_markdown_heading
        text = "第19章 画展前的风声\n\n正文……"
        assert _strip_markdown_heading(text) is text  # 短路返回同一对象

    def test_single_hash_with_space(self):
        from src.generators.content.content_generator import _strip_markdown_heading
        text = "# 第19章 画展前的风声\n\n正文……"
        assert _strip_markdown_heading(text) == "第19章 画展前的风声\n\n正文……"

    def test_multiple_hashes(self):
        from src.generators.content.content_generator import _strip_markdown_heading
        text = "### 第19章 标题\n正文"
        assert _strip_markdown_heading(text) == "第19章 标题\n正文"

    def test_hash_without_space(self):
        from src.generators.content.content_generator import _strip_markdown_heading
        text = "#第19章 标题\n正文"
        assert _strip_markdown_heading(text) == "第19章 标题\n正文"

    def test_leading_whitespace_before_hash(self):
        from src.generators.content.content_generator import _strip_markdown_heading
        text = "  # 第19章 标题\n正文"
        assert _strip_markdown_heading(text) == "第19章 标题\n正文"

    def test_only_first_line_affected(self):
        from src.generators.content.content_generator import _strip_markdown_heading
        text = "# 第19章 标题\n正文里 #也保留\n# 后续不是标题"
        assert _strip_markdown_heading(text) == "第19章 标题\n正文里 #也保留\n# 后续不是标题"

    def test_single_line_no_newline(self):
        from src.generators.content.content_generator import _strip_markdown_heading
        assert _strip_markdown_heading("# 仅一行") == "仅一行"

    def test_preserves_trailing_newline(self):
        from src.generators.content.content_generator import _strip_markdown_heading
        assert _strip_markdown_heading("# 标题\n正文\n") == "标题\n正文\n"


class TestSaveChapterContent:
    """_save_chapter_content 落盘时去 # 行为测试"""

    @pytest.fixture
    def generator(self, mock_config, output_dir_with_outline):
        mock_model = MagicMock()
        mock_model.model_name = "mock"
        mock_kb = MagicMock()
        mock_kb.is_built = True
        mock_kb.embedding_model = MagicMock()
        mock_kb.embedding_model.model_name = "mock"
        mock_kb.reranker_config = None
        return ContentGenerator(mock_config, mock_model, mock_kb)

    def test_strips_leading_hash_on_write(self, generator):
        generator._load_outline()
        content = "# 第1章 废柴觉醒\n\n正文开始"
        assert generator._save_chapter_content(1, content) is True
        cleaned = generator._clean_filename(generator.chapter_outlines[0].title)
        path = os.path.join(generator.output_dir, f"第1章_{cleaned}.txt")
        with open(path, "r", encoding="utf-8") as f:
            disk = f.read()
        assert disk.startswith("第1章 废柴觉醒")
        assert not disk.startswith("#")

    def test_preserves_content_without_hash(self, generator):
        generator._load_outline()
        content = "第1章 废柴觉醒\n\n正文"
        assert generator._save_chapter_content(1, content) is True
        cleaned = generator._clean_filename(generator.chapter_outlines[0].title)
        path = os.path.join(generator.output_dir, f"第1章_{cleaned}.txt")
        with open(path, "r", encoding="utf-8") as f:
            assert f.read() == content


class TestSplitChaptersBySize:
    """_split_chapters_by_size 分卷算法测试"""

    @pytest.fixture
    def generator(self, mock_config, output_dir_with_outline):
        mock_model = MagicMock()
        mock_model.model_name = "mock"
        mock_kb = MagicMock()
        mock_kb.is_built = True
        mock_kb.embedding_model = MagicMock()
        mock_kb.embedding_model.model_name = "mock"
        mock_kb.reranker_config = None
        return ContentGenerator(mock_config, mock_model, mock_kb)

    def test_disabled_returns_single_volume(self, generator):
        parts = ["a" * 100, "b" * 100, "c" * 100]
        assert generator._split_chapters_by_size(parts, max_bytes=0) == [parts]
        assert generator._split_chapters_by_size(parts, max_bytes=-1) == [parts]

    def test_empty_parts_returns_empty(self, generator):
        assert generator._split_chapters_by_size([], max_bytes=100) == []

    def test_single_volume_under_limit(self, generator):
        parts = ["a" * 100, "b" * 100]
        # 总字节 200 + 分隔符 2 = 202,阈值 1000 → 一卷
        result = generator._split_chapters_by_size(parts, max_bytes=1000)
        assert len(result) == 1
        assert result[0] == parts

    def test_splits_on_boundary(self, generator):
        # 每章 100 字节,阈值 250 → 第3章追加会超阈值 → 拆 2 卷
        parts = ["a" * 100, "b" * 100, "c" * 100]
        result = generator._split_chapters_by_size(parts, max_bytes=250)
        assert len(result) == 2
        assert result[0] == ["a" * 100, "b" * 100]
        assert result[1] == ["c" * 100]

    def test_single_chapter_exceeds_limit(self, generator):
        # 单章自身 > 阈值时该章独占一卷,允许略超
        parts = ["a" * 500, "b" * 50]
        result = generator._split_chapters_by_size(parts, max_bytes=200)
        assert len(result) == 2
        assert result[0] == ["a" * 500]
        assert result[1] == ["b" * 50]

    def test_utf8_byte_accounting(self, generator):
        # 一个中文字符 UTF-8 占 3 字节;100 个中文字符 = 300 字节
        parts = ["甲" * 100, "乙" * 100, "丙" * 100]
        # 总字节 900 + 2*2 分隔符 = 904,阈值 700 → 两卷
        result = generator._split_chapters_by_size(parts, max_bytes=700)
        assert len(result) == 2
        # 第一卷应含 1-2 章(具体取决于分隔符累计)
        assert len(result[0]) >= 1
        assert sum(len(p.encode("utf-8")) for p in result[0]) <= 700 or len(result[0]) == 1


class TestVolumeSizeConfig:
    """max_volume_size_mb 配置默认与读取行为"""

    def test_default_when_key_absent(self, mock_config):
        # MockConfig 默认 output_config 中无 max_volume_size_mb
        assert mock_config.output_config.get("max_volume_size_mb", 2) == 2

    def test_explicit_zero_disables_split(self, mock_config):
        mock_config.output_config["max_volume_size_mb"] = 0
        assert mock_config.output_config.get("max_volume_size_mb", 2) == 0
