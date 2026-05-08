# -*- coding: utf-8 -*-
"""测试 _create_sync_info_prompt 截断阈值的可配置性

bug 上下文: 主人长篇连载到 145 章时遇到日志
    WARNING - 现有同步信息过长 (13813 字符)，截断到 8000
源头是硬编码 max_sync_info_len=8000 / max_story_len=30000。

修复点:
- 改为读 generation_config.sync_info_max_length / sync_story_max_length
- 默认值上调到 32000 / 60000(4×/2×),容纳长篇累积
- 类型容错:None / 非数值 / <=0 都回退到默认
"""

import logging
import os

import pytest
from unittest.mock import MagicMock

from src.generators.content.content_generator import ContentGenerator


@pytest.fixture
def mock_kb():
    kb = MagicMock()
    kb.search.return_value = []
    kb.is_built = False
    kb.embedding_model = MagicMock()
    kb.embedding_model.model_name = "mock"
    kb.reranker_config = None
    return kb


@pytest.fixture
def mock_model():
    m = MagicMock()
    m.model_name = "mock"
    m.generate.return_value = "ok"
    return m


@pytest.fixture
def gen(mock_config, mock_model, mock_kb):
    g = ContentGenerator(mock_config, mock_model, mock_kb)
    g.current_chapter = 1
    return g


def _write_sync_file(gen, content: str):
    """把指定内容写入 sync_info_file,模拟历史累积"""
    os.makedirs(os.path.dirname(gen.sync_info_file), exist_ok=True)
    with open(gen.sync_info_file, "w", encoding="utf-8") as f:
        f.write(content)


class TestDefaultLimits:
    """默认值生效"""

    def test_default_sync_info_limit_32000(self, gen, caplog):
        """未配置时 sync_info 默认上限 32000(原硬编码 8000 应失效)"""
        # 写 30000 字符,在新默认 32000 内,不应触发截断
        _write_sync_file(gen, "X" * 30000)
        with caplog.at_level(logging.WARNING):
            gen._create_sync_info_prompt(story_content="ok")
        sync_warns = [r for r in caplog.records if "现有同步信息过长" in r.getMessage()]
        assert sync_warns == [], "30000 字符不应触发新默认 32000 的截断"

    def test_default_story_limit_60000(self, gen, caplog):
        """未配置时 story 默认上限 60000(原硬编码 30000 应失效)"""
        _write_sync_file(gen, "x")  # sync_info 短,聚焦 story
        with caplog.at_level(logging.WARNING):
            gen._create_sync_info_prompt(story_content="Y" * 50000)
        story_warns = [r for r in caplog.records if "故事内容过长" in r.getMessage()]
        assert story_warns == [], "50000 字符不应触发新默认 60000 的截断"


class TestCustomLimitsFromConfig:
    """generation_config 字段可覆盖默认"""

    def test_custom_sync_info_limit(self, gen, caplog):
        """配置 sync_info_max_length=64000 后,允许 50000 字符不截断"""
        gen.config.generation_config["sync_info_max_length"] = 64000
        _write_sync_file(gen, "X" * 50000)
        with caplog.at_level(logging.WARNING):
            gen._create_sync_info_prompt(story_content="ok")
        sync_warns = [r for r in caplog.records if "现有同步信息过长" in r.getMessage()]
        assert sync_warns == []

    def test_lower_custom_limit_triggers_truncation(self, gen, caplog):
        """主动降低限制到 5000 → 13813 字符必然触发"""
        gen.config.generation_config["sync_info_max_length"] = 5000
        _write_sync_file(gen, "X" * 13813)
        with caplog.at_level(logging.WARNING):
            gen._create_sync_info_prompt(story_content="ok")
        sync_warns = [r.getMessage() for r in caplog.records if "现有同步信息过长" in r.getMessage()]
        assert len(sync_warns) == 1
        assert "13813" in sync_warns[0]
        assert "5000" in sync_warns[0]


class TestTypeCoercion:
    """字段为非法类型时回退默认值"""

    @pytest.mark.parametrize("bad_value", [None, "abc", -1, 0, [], {}])
    def test_invalid_value_falls_back_to_default(self, gen, caplog, bad_value):
        """sync_info_max_length 为非法值时 → 走默认 32000"""
        gen.config.generation_config["sync_info_max_length"] = bad_value
        _write_sync_file(gen, "X" * 31000)  # 31000 < 默认 32000,不应截断
        with caplog.at_level(logging.WARNING):
            gen._create_sync_info_prompt(story_content="ok")
        sync_warns = [r for r in caplog.records if "现有同步信息过长" in r.getMessage()]
        assert sync_warns == [], f"非法值 {bad_value!r} 应回退到默认 32000"


class TestRegressionOriginalBug:
    """[回归] 主人 145 章场景:13813 字符同步信息不应再被截断"""

    def test_real_world_145_chapter_no_truncation(self, gen, caplog):
        _write_sync_file(gen, "X" * 13813)
        with caplog.at_level(logging.WARNING):
            gen._create_sync_info_prompt(story_content="real story")
        msgs = [r.getMessage() for r in caplog.records]
        # 关键断言:复刻日志中的 WARNING 不再出现
        assert not any("13813" in m and "8000" in m for m in msgs), (
            "原 bug 复刻:13813 字符不应被截断到 8000"
        )
