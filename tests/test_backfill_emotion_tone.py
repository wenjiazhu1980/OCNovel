# -*- coding: utf-8 -*-
"""[P1] tools/backfill_emotion_tone.py 测试

测试两层:
1. 纯函数 backfill_outline_emotion_tone(outline_data, chapters_per_arc, suffix)
   - 全空 → 全部回填
   - 部分已有 → 仅填空
   - chapter_number 缺失 / 非 int → 跳过
   - chapters_per_arc <= 0 → 全跳过(配置异常)
   - None / 非 dict 槽位保留(稀疏列表语义)
   - 占位后缀生效
   - 不污染原列表(浅拷贝)

2. CLI main() 入口
   - --dry-run 不写盘
   - 写盘前自动备份
   - --no-backup 跳过备份
   - 退出码: 0=成功 / 2=参数or文件错误 / 3=写盘错误
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# 注入项目根
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.backfill_emotion_tone import (  # noqa: E402
    backfill_outline_emotion_tone,
    main,
)


def _make_outline_chapter(num: int, emotion_tone: str = "") -> dict:
    """构造一条 outline.json 风格的章节字典"""
    return {
        "chapter_number": num,
        "title": f"第{num}章",
        "key_points": ["要点"],
        "characters": ["主角"],
        "settings": ["场景"],
        "conflicts": ["冲突"],
        "emotion_tone": emotion_tone,
        "character_goals": {},
        "scene_sequence": [],
        "foreshadowing": [],
        "pov_character": "",
    }


# ---------------------------------------------------------------------------
# 纯函数测试
# ---------------------------------------------------------------------------

class TestBackfillPureFunction:

    def test_all_empty_filled_with_phase_names(self):
        """40 章全空 → 全部按卷内位置填上对应阶段名"""
        outlines = [_make_outline_chapter(i) for i in range(1, 41)]
        result, stats = backfill_outline_emotion_tone(outlines, chapters_per_arc=40)

        assert stats["total"] == 40
        assert stats["filled"] == 40
        assert stats["already_set"] == 0

        # 第 1 章在成长期
        assert "成长" in result[0]["emotion_tone"]
        # 第 10 章 (arc_pct=0.25 > 0.23) 进入挫折期
        assert "挫折" in result[9]["emotion_tone"]
        # 第 40 章 (arc_pct=1.0) 在新局
        assert "新局" in result[39]["emotion_tone"]

    def test_already_set_preserved(self):
        """原有非空 emotion_tone 必须原样保留(即使是 LLM 写的奇怪值)"""
        outlines = [
            _make_outline_chapter(1, emotion_tone="LLM 自定义节奏"),
            _make_outline_chapter(2),  # 空
            _make_outline_chapter(3, emotion_tone="紧张→释然"),
        ]
        result, stats = backfill_outline_emotion_tone(outlines, chapters_per_arc=40)

        assert result[0]["emotion_tone"] == "LLM 自定义节奏"
        assert result[2]["emotion_tone"] == "紧张→释然"
        # 只有第 2 章被填
        assert "成长" in result[1]["emotion_tone"]
        assert stats["already_set"] == 2
        assert stats["filled"] == 1

    def test_whitespace_only_treated_as_empty(self):
        """仅含空白的 emotion_tone 视为空,会被回填"""
        outlines = [_make_outline_chapter(1, emotion_tone="   \t\n")]
        result, stats = backfill_outline_emotion_tone(outlines, chapters_per_arc=40)
        assert stats["filled"] == 1
        assert "成长" in result[0]["emotion_tone"]

    def test_placeholder_suffix_default(self):
        """默认占位后缀为「（自动回填）」便于人工审核辨识"""
        outlines = [_make_outline_chapter(1)]
        result, _ = backfill_outline_emotion_tone(outlines, chapters_per_arc=40)
        assert result[0]["emotion_tone"] == "成长（自动回填）"

    def test_empty_suffix_uses_pure_phase_name(self):
        """传空字符串时只填阶段名,不带后缀"""
        outlines = [_make_outline_chapter(1)]
        result, _ = backfill_outline_emotion_tone(
            outlines, chapters_per_arc=40, placeholder_suffix=""
        )
        assert result[0]["emotion_tone"] == "成长"

    def test_custom_suffix(self):
        """自定义后缀生效"""
        outlines = [_make_outline_chapter(1)]
        result, _ = backfill_outline_emotion_tone(
            outlines, chapters_per_arc=40, placeholder_suffix="[backfill]"
        )
        assert result[0]["emotion_tone"] == "成长[backfill]"

    def test_invalid_chapter_number_skipped(self):
        """chapter_number 缺失/非 int 的条目被跳过计数"""
        outlines = [
            {"title": "无 chapter_number", "emotion_tone": ""},  # 缺字段
            {"chapter_number": "abc", "emotion_tone": ""},        # 类型错
            _make_outline_chapter(3),                             # 正常
        ]
        result, stats = backfill_outline_emotion_tone(outlines, chapters_per_arc=40)
        assert stats["skipped_no_chapter_num"] == 2
        assert stats["filled"] == 1
        # 异常条目原样保留(浅拷贝)
        assert result[0]["emotion_tone"] == ""
        assert result[1]["emotion_tone"] == ""

    def test_chapters_per_arc_zero_skips_all(self):
        """chapters_per_arc=0 视为未配置卷长,函数全跳过并在 stats 标记"""
        outlines = [_make_outline_chapter(i) for i in range(1, 5)]
        result, stats = backfill_outline_emotion_tone(outlines, chapters_per_arc=0)
        assert stats["filled"] == 0
        assert stats["skipped_no_arc"] == 4
        # 原值不变
        for ch in result:
            assert ch["emotion_tone"] == ""

    def test_negative_chapters_per_arc_skips_all(self):
        outlines = [_make_outline_chapter(1)]
        _, stats = backfill_outline_emotion_tone(outlines, chapters_per_arc=-5)
        assert stats["filled"] == 0
        assert stats["skipped_no_arc"] == 1

    def test_none_slot_preserved(self):
        """outline.json 中的 None 槽位(稀疏列表)被原样保留并计入 sparse_none"""
        outlines = [_make_outline_chapter(1), None, _make_outline_chapter(3)]
        result, stats = backfill_outline_emotion_tone(outlines, chapters_per_arc=40)
        assert result[1] is None
        assert stats["sparse_none"] == 1
        assert stats["filled"] == 2

    def test_non_dict_item_preserved(self):
        """非 dict 杂项(如脏数据)原样保留,不抛异常"""
        outlines = [_make_outline_chapter(1), "脏数据", 42, _make_outline_chapter(4)]
        result, stats = backfill_outline_emotion_tone(outlines, chapters_per_arc=40)
        assert result[1] == "脏数据"
        assert result[2] == 42
        assert stats["sparse_none"] == 2

    def test_no_mutation_of_input(self):
        """函数不污染调用方的原列表/原字典"""
        original = [_make_outline_chapter(1)]
        original_snapshot = json.dumps(original, ensure_ascii=False)

        backfill_outline_emotion_tone(original, chapters_per_arc=40)

        # 原列表/原字典不变
        assert json.dumps(original, ensure_ascii=False) == original_snapshot

    def test_cross_arc_progression_reset(self):
        """跨卷时阶段重置(80 章 = 卷2末 = 新局; 81 章 = 卷3首 = 成长)"""
        outlines = [_make_outline_chapter(80), _make_outline_chapter(81)]
        result, _ = backfill_outline_emotion_tone(outlines, chapters_per_arc=40)
        assert "新局" in result[0]["emotion_tone"]
        assert "成长" in result[1]["emotion_tone"]


# ---------------------------------------------------------------------------
# CLI main() 测试
# ---------------------------------------------------------------------------

class TestBackfillCLI:

    @pytest.fixture
    def output_dir(self, tmp_path):
        d = tmp_path / "output"
        d.mkdir()
        return d

    @pytest.fixture
    def outline_file(self, output_dir):
        path = output_dir / "outline.json"
        data = [_make_outline_chapter(i) for i in range(1, 11)]
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def test_basic_backfill_writes_file_and_returns_zero(self, output_dir, outline_file):
        """正常调用:回填 + 写盘 + 退出 0"""
        rc = main([
            "--output-dir", str(output_dir),
            "--chapters-per-arc", "40",
        ])
        assert rc == 0

        with outline_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
        # 全部章节都被填了
        for ch in data:
            assert ch["emotion_tone"]
            assert "（自动回填）" in ch["emotion_tone"]

    def test_dry_run_does_not_write(self, output_dir, outline_file):
        """--dry-run 不修改原文件"""
        original = outline_file.read_text(encoding="utf-8")
        rc = main([
            "--output-dir", str(output_dir),
            "--chapters-per-arc", "40",
            "--dry-run",
        ])
        assert rc == 0
        assert outline_file.read_text(encoding="utf-8") == original

    def test_backup_created_by_default(self, output_dir, outline_file):
        """默认会创建 .bak.<timestamp>.json 备份"""
        rc = main([
            "--output-dir", str(output_dir),
            "--chapters-per-arc", "40",
        ])
        assert rc == 0
        backups = list(output_dir.glob("outline.bak.*.json"))
        assert len(backups) == 1, f"应有 1 个备份文件,实际 {backups}"

    def test_no_backup_flag_skips_backup(self, output_dir, outline_file):
        """--no-backup 不创建备份"""
        rc = main([
            "--output-dir", str(output_dir),
            "--chapters-per-arc", "40",
            "--no-backup",
        ])
        assert rc == 0
        backups = list(output_dir.glob("outline.bak.*.json"))
        assert backups == []

    def test_missing_outline_returns_2(self, tmp_path):
        """outline.json 不存在 → 退出码 2"""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        rc = main([
            "--output-dir", str(empty_dir),
            "--chapters-per-arc", "40",
        ])
        assert rc == 2

    def test_invalid_json_returns_2(self, output_dir):
        """outline.json 是非法 JSON → 退出码 2"""
        (output_dir / "outline.json").write_text("not valid json {", encoding="utf-8")
        rc = main([
            "--output-dir", str(output_dir),
            "--chapters-per-arc", "40",
        ])
        assert rc == 2

    def test_zero_chapters_per_arc_returns_2(self, output_dir, outline_file):
        """chapters_per_arc <= 0 → 退出码 2(参数错误)"""
        rc = main([
            "--output-dir", str(output_dir),
            "--chapters-per-arc", "0",
        ])
        assert rc == 2

    def test_no_changes_no_write_no_backup(self, output_dir):
        """所有章节都已填了 → 不写盘也不备份"""
        path = output_dir / "outline.json"
        data = [_make_outline_chapter(i, emotion_tone="已有") for i in range(1, 5)]
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        mtime_before = path.stat().st_mtime_ns

        rc = main([
            "--output-dir", str(output_dir),
            "--chapters-per-arc", "40",
        ])
        assert rc == 0
        # 没产生备份(因为没有改动)
        assert list(output_dir.glob("outline.bak.*.json")) == []
        # 文件未被改写(mtime 不变)
        assert path.stat().st_mtime_ns == mtime_before

    def test_dict_wrapped_outline_format_supported(self, output_dir):
        """支持旧格式 {"chapters": [...], "title": "..."}"""
        path = output_dir / "outline.json"
        wrapped = {
            "title": "测试小说",
            "chapters": [_make_outline_chapter(i) for i in range(1, 6)],
        }
        path.write_text(json.dumps(wrapped, ensure_ascii=False), encoding="utf-8")

        rc = main([
            "--output-dir", str(output_dir),
            "--chapters-per-arc", "40",
        ])
        assert rc == 0

        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        # 顶层结构应保持 dict 包装
        assert isinstance(data, dict)
        assert data["title"] == "测试小说"
        # 内部章节被回填
        for ch in data["chapters"]:
            assert ch["emotion_tone"]

    def test_partial_backfill_preserves_non_empty(self, output_dir):
        """部分章节已有非空 emotion_tone,仅填空的章节"""
        path = output_dir / "outline.json"
        data = [
            _make_outline_chapter(1, emotion_tone="原创节奏"),
            _make_outline_chapter(2),
            _make_outline_chapter(3, emotion_tone="另一原创"),
        ]
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        rc = main([
            "--output-dir", str(output_dir),
            "--chapters-per-arc", "40",
        ])
        assert rc == 0

        with path.open("r", encoding="utf-8") as f:
            saved = json.load(f)
        assert saved[0]["emotion_tone"] == "原创节奏"
        assert "成长" in saved[1]["emotion_tone"]
        assert saved[2]["emotion_tone"] == "另一原创"
