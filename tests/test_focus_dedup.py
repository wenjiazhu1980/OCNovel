# -*- coding: utf-8 -*-
"""
描写侧重列表语义去重的纯算法测试

不依赖 Qt,只测 src/gui/utils/focus_dedup.py 的:
  - Tier B (embedding cosine) 主路径
  - Tier A (jieba Jaccard) 兜底
  - embedding 失败自动降级
  - max_total 截断
  - 边界情况
  - stats 契约
"""

from __future__ import annotations

import numpy as np
import pytest
from unittest.mock import MagicMock

from src.gui.utils.focus_dedup import deduplicate_focus_items


# ---------------------------------------------------------------------------
# 辅助:构造 fake embedding model
# ---------------------------------------------------------------------------
def _make_keyword_embedder(keyword_to_vec: dict[str, list[float]]):
    """
    构造一个 mock embedding model:
      - 文本里出现 keyword 时返回对应向量
      - 多个关键词命中时返回平均向量
      - 无命中时返回纯噪声向量
    便于精确控制相似度,验证 cosine 阈值生效。
    """
    dim = len(next(iter(keyword_to_vec.values())))

    def embed(text: str) -> np.ndarray:
        vecs = [np.array(v, dtype=np.float32)
                for kw, v in keyword_to_vec.items() if kw in text]
        if vecs:
            v = np.mean(np.stack(vecs), axis=0)
        else:
            # 纯噪声向量:用文本的 hash 让其稳定可复现
            rng = np.random.default_rng(abs(hash(text)) % (2**32))
            v = rng.standard_normal(dim).astype(np.float32)
        return v

    m = MagicMock()
    m.embed.side_effect = embed
    return m


# ---------------------------------------------------------------------------
# Tier B: 嵌入向量主路径
# ---------------------------------------------------------------------------
class TestTierBEmbedding:
    """embedding_model 可用时,走 cosine 相似度去重"""

    def test_high_cosine_treated_as_dup(self):
        """同维度向量(都映射到「战斗」轴)应被识别为重复"""
        embedder = _make_keyword_embedder({
            "战斗": [1.0, 0.0, 0.0],
            "世界观": [0.0, 1.0, 0.0],
            "人物": [0.0, 0.0, 1.0],
        })
        existing = ["战斗场面的力量感"]  # 命中"战斗" → [1,0,0]
        candidates = [
            "武打戏与神通的力量感",  # 无关键词 → 噪声(预期不重)
            "战斗描写的爽感",  # 命中"战斗" → [1,0,0] → 与 existing cos=1.0
            "世界观奇景营造",  # 命中"世界观" → 不重
        ]
        kept, stats = deduplicate_focus_items(
            existing, candidates, embedding_model=embedder,
            cosine_threshold=0.85, max_total=10,
        )
        assert stats["method"] == "embedding"
        # "战斗描写的爽感" 必须被剔除(cos=1.0)
        assert "战斗描写的爽感" not in kept
        # "世界观奇景营造" 必须保留
        assert "世界观奇景营造" in kept
        assert stats["rejected_dup"] >= 1
        assert stats["fallback_reason"] is None

    def test_orthogonal_vectors_kept(self):
        """正交向量 cosine=0,不应被去重"""
        embedder = _make_keyword_embedder({
            "战斗": [1.0, 0.0, 0.0, 0.0],
            "情感": [0.0, 1.0, 0.0, 0.0],
            "权谋": [0.0, 0.0, 1.0, 0.0],
            "悬疑": [0.0, 0.0, 0.0, 1.0],
        })
        existing = ["战斗描写"]
        candidates = ["情感刻画", "权谋博弈", "悬疑氛围"]
        kept, stats = deduplicate_focus_items(
            existing, candidates, embedding_model=embedder,
            cosine_threshold=0.85, max_total=10,
        )
        assert len(kept) == 3
        assert stats["rejected_dup"] == 0
        assert stats["method"] == "embedding"

    def test_intra_candidate_dedup(self):
        """候选间互重也要识别(候选 1 与候选 2 命中同一关键词)"""
        embedder = _make_keyword_embedder({
            "战斗": [1.0, 0.0],
            "情感": [0.0, 1.0],
        })
        existing = []
        candidates = [
            "战斗描写一",
            "战斗描写二",  # 与候选 1 cos=1.0
            "情感一",
        ]
        kept, stats = deduplicate_focus_items(
            existing, candidates, embedding_model=embedder,
            cosine_threshold=0.85, max_total=10,
        )
        assert len(kept) == 2  # 只保留 1 个战斗 + 1 个情感
        assert stats["rejected_dup"] == 1


