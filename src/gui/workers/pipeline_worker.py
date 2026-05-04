"""后台流水线 Worker:在 QThread 中执行 auto 生成流程"""
import os
import sys
import json
import logging
import threading
from PySide6.QtCore import QThread, Signal, QCoreApplication

from src.gui.utils.log_handler import SignalLogHandler
from src.gui.workers.model_factory import create_model


class PipelineWorker(QThread):
    """后台运行 auto 流水线"""

    # ---- 信号 ----
    chapter_started = Signal(int)            # 章节开始
    chapter_completed = Signal(int, str)     # 章节完成 (chapter_num, title)
    chapter_failed = Signal(int, str)        # 章节失败 (chapter_num, error_msg)
    progress_updated = Signal(int, int)      # (current, total)
    pipeline_finished = Signal(bool)         # 是否成功完成
    log_message = Signal(str, str)           # (message, level)

    def __init__(
        self,
        config_path: str,
        env_path: str,
        force_outline: bool = False,
        extra_prompt: str = "",
        target_chapters_list: list[int] | None = None,
    ):
        super().__init__()
        self._config_path = config_path
        self._env_path = env_path
        self._force_outline = force_outline
        self._extra_prompt = extra_prompt
        self._target_chapters_list = target_chapters_list
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # 公共方法
    # ------------------------------------------------------------------

    def stop(self):
        """请求停止流水线（当前章节完成后生效）"""
        self._stop_event.set()

    def _get_requested_target_chapters(self, end_chapter: int) -> list[int]:
        """返回指定章节模式下有效的目标章节列表"""
        if not self._target_chapters_list:
            return []
        return [
            ch for ch in self._target_chapters_list
            if 1 <= ch <= end_chapter
        ]

    def _get_required_outline_chapters(self, end_chapter: int) -> int:
        """返回当前模式下所需的大纲最小章节数"""
        requested_targets = self._get_requested_target_chapters(end_chapter)
        if requested_targets:
            return max(requested_targets)
        if self._target_chapters_list:
            return 0
        return end_chapter

    # ------------------------------------------------------------------
    # 核心执行逻辑
    # ------------------------------------------------------------------

    def run(self):  # noqa: C901  — 与 main.py auto 保持一致的长流程
        logger = logging.getLogger("PipelineWorker")
        handler: SignalLogHandler | None = None

        try:
            # ---- 1. 加载配置（env + Config 串行化，避免并发 worker 互相污染 os.environ）----
            from ._env_lock import ENV_CONFIG_LOCK
            from dotenv import load_dotenv
            from src.config.config import Config
            from src.config.ai_config import AIConfig

            with ENV_CONFIG_LOCK:
                load_dotenv(self._env_path, override=True)
                config = Config(self._config_path)
                # 在锁内一次性取出 reranker 配置，避免后续再读 os.environ
                ai_config_snapshot = AIConfig()
                reranker_config = ai_config_snapshot.get_openai_config("reranker")

            # ---- 2. 初始化日志（会清除所有已有 handler） ----
            from src.generators.common.utils import setup_logging
            setup_logging(config.log_config["log_dir"], clear_logs=True)

            # ---- 3. 安装日志桥接 Handler（必须在 setup_logging 之后） ----
            handler = SignalLogHandler()
            handler.emitter.log_message.connect(self.log_message.emit)
            root_logger = logging.getLogger()
            root_logger.addHandler(handler)

            # ---- 4. 创建模型实例 ----
            outline_model = create_model(config.get_model_config("outline_model"), context="PipelineWorker")
            content_model = create_model(config.get_model_config("content_model"), context="PipelineWorker")
            embedding_model = create_model(config.get_model_config("embedding_model"), context="PipelineWorker")
            # 注入取消检查到模型层，使 API 调用重试间隙可响应停止
            outline_model.cancel_checker = self._stop_event.is_set
            content_model.cancel_checker = self._stop_event.is_set

            # ---- 5. 创建知识库（含 Reranker 配置） ----
            from src.knowledge_base.knowledge_base import KnowledgeBase
            knowledge_base = KnowledgeBase(
                config.knowledge_base_config, embedding_model,
                reranker_config=reranker_config
            )

            # ---- 6. 创建生成器 ----
            from src.generators.finalizer.finalizer import NovelFinalizer
            from src.generators.outline.outline_generator import OutlineGenerator
            from src.generators.content.content_generator import ContentGenerator

            finalizer = NovelFinalizer(config, content_model, knowledge_base)
            outline_generator = OutlineGenerator(
                config, outline_model, knowledge_base, content_model
            )
            # 注入取消检查回调，使大纲和内容生成过程中均可响应停止信号
            outline_generator.cancel_checker = self._stop_event.is_set

            content_generator = ContentGenerator(
                config, content_model, knowledge_base, finalizer=finalizer
            )
            content_generator.cancel_checker = self._stop_event.is_set

            # ---- 7. 获取目标章节数 ----
            end_chapter = config.novel_config.get("target_chapters")
            if not end_chapter or not isinstance(end_chapter, int) or end_chapter <= 0:
                raise RuntimeError(QCoreApplication.translate("PipelineWorker", "配置文件中未找到有效的目标章节数设置 (target_chapters)"))

            # ---- 8. 检查 / 生成大纲 ----
            if self._stop_event.is_set():
                logger.info(QCoreApplication.translate("PipelineWorker", "收到停止信号,流水线中止。"))
                self.pipeline_finished.emit(False)
                return

            outline_generator._load_outline()
            current_outline_count = len(outline_generator.chapter_outlines)

            # 指定章节模式下跳过大纲生成（大纲必须已存在）
            if not self._target_chapters_list:
                if current_outline_count < end_chapter or self._force_outline:
                    if self._force_outline:
                        outline_ok = outline_generator.generate_outline(
                            novel_type=config.novel_config.get("type"),
                            theme=config.novel_config.get("theme"),
                            style=config.novel_config.get("style"),
                            mode="replace",
                            replace_range=(1, end_chapter),
                            extra_prompt=self._extra_prompt,
                        )
                    else:
                        outline_ok = outline_generator.generate_outline(
                            novel_type=config.novel_config.get("type"),
                            theme=config.novel_config.get("theme"),
                            style=config.novel_config.get("style"),
                            mode="replace",
                            replace_range=(current_outline_count + 1, end_chapter),
                            extra_prompt=self._extra_prompt,
                        )
                    if not outline_ok:
                        raise RuntimeError(QCoreApplication.translate("PipelineWorker", "大纲生成失败,停止流程。"))
                    logger.info(QCoreApplication.translate("PipelineWorker", "大纲生成成功!"))

            # 确保 content_generator 加载最新大纲
            content_generator._load_outline()
            required_outline_chapters = self._get_required_outline_chapters(end_chapter)
            outline_count = len(content_generator.chapter_outlines)
            if outline_count < required_outline_chapters:
                if self._target_chapters_list:
                    requested_targets = self._get_requested_target_chapters(end_chapter)
                    raise RuntimeError(
                        QCoreApplication.translate(
                            "PipelineWorker",
                            "大纲章节数 ({0}) 小于所选章节上限 ({1})，无法重新生成指定章节: {2}",
                        ).format(
                            outline_count,
                            required_outline_chapters,
                            requested_targets,
                        )
                    )
                raise RuntimeError(
                    QCoreApplication.translate("PipelineWorker", "大纲章节数 ({0}) 小于目标章节数 ({1})").format(
                        outline_count, end_chapter
                    )
                )

            # ---- 9. 由 ContentGenerator._load_progress 决定起始章节（仅连续模式使用） ----
            # 旧逻辑直接读 summary.json max+1，会忽略"正文已落盘但 finalize 失败"的章节，
            # 导致这些章节被反复覆盖生成。改为信任 ContentGenerator 的进度（综合磁盘扫描）。
            start_chapter = 1
            if not self._target_chapters_list:
                start_chapter = content_generator.current_chapter + 1

                if start_chapter > end_chapter:
                    logger.info(QCoreApplication.translate("PipelineWorker", "所有章节均已完成,无需生成。"))
                    self.progress_updated.emit(end_chapter, end_chapter)
                    self.pipeline_finished.emit(True)
                    return

            # ---- 10. 逐章生成 ----
            # 确定要生成的章节列表
            if self._target_chapters_list:
                # 指定章节模式：仅生成指定章节（用于重新生成失败章节）
                chapters_to_generate = self._get_requested_target_chapters(end_chapter)
                logger.info(QCoreApplication.translate("PipelineWorker", "指定章节模式:将生成 {0} 章: {1}").format(len(chapters_to_generate), chapters_to_generate))
            else:
                # 连续模式:从断点续写
                chapters_to_generate = list(range(start_chapter, end_chapter + 1))

            total_to_generate = len(chapters_to_generate)
            if total_to_generate == 0:
                logger.info(QCoreApplication.translate("PipelineWorker", "没有需要生成的章节。"))
                self.progress_updated.emit(end_chapter, end_chapter)
                self.pipeline_finished.emit(True)
                return

            for idx, chapter_num in enumerate(chapters_to_generate):
                if self._stop_event.is_set():
                    logger.info(QCoreApplication.translate("PipelineWorker", "收到停止信号,流水线中止。"))
                    self.pipeline_finished.emit(False)
                    return

                self.chapter_started.emit(chapter_num)

                # 连续模式下：跳过已完成章节、为已存在但缺摘要的章节补 finalize
                # （指定章节重生成模式 self._target_chapters_list 仍按用户意图覆盖）
                if not self._target_chapters_list:
                    try:
                        existing_path = content_generator._chapter_content_exists(chapter_num)
                    except Exception:
                        existing_path = None
                    in_summary = chapter_num in getattr(
                        content_generator, "_chapters_in_summary", set()
                    )
                    if existing_path and in_summary:
                        title = self._get_chapter_title(content_generator, chapter_num)
                        logger.info(QCoreApplication.translate("PipelineWorker", "第 {0} 章已完成,跳过。").format(chapter_num))
                        content_generator.current_chapter = chapter_num
                        self.chapter_completed.emit(chapter_num, title)
                        self.progress_updated.emit(idx + 1, total_to_generate)
                        continue
                    if existing_path and not in_summary:
                        logger.warning(QCoreApplication.translate(
                            "PipelineWorker", "第 {0} 章正文已存在但缺摘要,补跑 finalize。"
                        ).format(chapter_num))
                        finalize_ok = False
                        try:
                            finalize_ok = finalizer.finalize_chapter(
                                chapter_num=chapter_num, update_summary=True
                            )
                        except Exception as fe:
                            logger.error(
                                QCoreApplication.translate("PipelineWorker", "第 {0} 章补 finalize 异常: {1}").format(chapter_num, fe),
                                exc_info=True,
                            )
                        if finalize_ok:
                            content_generator._chapters_in_summary.add(chapter_num)
                            content_generator.current_chapter = chapter_num
                            title = self._get_chapter_title(content_generator, chapter_num)
                            self.chapter_completed.emit(chapter_num, title)
                            self.progress_updated.emit(idx + 1, total_to_generate)
                            continue
                        # finalize 失败则按错误流程处理
                        self.chapter_failed.emit(
                            chapter_num,
                            QCoreApplication.translate("PipelineWorker", "补 finalize 失败"),
                        )
                        self.progress_updated.emit(idx + 1, total_to_generate)
                        continue

                try:
                    # 设置 content_generator 的当前章节索引
                    content_generator.current_chapter = chapter_num - 1
                    success = content_generator.generate_content(
                        target_chapter=chapter_num,
                        external_prompt=self._extra_prompt or None,
                    )
                    if success:
                        title = self._get_chapter_title(
                            content_generator, chapter_num
                        )
                        self.chapter_completed.emit(chapter_num, title)
                    else:
                        self.chapter_failed.emit(chapter_num, QCoreApplication.translate("PipelineWorker", "生成返回失败"))
                except InterruptedError:
                    logger.info(QCoreApplication.translate("PipelineWorker", "第 {0} 章生成被用户取消。").format(chapter_num))
                    self.pipeline_finished.emit(False)
                    return
                except Exception as exc:
                    logger.error(QCoreApplication.translate("PipelineWorker", "第 {0} 章生成异常: {1}").format(chapter_num, exc), exc_info=True)
                    self.chapter_failed.emit(chapter_num, str(exc))

                self.progress_updated.emit(idx + 1, total_to_generate)

            # ---- 11. 全部章节完成后自动合并 ----
            if not self._target_chapters_list:
                # 仅在连续模式(非指定章节重生成模式)下执行合并
                try:
                    logger.info(QCoreApplication.translate("PipelineWorker", "开始合并所有章节..."))
                    merged_path = content_generator.merge_all_chapters()
                    if merged_path:
                        logger.info(QCoreApplication.translate("PipelineWorker", "已合并所有章节到: {0}").format(merged_path))
                    else:
                        logger.warning(QCoreApplication.translate("PipelineWorker", "章节合并未成功,请检查日志"))
                except Exception as exc:
                    logger.error(QCoreApplication.translate("PipelineWorker", "章节合并失败: {0}").format(exc), exc_info=True)

            logger.info(QCoreApplication.translate("PipelineWorker", "自动生成流程全部完成!"))
            self.pipeline_finished.emit(True)

        except Exception as exc:
            logging.getLogger("PipelineWorker").error(
                QCoreApplication.translate("PipelineWorker", "流水线异常终止: {0}").format(exc), exc_info=True
            )
            self.pipeline_finished.emit(False)
        finally:
            # 移除日志桥接，避免泄漏
            if handler is not None:
                logging.getLogger().removeHandler(handler)

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _get_chapter_title(content_generator, chapter_num: int) -> str:
        """尝试从大纲中获取章节标题"""
        try:
            if chapter_num <= len(content_generator.chapter_outlines):
                return content_generator.chapter_outlines[chapter_num - 1].title
        except Exception:
            pass
        return f"第{chapter_num}章"
