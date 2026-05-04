#!/usr/bin/env python3
"""数据修复脚本：扫描 output_dir，为已存在正文但缺 summary.json 条目的章节补 finalize。

典型场景：
  - 流水线在某章 finalize 失败但仍继续生成后续正文，导致 summary.json 与磁盘脱节
  - 重启后系统误判这些章节"未生成"

用法：
  python -m src.tools.recover_summary --output-dir data/output9
  python -m src.tools.recover_summary --output-dir data/output9 --apply
  python -m src.tools.recover_summary --output-dir data/output9 --apply --skip-imitation
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Set, Tuple, List

# 让脚本能从仓库根目录运行（src/tools/recover_summary.py → 三层 dirname 到仓库根）
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from src.config.config import Config  # noqa: E402
from src.config.ai_config import AIConfig  # noqa: E402
from src.knowledge_base.knowledge_base import KnowledgeBase  # noqa: E402
from src.generators.finalizer.finalizer import NovelFinalizer  # noqa: E402
from src.generators.common.utils import setup_logging  # noqa: E402


CONTENT_PATTERN = re.compile(r"^第(\d+)章_")


def scan_output_dir(output_dir: str) -> Tuple[Set[int], Set[int], Set[int], Set[int]]:
    """扫描输出目录，返回四个章节号集合。

    Returns:
        (content_chs, summary_files, summary_keys, imitated_files)
        - content_chs: 含正文 .txt 的章节号
        - summary_files: 含 第NNN章_摘要.txt 的章节号
        - summary_keys: summary.json 中存在的章节号
        - imitated_files: 含 _imitated.txt 的章节号
    """
    if not os.path.isdir(output_dir):
        raise FileNotFoundError(f"目录不存在: {output_dir}")

    content_chs: Set[int] = set()
    summary_files: Set[int] = set()
    imitated_files: Set[int] = set()

    for name in os.listdir(output_dir):
        if not name.endswith(".txt"):
            continue
        m = CONTENT_PATTERN.match(name)
        if not m:
            continue
        n = int(m.group(1))
        if "_摘要" in name:
            summary_files.add(n)
        elif "_imitated" in name:
            imitated_files.add(n)
        else:
            content_chs.add(n)

    summary_keys: Set[int] = set()
    sj = os.path.join(output_dir, "summary.json")
    if os.path.exists(sj):
        try:
            with open(sj, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                summary_keys = {int(k) for k in data.keys() if str(k).isdigit()}
        except Exception as e:
            print(f"[WARN] 解析 summary.json 失败: {e}")

    return content_chs, summary_files, summary_keys, imitated_files


def report(
    output_dir: str,
    content: Set[int],
    summary_f: Set[int],
    summary_k: Set[int],
    imitated: Set[int],
) -> Tuple[List[int], List[int]]:
    """打印诊断报告，返回 (待修复章节列表, 完全缺失章节列表)。"""
    expected_max = max(content | summary_k) if (content or summary_k) else 0
    full_range = set(range(1, expected_max + 1)) if expected_max else set()
    pending = sorted(content - summary_k)
    missing_summary_file = sorted(content - summary_f)
    fully_missing = sorted(full_range - content)

    print("\n==== 扫描结果 ====")
    print(f"  output_dir: {output_dir}")
    print(f"  正文章节数: {len(content)}（最大: {max(content) if content else 0}）")
    print(f"  summary.json 章节数: {len(summary_k)}（最大: {max(summary_k) if summary_k else 0}）")
    print(f"  imitated 文件数: {len(imitated)}")
    print(f"  缺 summary.json 条目（待 finalize）: {len(pending)}")
    if pending:
        preview = pending[:30]
        ellipsis = " ..." if len(pending) > 30 else ""
        print(f"    {preview}{ellipsis}")
    print(f"  缺独立 _摘要.txt 文件: {len(missing_summary_file)}")
    print(f"  完全缺失（无正文，需重新生成）: {len(fully_missing)}")
    if fully_missing:
        preview = fully_missing[:30]
        ellipsis = " ..." if len(fully_missing) > 30 else ""
        print(f"    {preview}{ellipsis}")
    print("=" * 18)
    return pending, fully_missing


def build_finalizer(config: Config) -> NovelFinalizer:
    """复用 main.py 的实例化方式构造 finalizer。"""
    # 延迟 import 避免无关依赖在 dry-run 阶段被加载
    from src.models.gemini_model import GeminiModel
    from src.models.openai_model import OpenAIModel

    def _create_model(model_config: dict):
        t = model_config["type"]
        if t == "gemini":
            return GeminiModel(model_config)
        if t == "openai":
            return OpenAIModel(model_config)
        if t == "claude":
            from src.models.claude_model import ClaudeModel
            return ClaudeModel(model_config)
        raise ValueError(f"不支持的模型类型: {t}")

    ai_config = AIConfig()
    content_model_config = config.get_model_config("content_model")
    embedding_model_config = config.get_model_config("embedding_model")
    content_model = _create_model(content_model_config)
    embedding_model = _create_model(embedding_model_config)

    reranker_config = ai_config.get_openai_config("reranker")
    knowledge_base = KnowledgeBase(
        config.knowledge_base_config,
        embedding_model,
        reranker_config=reranker_config,
    )

    return NovelFinalizer(config, content_model, knowledge_base)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="config.json", help="配置文件路径（默认 config.json）")
    parser.add_argument("--output-dir", help="覆盖 config.json 中的 output_dir（如 data/output9）")
    parser.add_argument("--apply", action="store_true", help="真正执行修复（默认仅 dry-run）")
    parser.add_argument("--limit", type=int, default=0, help="本次最多修复多少章（0 = 不限）")
    parser.add_argument(
        "--only",
        type=str,
        default="",
        help="逗号分隔的章节号列表，仅修复这些章（覆盖 --limit）",
    )
    parser.add_argument(
        "--skip-imitation",
        action="store_true",
        help="临时关闭 auto_imitation，避免重做仿写（仅生成摘要、更新 summary.json）",
    )
    args = parser.parse_args()

    config = Config(args.config)
    if args.output_dir:
        # 允许相对路径相对于 base_dir
        out = args.output_dir
        if not os.path.isabs(out):
            out = os.path.join(config.base_dir, out)
        config.output_config["output_dir"] = out

    if args.skip_imitation:
        # 临时禁用自动仿写，避免在补 finalize 时重做仿写消耗大量 LLM 调用
        imitation = getattr(config, "imitation_config", {}) or {}
        if isinstance(imitation, dict):
            ai = imitation.get("auto_imitation", {})
            if isinstance(ai, dict):
                ai["enabled"] = False
                imitation["auto_imitation"] = ai
        config.imitation_config = imitation
        print("[INFO] --skip-imitation 已生效，本次仅生成摘要、不跑仿写。")

    output_dir = config.output_config["output_dir"]

    # 扫描 + 报告
    content, summary_f, summary_k, imitated = scan_output_dir(output_dir)
    pending, fully_missing = report(output_dir, content, summary_f, summary_k, imitated)

    if args.only:
        try:
            requested = [int(x.strip()) for x in args.only.split(",") if x.strip()]
        except ValueError:
            print(f"[ERROR] --only 参数格式错误: {args.only}")
            return 2
        # 只保留实际有正文且缺 summary 的
        todo = [n for n in requested if n in content and n not in summary_k]
        skipped = sorted(set(requested) - set(todo))
        if skipped:
            print(f"[WARN] 以下章节未在'缺 summary'列表中（已忽略）: {skipped}")
    else:
        todo = pending if args.limit <= 0 else pending[: args.limit]

    if not args.apply:
        print(f"\n[DRY-RUN] 待修复 {len(todo)} 章。加 --apply 才会真正执行。")
        return 0

    if not todo:
        print("\n无待修复章节。")
        return 0

    setup_logging(config.log_config["log_dir"])

    print(f"\n==== 开始修复 {len(todo)} 章（output_dir={output_dir}）====")
    finalizer = build_finalizer(config)

    ok, fail = 0, 0
    for ch in todo:
        print(f"  -> 第 {ch} 章 finalize_chapter ...", flush=True)
        try:
            success = finalizer.finalize_chapter(chapter_num=ch, update_summary=True)
            if success:
                ok += 1
                print(f"     ✓ 第 {ch} 章 OK")
            else:
                fail += 1
                print(f"     ✗ 第 {ch} 章 失败")
        except Exception as e:
            fail += 1
            print(f"     ✗ 第 {ch} 章 异常: {e}")

    print(f"\n完成: 成功 {ok}, 失败 {fail}")
    if fully_missing:
        print(
            f"\n提示: 仍有 {len(fully_missing)} 个章节完全缺失正文，"
            f"需通过 `python main.py content --target-chapter N` 重新生成。"
        )
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
