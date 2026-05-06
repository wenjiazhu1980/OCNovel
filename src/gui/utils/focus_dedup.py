# -*- coding: utf-8 -*-
"""描写侧重列表的语义去重工具

三层方案:
  - Tier B (主路径): 用 BaseModel.embed() 计算 cosine 相似度
  - Tier A (兜底):   jieba 分词后 Jaccard 相似度;极短文本回退到字符 bigram
  - 加固:            合并后总数硬上限 max_total (默认 8)

返回 stats 字典让上层 GUI 在弹框中告知用户当前走的是哪条路径。
"""
from __future__ import annotations

import logging
from typing import Iterable

import numpy as np

_logger = logging.getLogger(__name__)

# 中文常见标点,Jaccard 计算时丢弃避免噪声
_PUNCT = {" ", "　", "，", "、", "。", "；", "：", "！", "？",
          "（", "）", "(", ")", "「", "」", "“", "”", "‘", "’",
          ",", ".", ";", ":", "!", "?"}


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------
def deduplicate_focus_items(
    existing: list[str],
    candidates: list[str],
    embedding_model=None,
    *,
    cosine_threshold: float = 0.85,
    jaccard_threshold: float = 0.5,
    max_total: int = 8,
) -> tuple[list[str], dict]:
    """对 candidates 做去重(相对 existing 与候选间互比),并施加总数上限

    Args:
        existing: 已有列表
        candidates: 待合并的候选(模型新生成)
        embedding_model: 可选,具备 .embed(text)->np.ndarray 的对象;
            None 时直接走 Tier A
        cosine_threshold: Tier B 视为重复的余弦相似度下限
        jaccard_threshold: Tier A 视为重复的 Jaccard 相似度下限
        max_total: existing + kept 合并后的硬性上限

    Returns:
        (kept, stats)
        kept: 通过过滤的候选子集,可直接 extend 到 existing
        stats: {
            "method":          "embedding" | "jaccard"
            "rejected_dup":    int   # 被相似度判定剔除的候选数
            "rejected_capped": int   # 因达 max_total 而被截断的候选数
            "fallback_reason": str | None
        }
    """
    stats = {
        "method": "embedding" if embedding_model is not None else "jaccard",
        "rejected_dup": 0,
        "rejected_capped": 0,
        "fallback_reason": None,
    }

    # 候选预清洗:去空、去前后空白
    cleaned: list[str] = [str(x).strip() for x in candidates if str(x).strip()]
    if not cleaned:
        return [], stats

    existing_clean = [str(x).strip() for x in existing if str(x).strip()]

    # 计算可允许新增的额度
    remaining = max(0, max_total - len(existing_clean))

    # 主路径: Tier B 嵌入向量 + cosine
    if embedding_model is not None:
        try:
            kept = _dedup_by_embedding(
                existing_clean, cleaned, embedding_model,
                cosine_threshold=cosine_threshold,
                stats=stats,
            )
        except Exception as e:
            _logger.warning(
                f"语义去重(Tier B)失败,降级到词级 Jaccard: {type(e).__name__}: {e}"
            )
            stats["method"] = "jaccard"
            stats["fallback_reason"] = f"{type(e).__name__}: {e}"
            stats["rejected_dup"] = 0  # 重置,Tier A 重算
            kept = _dedup_by_jaccard(
                existing_clean, cleaned,
                jaccard_threshold=jaccard_threshold,
                stats=stats,
            )
    else:
        kept = _dedup_by_jaccard(
            existing_clean, cleaned,
            jaccard_threshold=jaccard_threshold,
            stats=stats,
        )

    # 加固: max_total 截断(在去重之后做,优先保留靠前候选)
    if len(kept) > remaining:
        stats["rejected_capped"] = len(kept) - remaining
        kept = kept[:remaining]

    return kept, stats


# ---------------------------------------------------------------------------
# Tier B: 嵌入向量 + cosine
# ---------------------------------------------------------------------------
def _dedup_by_embedding(
    existing: list[str],
    candidates: list[str],
    embedding_model,
    *,
    cosine_threshold: float,
    stats: dict,
) -> list[str]:
    """对 candidates 计算嵌入向量,与 existing + 已通过候选互比 cosine"""
    # 先把 existing 全部 embed(可能抛错,由上层 catch)
    existing_vecs: list[np.ndarray] = [
        np.asarray(embedding_model.embed(s), dtype=np.float32) for s in existing
    ]

    kept: list[str] = []
    kept_vecs: list[np.ndarray] = []
    for cand in candidates:
        vc = np.asarray(embedding_model.embed(cand), dtype=np.float32)
        # 与 existing + 已通过的候选都比对
        is_dup = False
        for ve in existing_vecs:
            if _cosine(vc, ve) >= cosine_threshold:
                is_dup = True
                break
        if not is_dup:
            for vk in kept_vecs:
                if _cosine(vc, vk) >= cosine_threshold:
                    is_dup = True
                    break
        if is_dup:
            stats["rejected_dup"] += 1
        else:
            kept.append(cand)
            kept_vecs.append(vc)
    return kept


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na < 1e-12 or nb < 1e-12:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


# ---------------------------------------------------------------------------
# Tier A: jieba 分词 + Jaccard (字符 bigram 兜底)
# ---------------------------------------------------------------------------
def _dedup_by_jaccard(
    existing: list[str],
    candidates: list[str],
    *,
    jaccard_threshold: float,
    stats: dict,
) -> list[str]:
    """对 candidates 用 jieba 分词后 Jaccard;极短文本回退到字符 bigram"""
    existing_tokens = [_tokenize(s) for s in existing]

    kept: list[str] = []
    kept_tokens: list[set[str]] = []
    for cand in candidates:
        tc = _tokenize(cand)
        is_dup = False
        for te in existing_tokens:
            if _jaccard(tc, te) >= jaccard_threshold:
                is_dup = True
                break
        if not is_dup:
            for tk in kept_tokens:
                if _jaccard(tc, tk) >= jaccard_threshold:
                    is_dup = True
                    break
        if is_dup:
            stats["rejected_dup"] += 1
        else:
            kept.append(cand)
            kept_tokens.append(tc)
    return kept


def _tokenize(text: str) -> set[str]:
    """jieba 分词去标点,空白;若分词后有效 token <= 1,降级到字符 bigram"""
    try:
        import jieba
        tokens = {t.strip() for t in jieba.cut(text) if t.strip() and t not in _PUNCT}
    except Exception:
        tokens = set()
    if len(tokens) <= 1:
        tokens = _char_bigrams(text)
    return tokens


def _char_bigrams(text: str) -> set[str]:
    """字符二元组(过滤标点),作为极短文本的兜底特征"""
    chars = [c for c in text if c not in _PUNCT and not c.isspace()]
    if len(chars) < 2:
        return {"".join(chars)} if chars else set()
    return {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)
