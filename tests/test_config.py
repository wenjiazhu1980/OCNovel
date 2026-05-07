# -*- coding: utf-8 -*-
"""
测试配置模块 - Config, AIConfig, _sanitize_config_for_logging
"""

import os
import json
import pytest
from unittest.mock import patch, MagicMock
from src.config.config import Config, _sanitize_config_for_logging


class TestSanitizeConfigForLogging:
    """_sanitize_config_for_logging 测试"""

    def test_sanitize_api_key(self):
        config = {"api_key": "sk-1234567890abcdef"}
        result = _sanitize_config_for_logging(config)
        assert result["api_key"] == "sk-1****cdef"

    def test_sanitize_short_key(self):
        config = {"api_key": "short"}
        result = _sanitize_config_for_logging(config)
        assert result["api_key"] == "****"

    def test_sanitize_empty_key(self):
        config = {"api_key": ""}
        result = _sanitize_config_for_logging(config)
        assert result["api_key"] == "未设置"

    def test_sanitize_nested(self):
        config = {"model": {"api_key": "sk-1234567890abcdef", "name": "gpt-4"}}
        result = _sanitize_config_for_logging(config)
        assert "****" in result["model"]["api_key"]
        assert result["model"]["name"] == "gpt-4"

    def test_sanitize_non_sensitive(self):
        config = {"model_name": "gpt-4", "temperature": 0.7}
        result = _sanitize_config_for_logging(config)
        assert result["model_name"] == "gpt-4"
        assert result["temperature"] == 0.7

    def test_sanitize_non_dict(self):
        assert _sanitize_config_for_logging("not a dict") == "not a dict"
        assert _sanitize_config_for_logging(42) == 42

    def test_sanitize_fallback_api_key(self):
        config = {"fallback_api_key": "abcdefghijklmnop"}
        result = _sanitize_config_for_logging(config)
        assert "****" in result["fallback_api_key"]

    def test_sanitize_password(self):
        config = {"password": "mysecretpassword123"}
        result = _sanitize_config_for_logging(config)
        assert "****" in result["password"]


class TestConfig:
    """Config 类测试（需要 config.json 文件）"""

    @pytest.fixture
    def minimal_config_file(self, tmp_path):
        """创建最小化的配置文件"""
        config = {
            "novel_config": {
                "type": "玄幻",
                "theme": "修真",
                "target_chapters": 10,
                "chapter_length": 3000,
                "writing_guide": {
                    "world_building": {},
                    "character_guide": {"protagonist": {}},
                    "plot_structure": {},
                    "style_guide": {},
                },
            },
            "generation_config": {
                "max_retries": 3,
                "retry_delay": 10,
                "validation": {"enabled": False},
            },
            "output_config": {"output_dir": str(tmp_path / "output")},
            "knowledge_base_config": {
                "cache_dir": str(tmp_path / "cache"),
                "chunk_size": 500,
                "chunk_overlap": 50,
                "reference_files": [],
            },
            "model_config": {
                "outline_model": {"type": "openai", "api_key": "test", "model_name": "test", "base_url": "http://test"},
                "content_model": {"type": "openai", "api_key": "test", "model_name": "test", "base_url": "http://test"},
                "embedding_model": {"type": "openai", "api_key": "test", "model_name": "test", "base_url": "http://test"},
            },
        }
        config_file = str(tmp_path / "config.json")
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False)
        # 创建 .env 文件
        env_file = str(tmp_path / ".env")
        with open(env_file, "w") as f:
            f.write("OPENAI_EMBEDDING_API_KEY=test-key\n")
            f.write("OPENAI_EMBEDDING_API_BASE=http://test\n")
        return config_file

    def test_config_load(self, minimal_config_file):
        config = Config(minimal_config_file)
        assert config.novel_config["type"] == "玄幻"
        assert config.novel_config["target_chapters"] == 10

    def test_get_model_config(self, minimal_config_file):
        config = Config(minimal_config_file)
        model_config = config.get_model_config("outline_model")
        assert model_config["type"] == "openai"

    def test_get_model_config_invalid(self, minimal_config_file):
        config = Config(minimal_config_file)
        with pytest.raises(ValueError):
            config.get_model_config("nonexistent_model")

    def test_get_writing_guide(self, minimal_config_file):
        config = Config(minimal_config_file)
        guide = config.get_writing_guide()
        assert isinstance(guide, dict)
        assert "world_building" in guide

    def test_getattr_fallback(self, minimal_config_file):
        config = Config(minimal_config_file)
        # 应该能通过 __getattr__ 访问 config 中的键
        assert config.generation_config is not None

    def test_getattr_missing(self, minimal_config_file):
        config = Config(minimal_config_file)
        with pytest.raises(AttributeError):
            _ = config.nonexistent_attribute

    def test_config_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            Config("/nonexistent/config.json")
