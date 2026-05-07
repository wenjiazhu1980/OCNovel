# -*- coding: utf-8 -*-
"""[5.2] load_outline_chapter_data 稀疏大纲读取测试

替代 chapters_list[chapter_num - 1] 位置访问,确保稀疏/乱序大纲场景正确性。
"""

import os
import json
import pytest
from src.generators.common.utils import load_outline_chapter_data


def _write_outline(output_dir: str, data):
    """便捷写入 outline.json"""
    path = os.path.join(output_dir, "outline.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return path


class TestLoadOutlineChapterData:
    def test_dict_format_compact_list(self, tmp_path):
        """顶层 dict + 紧凑 chapters 列表"""
        _write_outline(str(tmp_path), {
            "chapters": [
                {"chapter_number": 1, "title": "第一章"},
                {"chapter_number": 2, "title": "第二章"},
                {"chapter_number": 3, "title": "第三章"},
            ]
        })
        result = load_outline_chapter_data(str(tmp_path), 2)
        assert result is not None
        assert result["title"] == "第二章"

    def test_list_format_top_level(self, tmp_path):
        """顶层 list 格式"""
        _write_outline(str(tmp_path), [
            {"chapter_number": 1, "title": "C1"},
            {"chapter_number": 2, "title": "C2"},
        ])
        result = load_outline_chapter_data(str(tmp_path), 1)
        assert result["title"] == "C1"

    def test_sparse_with_none_placeholders(self, tmp_path):
        """稀疏大纲(含 None 占位): 按 chapter_number 精确匹配,不受位置影响"""
        _write_outline(str(tmp_path), [
            {"chapter_number": 1, "title": "第一章"},
            None,
            None,
            {"chapter_number": 4, "title": "第四章"},
        ])
        # 旧逻辑 chapters_list[chapter_num - 1] 会读到 None 或越界
        result = load_outline_chapter_data(str(tmp_path), 4)
        assert result is not None
        assert result["title"] == "第四章"

    def test_out_of_order_chapters(self, tmp_path):
        """乱序大纲: 即使顺序颠倒也能按编号查找"""
        _write_outline(str(tmp_path), [
            {"chapter_number": 3, "title": "三"},
            {"chapter_number": 1, "title": "一"},
            {"chapter_number": 2, "title": "二"},
        ])
        # 旧位置访问会得到错误章节
        assert load_outline_chapter_data(str(tmp_path), 1)["title"] == "一"
        assert load_outline_chapter_data(str(tmp_path), 2)["title"] == "二"
        assert load_outline_chapter_data(str(tmp_path), 3)["title"] == "三"

    def test_chapter_not_found(self, tmp_path):
        """章节号不存在 → None"""
        _write_outline(str(tmp_path), [{"chapter_number": 1, "title": "唯一"}])
        assert load_outline_chapter_data(str(tmp_path), 99) is None

    def test_no_outline_file(self, tmp_path):
        """大纲文件不存在 → None"""
        assert load_outline_chapter_data(str(tmp_path), 1) is None

    def test_invalid_format_top_level(self, tmp_path):
        """无法识别的顶层格式 → None"""
        _write_outline(str(tmp_path), {"unexpected_key": 123})
        assert load_outline_chapter_data(str(tmp_path), 1) is None

    def test_invalid_entries_skipped(self, tmp_path):
        """非 dict 条目(None / str / int)被跳过,不影响其他章节查找"""
        _write_outline(str(tmp_path), [
            "not a dict",
            None,
            123,
            {"chapter_number": 5, "title": "第五章"},
        ])
        result = load_outline_chapter_data(str(tmp_path), 5)
        assert result is not None
        assert result["title"] == "第五章"
