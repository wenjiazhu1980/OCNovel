# -*- coding: utf-8 -*-
"""[L2-5c] tools/recommend_arc_size.py CLI 测试"""

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.recommend_arc_size import main  # noqa: E402


class TestExitCodes:
    """退出码契约"""

    def test_perfect_alignment_exits_zero(self, capsys):
        rc = main(["--total-chapters", "400"])
        assert rc == 0

    def test_invalid_n_exits_two(self, capsys):
        rc = main(["--total-chapters", "0"])
        assert rc == 2
        captured = capsys.readouterr()
        assert "错误" in captured.err

    def test_negative_n_exits_two(self, capsys):
        rc = main(["--total-chapters", "-1"])
        assert rc == 2

    def test_short_alias_works(self, capsys):
        rc = main(["-n", "200"])
        assert rc == 0


class TestHumanReadableOutput:
    """人类可读输出格式"""

    def test_basic_output_contains_recommendation(self, capsys):
        main(["--total-chapters", "400"])
        out = capsys.readouterr().out
        assert "推荐 chapters_per_arc = 80" in out
        assert "K=5" in out

    def test_anchor_preview_present(self, capsys):
        main(["--total-chapters", "400"])
        out = capsys.readouterr().out
        # 三次锚点应都有预览
        assert "ch 100" in out
        assert "ch 200" in out
        assert "ch 300" in out
        assert "挫折期" in out
        assert "绝境期" in out
        assert "跌落期" in out

    def test_application_hint_present(self, capsys):
        main(["--total-chapters", "400"])
        out = capsys.readouterr().out
        assert "auto_compute" in out
        assert "chapters_per_arc" in out

    def test_show_candidates_flag_adds_table(self, capsys):
        main(["--total-chapters", "400", "--show-candidates"])
        out = capsys.readouterr().out
        assert "K 候选对比" in out
        # 应列出多个 K 候选
        for K in (5, 9, 13):
            assert f"  {K}" in out


class TestJsonOutput:
    """--json 模式输出格式"""

    def test_json_output_is_valid(self, capsys):
        main(["--total-chapters", "400", "--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["total_chapters"] == 400
        assert data["recommended_chapters_per_arc"] == 80
        assert data["alignment_score"] == 3
        assert isinstance(data["anchors"], list) and len(data["anchors"]) == 3

    def test_json_anchors_have_phase_info(self, capsys):
        main(["--total-chapters", "400", "--json"])
        data = json.loads(capsys.readouterr().out)
        # 三个锚点应分别为挫折/绝境/跌落
        anchor_phases = [a["actual_phase"] for a in data["anchors"]]
        assert anchor_phases == ["挫折", "绝境", "跌落"]
        # 期望阶段也匹配
        for a in data["anchors"]:
            assert a["expected_phase"] == a["actual_phase"]

    def test_json_mode_no_human_text(self, capsys):
        """--json 模式不应输出人类可读的"应用方式"等文本"""
        main(["--total-chapters", "400", "--json"])
        out = capsys.readouterr().out
        assert "应用方式" not in out
        assert "灾难锚点预览" not in out


class TestSpecialN:
    """特殊 N 值"""

    def test_small_n_warning_exits_one(self, capsys):
        """N=50 触发 fallback,score < 3 应退出码 1"""
        rc = main(["--total-chapters", "50"])
        assert rc == 1
        out = capsys.readouterr().out
        assert "⚠" in out

    def test_large_n_warning(self, capsys):
        """N=3500 极大 fallback"""
        rc = main(["--total-chapters", "3500"])
        # score 可能 < 3 或者刚好 = 3,只要不 crash
        assert rc in (0, 1)
