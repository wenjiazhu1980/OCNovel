"""[L2] 推荐 chapters_per_arc 的 CLI 查询工具

不修改任何文件,仅打印推荐值与对齐预览。

使用示例
========
基础查询::

    python tools/recommend_arc_size.py --total-chapters 400

详细对比 K 候选::

    python tools/recommend_arc_size.py --total-chapters 600 --show-candidates

JSON 输出(便于脚本消费)::

    python tools/recommend_arc_size.py --total-chapters 400 --json

退出码
======
- 0: 推荐完美对齐(score=3) 或 用户使用 --json 模式
- 1: 推荐对齐质量降级(score < 3) 或 fallback 路径触发
- 2: 参数错误
"""

from __future__ import annotations

import argparse
import json as _json
import sys
from pathlib import Path
from typing import List, Optional

# 注入项目根
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.generators.prompts import (  # noqa: E402
    ARC_M_MAX,
    ARC_M_MIN,
    ARC_VALID_K,
    _score_alignment,
    compute_optimal_chapters_per_arc,
    get_emotion_phase_for_chapter,
)


def _build_anchor_preview(total_chapters: int, M: int) -> List[str]:
    """渲染三次灾难锚点预览行,如 'ch100 (25%) → 卷 2 第 20 章 → 挫折期 ✓'。"""
    lines = []
    targets = (("挫折", 0.25), ("绝境", 0.50), ("跌落", 0.75))
    for expected, pct in targets:
        ch = max(1, round(total_chapters * pct))
        if M > 0:
            arc_num = (ch - 1) // M + 1
            arc_pos = (ch - 1) % M + 1
            phase = get_emotion_phase_for_chapter(ch, M)
            phase_name = phase.name if phase else "-"
            mark = "✓" if phase_name == expected else "✗"
            lines.append(
                f"  ch{ch:>4} ({int(pct * 100):>2}%) → "
                f"卷 {arc_num} 第 {arc_pos:>2} 章 → {phase_name}期 {mark}"
                f"{' (期望: ' + expected + '期)' if phase_name != expected else ''}"
            )
        else:
            lines.append(f"  ch{ch:>4} ({int(pct * 100):>2}%) → arc 模型禁用")
    return lines


def _build_candidates_table(total_chapters: int) -> List[str]:
    """渲染所有 K 候选的对比表格。"""
    rows = ["  K     M    对齐    范围内    备注"]
    for K in ARC_VALID_K:
        ideal = total_chapters / K
        # 取最优 M(round/floor/ceil 中分数最高)
        best_M, best_score = 0, -1
        for M in {round(ideal), int(ideal), int(ideal) + 1}:
            if not (ARC_M_MIN <= M <= ARC_M_MAX):
                continue
            score = _score_alignment(total_chapters, M)
            if score > best_score:
                best_score = score
                best_M = M
        in_range = ARC_M_MIN <= best_M <= ARC_M_MAX
        if best_M > 0:
            quality = "完美" if best_score == 3 else f"{best_score}/3"
            range_mark = "✓" if in_range else "✗"
            note = "" if in_range else f"M 越界 [{ARC_M_MIN},{ARC_M_MAX}]"
            rows.append(f"  {K:<5} {best_M:<4} {quality:<6} {range_mark:<7}  {note}")
        else:
            ideal_round = round(ideal)
            rows.append(f"  {K:<5} {ideal_round:<4} -       ✗        M 越界 [{ARC_M_MIN},{ARC_M_MAX}]")
    return rows


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="推荐 chapters_per_arc,使全书灾难锚点与卷内情绪节奏对齐",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--total-chapters", "-n",
        type=int,
        required=True,
        help="总章节数(必须 > 0)",
    )
    parser.add_argument(
        "--show-candidates",
        action="store_true",
        help="额外显示所有 K 值候选的对比表格",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式输出(便于脚本消费),禁用人类可读渲染",
    )
    args = parser.parse_args(argv)

    if args.total_chapters <= 0:
        print("错误: --total-chapters 必须 > 0", file=sys.stderr)
        return 2

    M, reason = compute_optimal_chapters_per_arc(args.total_chapters)
    score = _score_alignment(args.total_chapters, M)

    if args.json:
        out = {
            "total_chapters": args.total_chapters,
            "recommended_chapters_per_arc": M,
            "alignment_score": score,
            "reason": reason,
            "anchors": [
                {
                    "pct": pct,
                    "chapter": max(1, round(args.total_chapters * pct)),
                    "expected_phase": expected,
                    "actual_phase": (
                        get_emotion_phase_for_chapter(
                            max(1, round(args.total_chapters * pct)), M
                        ).name
                        if M > 0 and get_emotion_phase_for_chapter(
                            max(1, round(args.total_chapters * pct)), M
                        )
                        else None
                    ),
                }
                for expected, pct in (("挫折", 0.25), ("绝境", 0.50), ("跌落", 0.75))
            ],
        }
        print(_json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    # 人类可读输出
    print(f"总章节数: {args.total_chapters}")
    print(f"推荐 chapters_per_arc = {M}")
    print(f"原因: {reason}")
    print()
    print("灾难锚点预览:")
    for line in _build_anchor_preview(args.total_chapters, M):
        print(line)

    if args.show_candidates:
        print()
        print("所有 K 候选对比:")
        for line in _build_candidates_table(args.total_chapters):
            print(line)

    print()
    print("应用方式(任选其一):")
    print(f'  方式1 显式指定: "arc_config": {{ "chapters_per_arc": {M} }}')
    print(f'  方式2 自动计算: "arc_config": {{ "chapters_per_arc": 0, "auto_compute": true }}')
    if M > 0 and score < 3:
        print()
        print(f"⚠ 当前推荐对齐质量 {score}/3,完美对齐需要总章数为 K∈{{5,9,13...}} 的整数倍")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
