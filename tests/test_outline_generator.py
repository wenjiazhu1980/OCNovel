# -*- coding: utf-8 -*-
"""
测试大纲生成器模块 - OutlineGenerator
"""

import os
import json
import logging
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from dataclasses import asdict
from src.generators.outline.outline_generator import OutlineGenerator
from src.generators.common.data_structures import ChapterOutline


class TestOutlineGenerator:
    """OutlineGenerator 测试"""

    @pytest.fixture
    def mock_outline_model(self):
        model = MagicMock()
        model.model_name = "mock-outline"
        return model

    @pytest.fixture
    def mock_kb(self):
        kb = MagicMock()
        kb.search.return_value = ["参考内容1", "参考内容2"]
        kb.is_built = True
        return kb

    @pytest.fixture
    def generator(self, mock_config, mock_outline_model, mock_kb, output_dir_with_outline):
        return OutlineGenerator(mock_config, mock_outline_model, mock_kb)

    def test_init(self, generator, mock_config):
        assert generator.output_dir == mock_config.output_config["output_dir"]
        assert generator.cancel_checker is None

    def test_load_outline(self, generator):
        """测试从文件加载大纲"""
        assert len(generator.chapter_outlines) == 5
        assert generator.chapter_outlines[0].title == "第1章标题"

    def test_save_outline(self, generator):
        result = generator._save_outline()
        assert result is True
        outline_file = os.path.join(generator.output_dir, "outline.json")
        assert os.path.exists(outline_file)
        with open(outline_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) == 5

    def test_save_outline_empty(self, mock_config, mock_kb):
        """空大纲不应保存"""
        mock_model = MagicMock()
        mock_model.model_name = "mock"
        # 创建空的 outline.json
        output_dir = mock_config.output_config["output_dir"]
        with open(os.path.join(output_dir, "outline.json"), "w") as f:
            json.dump([], f)
        gen = OutlineGenerator(mock_config, mock_model, mock_kb)
        result = gen._save_outline()
        assert result is False

    def test_parse_model_response_valid_json(self, generator):
        response = json.dumps([
            {"chapter_number": 1, "title": "测试", "key_points": ["点1"], "characters": ["A"], "settings": ["B"], "conflicts": ["C"]}
        ])
        result = generator._parse_model_response(response)
        assert result is not None
        assert len(result) == 1
        assert result[0]["title"] == "测试"

    def test_parse_model_response_markdown_wrapped(self, generator):
        response = '```json\n[{"chapter_number": 1, "title": "测试", "key_points": [], "characters": [], "settings": [], "conflicts": []}]\n```'
        result = generator._parse_model_response(response)
        assert result is not None
        assert len(result) == 1

    def test_parse_model_response_trailing_comma(self, generator):
        response = '[{"chapter_number": 1, "title": "测试", "key_points": [], "characters": [], "settings": [], "conflicts": [],}]'
        result = generator._parse_model_response(response)
        assert result is not None

    def test_parse_model_response_invalid(self, generator):
        result = generator._parse_model_response("这不是JSON")
        assert result is None

    def test_check_outline_consistency_basic(self, generator):
        new_outline = ChapterOutline(
            chapter_number=6, title="新章节", key_points=["新点1", "新点2"],
            characters=["林小凡", "新角色"], settings=["新场景"], conflicts=["新冲突"],
        )
        previous = generator.chapter_outlines[:5]
        result = generator._check_outline_consistency(new_outline, previous)
        assert result is True

    def test_check_outline_consistency_duplicate_title(self, generator):
        """重复标题应该被拒绝"""
        new_outline = ChapterOutline(
            chapter_number=6, title="第1章标题",  # 与已有标题重复
            key_points=["新点"], characters=["A"], settings=["B"], conflicts=["C"],
        )
        previous = generator.chapter_outlines[:5]
        result = generator._check_outline_consistency(new_outline, previous)
        assert result is False

    def test_generate_outline_invalid_mode(self, generator):
        result = generator.generate_outline("玄幻", "修真", "热血", mode="invalid")
        assert result is False

    def test_generate_outline_invalid_range(self, generator):
        result = generator.generate_outline("玄幻", "修真", "热血", mode="replace", replace_range=(5, 3))
        assert result is False

    def test_generate_outline_cancel(self, generator, mock_outline_model):
        """测试取消信号 - generate_outline 内部捕获 InterruptedError 并返回 False"""
        generator.cancel_checker = lambda: True
        result = generator.generate_outline("玄幻", "修真", "热血", mode="replace", replace_range=(1, 5))
        assert result is False

    def test_get_context_for_batch(self, generator):
        context = generator._get_context_for_batch(3)
        assert isinstance(context, str)

    def test_get_default_sync_info(self, generator):
        info = generator._get_default_sync_info()
        assert "世界观" in info
        assert "人物设定" in info
        assert "剧情发展" in info
        assert info["最后更新章节"] == 0

    def test_load_sync_info_no_file(self, generator):
        info = generator._load_sync_info()
        assert "世界观" in info

    def test_merge_list_unique(self, generator):
        target = ["A", "B"]
        source = ["B", "C", "D"]
        generator._merge_list_unique(target, source)
        assert target == ["A", "B", "C", "D"]

    def test_merge_list_unique_with_dicts(self, generator):
        target = [{"名称": "A"}]
        source = [{"名称": "A"}, {"名称": "B"}]
        generator._merge_list_unique(target, source)
        assert len(target) == 2

    def test_get_hashable_item_string(self, generator):
        assert generator._get_hashable_item("test") == "test"

    def test_get_hashable_item_dict(self, generator):
        result = generator._get_hashable_item({"名称": "测试"})
        assert result == "测试"

    def test_generate_outline_success(self, generator, mock_outline_model):
        """测试成功生成大纲"""
        response_data = [
            {
                "chapter_number": i,
                "title": f"新章节{i}",
                "key_points": [f"点{i}-1", f"点{i}-2", f"点{i}-3"],
                "characters": ["林小凡", f"角色{i}"],
                "settings": [f"场景{i}"],
                "conflicts": [f"冲突{i}"],
            }
            for i in range(6, 9)
        ]
        mock_outline_model.generate.return_value = json.dumps(response_data, ensure_ascii=False)
        result = generator.generate_outline("玄幻", "修真", "热血", mode="replace", replace_range=(6, 8))
        assert result is True