# ---------------------------------------------------------------------------
# Tier A: jieba Jaccard 兜底
# ---------------------------------------------------------------------------
class TestTierAJaccardFallback:
    """embedding_model=None 时直接走 Jaccard"""

    def test_high_token_overlap_dedup(self):
        """同词干高重叠应去重"""
        existing = ["战斗场面的力量感"]
        candidates = ["战斗场面的爽快感"]  # 与 existing 共享"战斗/场面"
        kept, stats = deduplicate_focus_items(
            existing, candidates, embedding_model=None,
            jaccard_threshold=0.3, max_total=10,
        )
        assert stats["method"] == "jaccard"
        assert kept == []
        assert stats["rejected_dup"] == 1

    def test_low_token_overlap_kept(self):
        """完全不同主题应保留"""
        existing = ["战斗场面"]
        candidates = ["世界观奇观", "权谋博弈", "情感纠葛"]
        kept, stats = deduplicate_focus_items(
            existing, candidates, embedding_model=None,
            jaccard_threshold=0.5, max_total=10,
        )
        assert len(kept) == 3
        assert stats["rejected_dup"] == 0


# ---------------------------------------------------------------------------
# Embedding 调用失败 → 自动降级
# ---------------------------------------------------------------------------
class TestEmbedFailureFallback:
    """embed() 抛异常时自动降级到 Jaccard,记录 fallback_reason"""

    def test_not_implemented_error(self):
        """Claude 模型 embed() 抛 NotImplementedError"""
        m = MagicMock()
        m.embed.side_effect = NotImplementedError("Claude 不支持嵌入")
        existing = ["战斗场面的力量感"]
        candidates = ["战斗场面的爽快感", "情感纠葛与人物刻画"]
        kept, stats = deduplicate_focus_items(
            existing, candidates, embedding_model=m,
            max_total=10, jaccard_threshold=0.3,
        )
        # 应该降级到 jaccard
        assert stats["method"] == "jaccard"
        assert stats["fallback_reason"] is not None
        assert "NotImplementedError" in stats["fallback_reason"]
        # Jaccard 应识别"战斗+场面"高重叠
        assert "战斗场面的爽快感" not in kept
        assert "情感纠葛与人物刻画" in kept

    def test_generic_exception(self):
        """通用异常(如 timeout)也应降级"""
        m = MagicMock()
        m.embed.side_effect = TimeoutError("API 超时")
        kept, stats = deduplicate_focus_items(
            ["旧条目"], ["新条目甲", "新条目乙"], embedding_model=m,
            max_total=10,
        )
        assert stats["method"] == "jaccard"
        assert "TimeoutError" in stats["fallback_reason"]


