# -*- coding: utf-8 -*-
"""[L2-5a] compute_optimal_chapters_per_arc 纯函数测试

覆盖维度:
1. 边界:N <= 0 / 极小 / 极大
2. 对齐质量:典型 N 值的 score=3 完美对齐验证
3. 算法保证:返回 M 必然落在 [ARC_M_MIN, ARC_M_MAX] 或带 fallback warning
4. K 选择策略:同等对齐质量优先 K 小
5. 与 EMOTION_PHASES 的契约一致性
"""

import re

import pytest
from src.generators.prompts import (
    ARC_M_MAX,
    ARC_M_MIN,
    ARC_VALID_K,
    _score_alignment,
    compute_optimal_chapters_per_arc,
    get_emotion_phase_for_chapter,
)


class TestEdgeCases:
    """边界条件"""

    @pytest.mark.parametrize("n", [0, -1, -100, -9999])
    def test_invalid_n_returns_zero(self, n):
        m, reason = compute_optimal_chapters_per_arc(n)
        assert m == 0
        assert "无效" in reason or "禁用" in reason

    def test_very_small_n_falls_back(self):
        """N=50 小于阈值,触发 fallback 1 路径"""
        m, reason = compute_optimal_chapters_per_arc(50)
        assert m > 0
        assert "fallback" in reason.lower() or "偏少" in reason

    def test_very_large_n_falls_back_to_max(self):
        """N=3500 超过 K=29 上限,触发 fallback 2 路径"""
        m, reason = compute_optimal_chapters_per_arc(3500)
        assert m > 0
        assert m <= ARC_M_MAX
        assert "过大" in reason or "fallback" in reason.lower()

    def test_minimum_aligned_n(self):
        """N=ARC_M_MIN*5=150 是首个能完美对齐的总章数"""
        m, _ = compute_optimal_chapters_per_arc(150)
        assert m == 30
        assert _score_alignment(150, m) == 3


class TestPerfectAlignmentForTypicalN:
    """主流总章数应取得 score=3 完美对齐"""

    @pytest.mark.parametrize("n,expected_m,expected_k", [
        (150, 30, 5),    # ARC_M_MIN*5,K=5 临界
        (200, 40, 5),    # K=5 标准
        (300, 60, 5),    # K=5 标准
        (400, 80, 5),    # K=5 标准(目标项目当前)
        (500, 100, 5),   # ARC_M_MAX*5,K=5 上界
        (600, 66, 9),    # K=5 越界 → 升级到 K=9(注意取 floor 66 而非 round 67)
        (800, 89, 9),    # K=9 中间
        (900, 100, 9),   # K=9 上界
        (1000, 77, 13),  # K=9 越界 → 升级到 K=13
        (1300, 100, 13), # K=13 上界
        (2000, 95, 21),  # K=21
        (2900, 100, 29), # K=29 上界
    ])
    def test_typical_n_perfect_alignment(self, n, expected_m, expected_k):
        m, reason = compute_optimal_chapters_per_arc(n)
        assert m == expected_m, f"N={n} 期望 M={expected_m},实际 {m}"
        assert f"K={expected_k}" in reason, (
            f"N={n} 期望 K={expected_k},实际 reason={reason!r}"
        )
        assert _score_alignment(n, m) == 3, f"N={n} 应完美对齐"

    @pytest.mark.parametrize("n", [150, 200, 300, 400, 500, 600, 800, 1000, 1300, 2000, 2900])
    def test_anchors_fall_into_disaster_phases(self, n):
        """三次灾难锚点必然落入挫折/绝境/跌落期"""
        m, _ = compute_optimal_chapters_per_arc(n)
        for pct, expected_phase in [(0.25, "挫折"), (0.50, "绝境"), (0.75, "跌落")]:
            ch = max(1, round(n * pct))
            phase = get_emotion_phase_for_chapter(ch, m)
            assert phase is not None
            assert phase.name == expected_phase, (
                f"N={n} M={m} ch{ch} ({pct:.0%}) 期望 {expected_phase} 实际 {phase.name}"
            )