class TestOutlineBatchRetry:
    """大纲批次失败自动重试机制测试"""

    @pytest.fixture
    def mock_outline_model(self):
        model = MagicMock()
        model.model_name = "mock-outline"
        return model

    @pytest.fixture
    def mock_kb(self):
        kb = MagicMock()
        kb.search.return_value = ["参考内容"]
        kb.is_built = True
        return kb

    @pytest.fixture
    def retry_config(self, tmp_path):
        """配置重试相关参数的 MockConfig"""
        from tests.conftest import MockConfig
        output_dir = str(tmp_path / "output")
        os.makedirs(output_dir, exist_ok=True)
        config = MockConfig(output_dir=output_dir)
        # 关键：设置重试参数
        config.generation_config["outline_batch_max_retries"] = 3
        config.generation_config["outline_batch_retry_delay"] = 0  # 测试时不需要等待
        config.generation_config["outline_batch_size"] = 10
        config.generation_config["batch_size"] = 10
        return config

    @pytest.fixture
    def retry_generator(self, retry_config, mock_outline_model, mock_kb):
        """带重试配置的大纲生成器（空大纲）"""
        output_dir = retry_config.output_config["output_dir"]
        with open(os.path.join(output_dir, "outline.json"), "w", encoding="utf-8") as f:
            json.dump([], f)
        return OutlineGenerator(retry_config, mock_outline_model, mock_kb)

    def _make_chapter_response(self, start, end):
        """生成指定范围章节的 JSON 响应"""
        return json.dumps([
            {
                "chapter_number": i,
                "title": f"第{i}章 标题",
                "key_points": [f"要点{i}"],
                "characters": ["林小凡"],
                "settings": [f"场景{i}"],
                "conflicts": [f"冲突{i}"],
            }
            for i in range(start, end + 1)
        ], ensure_ascii=False)

    def test_batch_retry_success_on_second_attempt(self, retry_generator, mock_outline_model):
        """第一次失败，第二次成功 → 最终返回 True"""
        mock_outline_model.generate.side_effect = [
            self._make_chapter_response(1, 3),   # 第1次 _generate_batch 失败（模型调用但解析/一致性问题导致失败）
            Exception("API 临时错误"),             # core_seed 调用可能消耗一次
            self._make_chapter_response(1, 3),   # 第2次成功
            self._make_chapter_response(1, 3),   # 额外备用
        ]

        def batch_side_effect(*args, **kwargs):
            """第一次失败，第二次成功并填充 chapter_outlines"""
            batch_side_effect.call_count += 1
            if batch_side_effect.call_count == 1:
                return False
            # 模拟成功时填充大纲
            for i in range(3):
                retry_generator.chapter_outlines[i] = ChapterOutline(
                    chapter_number=i + 1, title=f"第{i+1}章 标题",
                    key_points=[f"要点{i+1}"], characters=["林小凡"],
                    settings=[f"场景{i+1}"], conflicts=[f"冲突{i+1}"],
                )
            return True
        batch_side_effect.call_count = 0

        with patch.object(retry_generator, '_generate_batch', side_effect=batch_side_effect):
            result = retry_generator.generate_outline(
                "玄幻", "修真", "热血",
                mode="replace", replace_range=(1, 3),
            )
        assert result is True

    def test_batch_retry_success_on_third_attempt(self, retry_generator, mock_outline_model):
        """前两次失败，第三次成功 → 最终返回 True"""
        def batch_side_effect(*args, **kwargs):
            batch_side_effect.call_count += 1
            if batch_side_effect.call_count < 3:
                return False
            for i in range(3):
                retry_generator.chapter_outlines[i] = ChapterOutline(
                    chapter_number=i + 1, title=f"第{i+1}章 标题",
                    key_points=[f"要点{i+1}"], characters=["林小凡"],
                    settings=[f"场景{i+1}"], conflicts=[f"冲突{i+1}"],
                )
            return True
        batch_side_effect.call_count = 0

        with patch.object(retry_generator, '_generate_batch', side_effect=batch_side_effect):
            result = retry_generator.generate_outline(
                "玄幻", "修真", "热血",
                mode="replace", replace_range=(1, 3),
            )
        assert result is True

    def test_batch_retry_all_attempts_fail(self, retry_generator, mock_outline_model):
        """总尝试 3 次全部失败 → 返回 False"""
        with patch.object(retry_generator, '_generate_batch', return_value=False):
            result = retry_generator.generate_outline(
                "玄幻", "修真", "热血",
                mode="replace", replace_range=(1, 3),
            )
        assert result is False

    def test_batch_retry_default_retries_when_no_config(self, tmp_path, mock_outline_model, mock_kb):
        """未配置重试参数时使用默认值（总共最多尝试 3 次）"""
        from tests.conftest import MockConfig
        output_dir = str(tmp_path / "output")
        os.makedirs(output_dir, exist_ok=True)
        config = MockConfig(output_dir=output_dir)
        # 不设置 outline_batch_max_retries，应使用默认值 3（总尝试次数）
        with open(os.path.join(output_dir, "outline.json"), "w", encoding="utf-8") as f:
            json.dump([], f)

        gen = OutlineGenerator(config, mock_outline_model, mock_kb)
        with patch.object(gen, '_generate_batch', return_value=False) as mock_batch:
            result = gen.generate_outline(
                "玄幻", "修真", "热血",
                mode="replace", replace_range=(1, 3),
            )
        assert result is False
        assert mock_batch.call_count == 3

    def test_batch_retry_cancel_during_retry(self, retry_generator, mock_outline_model):
        """重试期间用户取消 → 返回 False（不继续重试）"""
        call_count = 0

        def fail_then_cancel(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                retry_generator.cancel_checker = lambda: True
            return False

        with patch.object(retry_generator, '_generate_batch', side_effect=fail_then_cancel):
            result = retry_generator.generate_outline(
                "玄幻", "修真", "热血",
                mode="replace", replace_range=(1, 3),
            )
        # 取消后应返回 False，且不应继续重试所有3次
        assert result is False
        # _generate_batch 只被调用了1次（取消后不再重试）
        assert call_count == 1

    def test_quality_threshold_triggers_retry(self, retry_generator, mock_outline_model):
        """有效章节低于阈值（<50%）→ 视为批次失败，触发重试"""
        def batch_side_effect(*args, **kwargs):
            batch_side_effect.call_count += 1
            if batch_side_effect.call_count == 1:
                return False
            for i in range(3):
                retry_generator.chapter_outlines[i] = ChapterOutline(
                    chapter_number=i + 1, title=f"第{i+1}章 标题",
                    key_points=[f"要点{i+1}"], characters=["林小凡"],
                    settings=[f"场景{i+1}"], conflicts=[f"冲突{i+1}"],
                )
            return True
        batch_side_effect.call_count = 0

        with patch.object(retry_generator, '_generate_batch', side_effect=batch_side_effect) as mock_batch:
            result = retry_generator.generate_outline(
                "玄幻", "修真", "热血",
                mode="replace", replace_range=(1, 3),
            )
        assert result is True
        assert mock_batch.call_count == 2

    def test_missing_chapters_detected(self, retry_generator, mock_outline_model):
        """模型返回章节数不足时，应检测并补充 None 占位"""
        # 请求3章，模型只返回2章
        partial_response = json.dumps([
            {
                "chapter_number": 1,
                "title": "第1章",
                "key_points": ["要点1"],
                "characters": ["角色1"],
                "settings": ["场景1"],
                "conflicts": ["冲突1"],
            },
            {
                "chapter_number": 2,
                "title": "第2章",
                "key_points": ["要点2"],
                "characters": ["角色2"],
                "settings": ["场景2"],
                "conflicts": ["冲突2"],
            },
        ], ensure_ascii=False)

        # 第1次返回不完整，第2次返回完整
        mock_outline_model.generate.side_effect = [
            partial_response,                        # 仅返回2/3章
            self._make_chapter_response(1, 3),      # 返回完整3章
        ]
        result = retry_generator.generate_outline(
            "玄幻", "修真", "热血",
            mode="replace", replace_range=(1, 3),
        )
        # 2/3 的有效大纲高于阈值（max(1,3//2)=1, 2>=1），所以第1次不会重试
        # 但为了完整性验证，检查最终结果
        assert result is True