# ---------------------------------------------------------------------------
# 加固:max_total 上限截断
# ---------------------------------------------------------------------------
class TestMaxTotalCap:
    """超过 max_total 时,候选被截断"""

    def test_existing_full_no_room(self):
        """existing 已经达到 max_total,kept 应为空,rejected_capped 计入"""
        existing = [f"已有第{i}条" for i in range(8)]
        # 候选间不互重(用完全不同的关键词),让 Jaccard 不触发 dedup
        candidates = ["独立主题甲", "独立主题乙"]
        kept, stats = deduplicate_focus_items(
            existing, candidates, embedding_model=None,
            jaccard_threshold=0.99, max_total=8,
        )
        assert kept == []
        assert stats["rejected_capped"] == 2

    def test_partial_room(self):
        """existing=6, candidates=4, max=8 → 只能加 2,截断 2"""
        existing = [f"已有第{i}条独特内容{chr(0x4e00+i)}" for i in range(6)]
        # 让候选间无重复,Jaccard 通过
        candidates = ["独立主题甲A", "独立主题乙B", "独立主题丙C", "独立主题丁D"]
        kept, stats = deduplicate_focus_items(
            existing, candidates, embedding_model=None,
            jaccard_threshold=0.99,  # 几乎不去重,聚焦验证截断
            max_total=8,
        )
        assert len(kept) == 2
        assert stats["rejected_capped"] == 2

    def test_dedup_first_then_cap(self):
        """先去重再截断:重复的不占用配额"""
        existing = []
        # 5 条候选,前 3 条互重,后 2 条独立
        embedder = _make_keyword_embedder({
            "战斗": [1.0, 0.0, 0.0],
            "情感": [0.0, 1.0, 0.0],
            "权谋": [0.0, 0.0, 1.0],
        })
        candidates = ["战斗一", "战斗二", "战斗三", "情感一", "权谋一"]
        kept, stats = deduplicate_focus_items(
            existing, candidates, embedding_model=embedder,
            cosine_threshold=0.85, max_total=4,
        )
        # 去重后剩 3 条(战斗一/情感一/权谋一)
        # max_total=4,existing=0 → 余额 4 → 全部保留
        assert len(kept) == 3
        assert stats["rejected_dup"] == 2
        assert stats["rejected_capped"] == 0


# ---------------------------------------------------------------------------
# 边界
# ---------------------------------------------------------------------------
class TestEdgeCases:
    """空输入 / 全空白 / 全部相同"""

    def test_empty_candidates(self):
        kept, stats = deduplicate_focus_items(
            ["existing"], [], embedding_model=None, max_total=8,
        )
        assert kept == []
        assert stats["rejected_dup"] == 0
        assert stats["rejected_capped"] == 0

    def test_empty_existing(self):
        kept, stats = deduplicate_focus_items(
            [], ["新条目甲", "新条目乙"], embedding_model=None,
            jaccard_threshold=0.99, max_total=8,
        )
        assert len(kept) == 2

    def test_whitespace_only_candidates(self):
        """全空白的候选应被预清洗剔除"""
        kept, stats = deduplicate_focus_items(
            [], ["", "   ", "\n\t"], embedding_model=None, max_total=8,
        )
        assert kept == []

    def test_all_identical_candidates(self):
        """完全相同的候选:候选间互比应剔除重复"""
        kept, _ = deduplicate_focus_items(
            [], ["战斗描写", "战斗描写", "战斗描写"], embedding_model=None,
            jaccard_threshold=0.5, max_total=8,
        )
        assert len(kept) == 1


# ---------------------------------------------------------------------------
# stats 契约
# ---------------------------------------------------------------------------
class TestStatsContract:
    """stats 字典字段齐全"""

    def test_stats_keys_when_embedding_path(self):
        embedder = _make_keyword_embedder({"战斗": [1.0, 0.0]})
        _, stats = deduplicate_focus_items(
            [], ["战斗"], embedding_model=embedder, max_total=8,
        )
        assert set(stats.keys()) == {
            "method", "rejected_dup", "rejected_capped", "fallback_reason"
        }
        assert stats["method"] == "embedding"
        assert stats["fallback_reason"] is None

    def test_stats_keys_when_jaccard_path(self):
        _, stats = deduplicate_focus_items(
            [], ["条目"], embedding_model=None, max_total=8,
        )
        assert set(stats.keys()) == {
            "method", "rejected_dup", "rejected_capped", "fallback_reason"
        }
        assert stats["method"] == "jaccard"

    def test_stats_keys_when_fallback_triggered(self):
        m = MagicMock()
        m.embed.side_effect = RuntimeError("network down")
        _, stats = deduplicate_focus_items(
            ["a"], ["b"], embedding_model=m, max_total=8,
        )
        assert stats["method"] == "jaccard"
        assert "RuntimeError" in stats["fallback_reason"]
        assert "network down" in stats["fallback_reason"]
