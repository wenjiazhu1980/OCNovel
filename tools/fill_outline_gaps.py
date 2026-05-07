"""逐章补生成 outline.json 的缺失槽位

设计目标：
- 仅对 chapter_outlines[i] is None 的位置调用 LLM，避免 batch 浪费
- 复用 OutlineGenerator._generate_single_chapter_outline 的现成逻辑（一致性检查、上下文注入等）
- 每章生成后立即落盘，确保中断不丢已成功的补生
- 失败章节累计后报告，不阻断其他章节

使用：
    python tools/fill_outline_gaps.py --config /Volumes/DH/OCNovel/config.json --env /Volumes/DH/OCNovel/.env

可选参数：
    --max-retries N   每章失败后的重试次数（默认 2）
    --retry-delay S   重试间隔秒（默认 5）
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# 注入项目根路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="补生成 outline.json 缺失章节槽位")
    parser.add_argument("--config", required=True, help="config.json 绝对路径")
    parser.add_argument("--env", required=True, help=".env 绝对路径")
    parser.add_argument("--max-retries", type=int, default=2, help="单章重试次数")
    parser.add_argument("--retry-delay", type=float, default=5.0, help="重试间隔秒")
    args = parser.parse_args()

    # 加载环境
    load_dotenv(args.env, override=True)

    from src.config.config import Config
    from src.config.ai_config import AIConfig
    from src.generators.outline.outline_generator import OutlineGenerator
    from src.knowledge_base.knowledge_base import KnowledgeBase
    from src.models.openai_model import OpenAIModel
    from src.models.gemini_model import GeminiModel
    from src.models.claude_model import ClaudeModel
    from src.generators.common.utils import setup_logging

    config = Config(args.config)

    # 设置日志：同时输出到控制台
    log_dir = config.log_config.get("log_dir", "./logs")
    setup_logging(log_dir, clear_logs=False)
    logging.getLogger().setLevel(logging.INFO)
    # 添加控制台 handler（setup_logging 通常只写文件）
    console_h = logging.StreamHandler()
    console_h.setLevel(logging.INFO)
    console_h.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logging.getLogger().addHandler(console_h)

    log = logging.getLogger("fill_outline_gaps")

    def create_model(model_config: dict):
        t = model_config.get("type")
        if t == "openai":
            return OpenAIModel(model_config)
        if t == "gemini":
            return GeminiModel(model_config)
        if t == "claude":
            return ClaudeModel(model_config)
        raise ValueError(f"不支持的模型类型: {t}")

    log.info("初始化模型与知识库...")
    outline_model = create_model(config.get_model_config("outline_model"))
    content_model = create_model(config.get_model_config("content_model"))
    embedding_model = create_model(config.get_model_config("embedding_model"))

    ai_snap = AIConfig()
    reranker_config = ai_snap.get_openai_config("reranker")

    knowledge_base = KnowledgeBase(
        config.knowledge_base_config,
        embedding_model,
        reranker_config=reranker_config,
    )

    log.info("初始化 OutlineGenerator...")
    generator = OutlineGenerator(config, outline_model, knowledge_base, content_model)

    # 探测缺失槽位
    missing = [
        idx + 1 for idx, slot in enumerate(generator.chapter_outlines) if slot is None
    ]
    target_chapters = config.novel_config.get("target_chapters", 0)

    # 兜底：若加载 max < target_chapters，扩展到 target 后重新探测
    if len(generator.chapter_outlines) < target_chapters:
        log.info(
            f"chapter_outlines 长度 {len(generator.chapter_outlines)} < target_chapters {target_chapters}，"
            f"扩展尾部空槽"
        )
        generator.chapter_outlines.extend(
            [None] * (target_chapters - len(generator.chapter_outlines))
        )
        missing = [
            idx + 1
            for idx, slot in enumerate(generator.chapter_outlines)
            if slot is None
        ]

    if not missing:
        log.info("✓ 没有缺失章节，无需补生成")
        return 0

    log.info(f"检测到 {len(missing)} 个缺失槽位: {missing}")
    log.info("开始逐章补生成（每成功一章立即落盘）...")

    novel_cfg = config.novel_config
    novel_type = novel_cfg.get("type", "")
    theme = novel_cfg.get("theme", "")
    style = novel_cfg.get("style", "")

    # [5.1] DRY 整合: 直接复用 OutlineGenerator.patch_missing_chapters,
    # 而非在此处重复实现"逐章补生成 + 重试 + 落盘"循环。
    # patch_missing_chapters 已包含:
    #   - 多轮重试(配置 outline_gap_max_retries / outline_gap_retry_delay)
    #   - 一致性检查 + 落盘
    #   - 取消信号处理
    # 本脚本只负责参数桥接(--max-retries/--retry-delay 覆盖配置默认)
    try:
        succeeded, failed = generator.patch_missing_chapters(
            missing,
            novel_type=novel_type,
            theme=theme,
            style=style,
            extra_prompt=None,
            max_rounds=args.max_retries,
            retry_delay=args.retry_delay,
        )
    except InterruptedError:
        log.info("用户中断,已保留已成功章节")
        return 130

    log.info("=" * 60)
    log.info(f"补生成结束：成功 {len(succeeded)}/{len(missing)}，失败 {len(failed)}")
    if succeeded:
        log.info(f"  成功章节: {succeeded}")
    if failed:
        log.error(f"  失败章节: {failed}")

    # 验证最终连续性
    generator._load_outline()
    final_missing = [
        idx + 1 for idx, slot in enumerate(generator.chapter_outlines) if slot is None
    ]
    if final_missing:
        log.error(f"重新加载后仍有 {len(final_missing)} 个缺失槽位: {final_missing}")
        return 1
    log.info(f"✓ 重新加载验证：所有 {len(generator.chapter_outlines)} 章大纲连续完整")
    return 0


if __name__ == "__main__":
    sys.exit(main())
