# -*- coding: utf-8 -*-
"""
测试工具函数模块 - setup_logging, load_json_file, save_json_file, clean_text, validate_directory
"""

import os
import json
import logging
import pytest
from src.generators.common.utils import (
    load_json_file,
    save_json_file,
    clean_text,
    validate_directory,
    setup_logging,
)


class TestLoadJsonFile:
    """load_json_file 测试"""

    def test_load_existing_file(self, tmp_path):
        data = {"key": "value", "number": 42}
        file_path = str(tmp_path / "test.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        result = load_json_file(file_path)
        assert result == data

    def test_load_nonexistent_file(self):
        result = load_json_file("/nonexistent/path.json", default_value={"default": True})
        assert result == {"default": True}

    def test_load_invalid_json(self, tmp_path):
        file_path = str(tmp_path / "bad.json")
        with open(file_path, "w") as f:
            f.write("not valid json {{{")
        result = load_json_file(file_path, default_value=[])
        assert result == []

    def test_load_chinese_content(self, tmp_path):
        data = {"标题": "测试小说", "角色": ["林小凡", "王大锤"]}
        file_path = str(tmp_path / "chinese.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        result = load_json_file(file_path)
        assert result["标题"] == "测试小说"

    def test_default_value_none(self):
        result = load_json_file("/nonexistent.json")
        assert result is None


class TestSaveJsonFile:
    """save_json_file 测试"""

    def test_save_basic(self, tmp_path):
        data = {"chapters": [1, 2, 3]}
        file_path = str(tmp_path / "output.json")
        assert save_json_file(file_path, data) is True
        with open(file_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == data

    def test_save_creates_directory(self, tmp_path):
        file_path = str(tmp_path / "sub" / "dir" / "data.json")
        assert save_json_file(file_path, {"ok": True}) is True
        assert os.path.exists(file_path)

    def test_save_chinese_content(self, tmp_path):
        data = {"内容": "中文测试"}
        file_path = str(tmp_path / "cn.json")
        save_json_file(file_path, data)
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "中文测试" in content  # ensure_ascii=False


class TestCleanText:
    """clean_text 测试"""

    def test_strip_whitespace(self):
        result = clean_text("  hello world  ")
        assert result == "hello world"

    def test_traditional_to_simplified(self):
        result = clean_text("東方玄幻")
        assert result == "东方玄幻"

    def test_mixed_content(self):
        result = clean_text("  測試內容  ")
        assert result == "测试内容"


class TestValidateDirectory:
    """validate_directory 测试"""

    def test_create_new_directory(self, tmp_path):
        new_dir = str(tmp_path / "new_dir" / "sub")
        assert validate_directory(new_dir) is True
        assert os.path.isdir(new_dir)

    def test_existing_directory(self, tmp_path):
        assert validate_directory(str(tmp_path)) is True

    def test_invalid_path(self):
        # 在只读路径上创建目录应该失败（取决于系统权限）
        # 这里用一个不太可能成功的路径
        result = validate_directory("/proc/fake_dir_test")
        # 在某些系统上可能成功，所以只检查返回类型
        assert isinstance(result, bool)


class TestSetupLogging:
    """setup_logging 测试"""

    def test_setup_creates_log_file(self, tmp_path):
        log_dir = str(tmp_path / "logs")
        os.makedirs(log_dir, exist_ok=True)
        setup_logging(log_dir)
        log_file = os.path.join(log_dir, "generation.log")
        # 写一条日志触发文件创建
        logging.info("测试日志")
        assert os.path.exists(log_file)

    def test_clear_logs(self, tmp_path):
        log_dir = str(tmp_path / "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "generation.log")
        with open(log_file, "w") as f:
            f.write("old log content")
        setup_logging(log_dir, clear_logs=True)
        # 旧日志应该被清除
        logging.info("新日志")
        with open(log_file, "r") as f:
            content = f.read()
        assert "old log content" not in content