class TestRangeGuarantees:
    """算法应保证 M 在合理范围内"""

    @pytest.mark.parametrize("n", range(150, 3001, 50))
    def test_m_always_in_valid_range_for_main_path(self, n):
        """主路径(N >= 150)的 M 必须在 [ARC_M_MIN, ARC_M_MAX]"""
        m, _ = compute_optimal_chapters_per_arc(n)
        assert ARC_M_MIN <= m <= ARC_M_MAX, (
            f"N={n} M={m} 越界 [{ARC_M_MIN}, {ARC_M_MAX}]"
        )

    @pytest.mark.parametrize("n", [60, 80, 100, 120, 149])
    def test_fallback_returns_positive_m(self, n):
        """fallback 1 路径(N<150)至少返回 M>0"""
        m, _ = compute_optimal_chapters_per_arc(n)
        assert m > 0


class TestKSelectionStrategy:
    """K 候选策略:同等对齐质量优先 K 小"""

    def test_prefer_smaller_k_when_tied(self):
        """N=400 同时满足 K=5 (M=80) 与 K=9 (M=44),应选 K=5"""
        m, reason = compute_optimal_chapters_per_arc(400)
        assert "K=5" in reason
        assert m == 80

    def test_k_upgraded_when_k5_out_of_range(self):
        """N=600,K=5 → M=120 越界,应升级到 K=9"""
        m, reason = compute_optimal_chapters_per_arc(600)
        assert "K=9" in reason
        # 不能是 K=5 (因为 K=5 时 M=120 > ARC_M_MAX)
        assert "K=5" not in reason


class TestAlignmentScorer:
    """_score_alignment 内部辅助函数"""

    def test_perfect_score_for_known_aligned(self):
        assert _score_alignment(400, 80) == 3
        assert _score_alignment(200, 40) == 3
        assert _score_alignment(1000, 77) == 3

    def test_zero_score_for_misaligned(self):
        # cpa=4*N/4=N(单卷),所有锚点 arc_pct=0.25/0.5/0.75 落入 挫折/绝境/跌落
        # 实际是单卷模型,确实完美对齐 → 反例需手工构造
        # cpa=N (单卷,K=1) 时:0.25→挫折/0.5→绝境/0.75→跌落 → 居然 score=3
        # 真正反例:cpa = N/4 (4 卷),所有锚点撞卷末
        assert _score_alignment(400, 100) == 0  # K=4,全部新局

    def test_invalid_input_returns_zero(self):
        assert _score_alignment(0, 100) == 0
        assert _score_alignment(400, 0) == 0
        assert _score_alignment(-100, 80) == 0


class TestReasonText:
    """reason 字符串契约"""

    def test_main_path_includes_k_and_m(self):
        """主路径 reason 必含 K 与 M 数值"""
        for n in (200, 400, 1000):
            _, reason = compute_optimal_chapters_per_arc(n)
            assert re.search(r"K=\d+", reason)
            assert re.search(r"\d+\s*章", reason)
            assert "完美" in reason or re.search(r"\d/3", reason)

    def test_fallback_includes_warning(self):
        """fallback 路径 reason 必含警示符号"""
        for n in (50, 3500):
            _, reason = compute_optimal_chapters_per_arc(n)
            assert "⚠" in reason or "warning" in reason.lower()


class TestModuleConstants:
    """常量契约:外部回填工具会读取这些常量"""

    def test_arc_valid_k_all_four_n_plus_one(self):
        """ARC_VALID_K 中所有值必须 ≡ 1 (mod 4)"""
        for K in ARC_VALID_K:
            assert K % 4 == 1, f"K={K} 不满足 K ≡ 1 (mod 4)"

    def test_arc_m_range_sensible(self):
        """卷长范围必须有意义"""
        assert ARC_M_MIN >= 6   # 6 阶段至少各 1 章
        assert ARC_M_MAX <= 200
        assert ARC_M_MIN < ARC_M_MAX
