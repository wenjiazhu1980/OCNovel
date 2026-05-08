"""[P1] 为已有 outline.json 回填 emotion_tone 占位

设计目标
========
当 LLM 在大纲生成阶段未按 prompt 输出 ``emotion_tone`` 字段（即 ``_save_outline``
统计中 emotion_tone 覆盖率偏低）时，本工具按章节号 + 卷长（``chapters_per_arc``）
机械地填入对应情绪阶段名作为占位，便于后续:

- 章节内容生成时仍能从 outline 读到一个非空 emotion_tone（避免下游空值分支）
- 人工审稿能快速识别"哪些章节的情绪节奏由 LLM 主动规划、哪些是工具回填"
- 后续整本重生成时，LLM 可拿到上下文中的占位作为参考

非目标（不做的事）
================
- 不调用 LLM；纯基于章节号 + 卷长公式回填
- 不覆盖原已有的非空 emotion_tone（即使是 LLM 写的低质量值也保留）
- 不修改 character_goals / scene_sequence / foreshadowing / pov_character
  （这些字段需要语义理解，机械回填没有意义）

使用示例
========
基础用法（推荐）::

    python tools/backfill_emotion_tone.py \
        --output-dir /Volumes/DH/OCNovel/data/output \
        --chapters-per-arc 40

只预览不写盘::

    python tools/backfill_emotion_tone.py \
        --output-dir <DIR> --chapters-per-arc 40 --dry-run

自定义占位后缀（默认 "（自动回填）"）::

    python tools/backfill_emotion_tone.py \
        --output-dir <DIR> --chapters-per-arc 40 \
        --placeholder-suffix "[backfill]"

退出码
======
- 0: 成功（含 dry-run）
- 2: 参数错误 / 文件缺失 / JSON 解析失败
- 3: 写盘失败
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 注入项目根路径，便于直接 `python tools/backfill_emotion_tone.py` 运行
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.generators.prompts import (  # noqa: E402  (after sys.path injection)
    EMOTION_PHASES,
    EmotionPhase,
    get_emotion_phase_for_chapter,
)


# ---------------------------------------------------------------------------
# 纯函数：可被单元测试直接调用，不依赖 argparse / 文件系统
# ---------------------------------------------------------------------------

def backfill_outline_emotion_tone(
    outline_data: List[Dict[str, Any]],
    chapters_per_arc: int,
    placeholder_suffix: str = "（自动回填）",
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """对内存中的 outline 列表进行回填，返回新列表 + 统计。

    本函数是纯函数：不读写文件、不打印日志（除 logging），便于单元测试。

    Args:
        outline_data: outline.json 解析后的章节字典列表（按章节号升序更佳，
            但本函数不做强制要求；遇到 None 槽位会保留并跳过）。
        chapters_per_arc: 每卷章节数；必须 > 0，否则函数返回原列表的浅拷贝
            并在统计中记录 ``skipped_no_arc=N``。
        placeholder_suffix: 占位文本的后缀（与阶段名拼接，如 "成长（自动回填）"）。
            空字符串则只填阶段名本身。

    Returns:
        (backfilled_data, stats)
        - backfilled_data: 浅拷贝后的章节列表，原列表不被修改。
        - stats: dict，包含 keys:
            - total: 输入条目数
            - sparse_none: None/非 dict 占位数（保留原样）
            - already_set: 原 emotion_tone 非空的条目数（保留原值）
            - filled: 本次新填充的条目数
            - skipped_no_chapter_num: chapter_number 缺失/非 int 的条目数
            - skipped_no_arc: chapters_per_arc <= 0 时的总跳过数
    """
    stats = {
        "total": len(outline_data),
        "sparse_none": 0,
        "already_set": 0,
        "filled": 0,
        "skipped_no_chapter_num": 0,
        "skipped_no_arc": 0,
    }

    if chapters_per_arc <= 0:
        # 配置异常：保留原样，明确记录到统计
        stats["skipped_no_arc"] = stats["total"]
        return [dict(c) if isinstance(c, dict) else c for c in outline_data], stats

    new_data: List[Dict[str, Any]] = []
    for item in outline_data:
        # 容错：稀疏列表的 None 槽位 / 非 dict 杂项原样保留
        if item is None or not isinstance(item, dict):
            new_data.append(item)
            stats["sparse_none"] += 1
            continue

        # 浅拷贝避免污染调用方
        ch = dict(item)

        chapter_num = ch.get("chapter_number")
        if not isinstance(chapter_num, int) or chapter_num < 1:
            stats["skipped_no_chapter_num"] += 1
            new_data.append(ch)
            continue

        existing = ch.get("emotion_tone")
        if isinstance(existing, str) and existing.strip():
            stats["already_set"] += 1
            new_data.append(ch)
            continue

        phase: Optional[EmotionPhase] = get_emotion_phase_for_chapter(
            chapter_num, chapters_per_arc
        )
        if phase is None:
            # 理论上不可达（chapters_per_arc 已校验）；保险兜底
            new_data.append(ch)
            continue

        ch["emotion_tone"] = (
            f"{phase.name}{placeholder_suffix}" if placeholder_suffix else phase.name
        )
        stats["filled"] += 1
        new_data.append(ch)

    return new_data, stats


# ---------------------------------------------------------------------------
# CLI 入口：负责文件 IO、备份、日志
# ---------------------------------------------------------------------------

def _backup_outline(outline_path: Path) -> Path:
    """复制 outline.json 到带时间戳的备份文件，返回备份路径。"""
    ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = outline_path.with_name(f"{outline_path.stem}.bak.{ts}{outline_path.suffix}")
    shutil.copy2(outline_path, backup)
    return backup


def _format_stats(stats: Dict[str, int]) -> str:
    return (
        f"  - 输入总条目: {stats['total']}\n"
        f"  - None 槽位/非 dict（原样保留）: {stats['sparse_none']}\n"
        f"  - 原已有非空 emotion_tone（保留）: {stats['already_set']}\n"
        f"  - 本次新回填: {stats['filled']}\n"
        f"  - chapter_number 缺失（跳过）: {stats['skipped_no_chapter_num']}\n"
        f"  - 配置异常导致全跳过: {stats['skipped_no_arc']}"
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="为 outline.json 回填 emotion_tone 占位（按 chapters_per_arc 节奏）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="outline.json 所在目录（如 data/output 或 /Volumes/DH/OCNovel/data/output）",
    )
    parser.add_argument(
        "--chapters-per-arc",
        type=int,
        required=True,
        help="每卷章节数（必须 > 0；通常对应 config.json 的 arc_config.chapters_per_arc）",
    )
    parser.add_argument(
        "--placeholder-suffix",
        default="（自动回填）",
        help="占位后缀，默认 '（自动回填）'。传空串则只填阶段名。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只预览不写盘，stdout 打印统计与前 5 条变更示例",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="跳过备份原文件（默认会写一份 .bak.<ts> 副本，强烈建议保留默认）",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="启用 DEBUG 级别日志"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    if args.chapters_per_arc <= 0:
        logging.error("--chapters-per-arc 必须 > 0")
        return 2

    output_dir = Path(args.output_dir).expanduser().resolve()
    outline_path = output_dir / "outline.json"
    if not outline_path.is_file():
        logging.error(f"outline.json 不存在: {outline_path}")
        return 2

    try:
        with outline_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logging.error(f"读取/解析 outline.json 失败: {e}")
        return 2

    # 兼容旧格式：dict 包 chapters / 直接 list
    if isinstance(raw, dict):
        chapters = raw.get("chapters", [])
        wrapper = raw
        was_wrapped = True
    elif isinstance(raw, list):
        chapters = raw
        wrapper = None
        was_wrapped = False
    else:
        logging.error(f"outline.json 顶层结构不识别: {type(raw).__name__}")
        return 2

    new_chapters, stats = backfill_outline_emotion_tone(
        chapters,
        chapters_per_arc=args.chapters_per_arc,
        placeholder_suffix=args.placeholder_suffix,
    )

    logging.info("回填统计：\n" + _format_stats(stats))

    # 打印前几条变更示例（dry-run 或 verbose 都打）
    if args.dry_run or args.verbose:
        sample_changes = []
        for orig, new in zip(chapters, new_chapters):
            if not isinstance(orig, dict) or not isinstance(new, dict):
                continue
            if orig.get("emotion_tone") != new.get("emotion_tone"):
                sample_changes.append(
                    f"  ch{new.get('chapter_number')}: "
                    f"{orig.get('emotion_tone', '')!r} → {new.get('emotion_tone')!r}"
                )
                if len(sample_changes) >= 5:
                    break
        if sample_changes:
            logging.info("变更示例（前 5 条）：\n" + "\n".join(sample_changes))

    if args.dry_run:
        logging.info("dry-run 模式：不写盘。")
        return 0

    if stats["filled"] == 0:
        logging.info("无任何条目需要回填，跳过写盘。")
        return 0

    # 写盘前备份
    if not args.no_backup:
        try:
            backup = _backup_outline(outline_path)
            logging.info(f"已备份原文件到: {backup}")
        except OSError as e:
            logging.error(f"备份原文件失败，已中止写盘: {e}")
            return 3

    # 还原顶层结构再写回
    payload: Any = (
        {**wrapper, "chapters": new_chapters} if was_wrapped else new_chapters
    )
    try:
        tmp_path = outline_path.with_suffix(outline_path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, outline_path)
    except OSError as e:
        logging.error(f"写盘失败: {e}")
        return 3

    logging.info(f"已写回 {outline_path}（回填 {stats['filled']} 章）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
