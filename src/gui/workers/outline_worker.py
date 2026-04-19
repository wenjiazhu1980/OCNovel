"""后台大纲 Worker：在 QThread 中单独执行大纲生成"""
import os
import logging
import threading
from PySide6.QtCore import QThread, Signal, QCoreApplication

from src.gui.utils.log_handler import SignalLogHandler


def create_model(model_config: dict):
    """根据配置创建 AI 模型实例"""
    model_type = model_config["type"]
    if model_type == "gemini":
        from src.models.gemini_model import GeminiModel
        return GeminiModel(model_config)
    elif model_type in ("openai",):
        from src.models.openai_model import OpenAIModel
        return OpenAIModel(model_config)
    elif model_type == "claude":
        from src.models.claude_model import ClaudeModel
        return ClaudeModel(model_config)
    else:
        raise ValueError(
            QCoreApplication.translate(
                "OutlineWorker", "不支持的模型类型: {0}"
            ).format(model_type)
        )


class OutlineWorker(QThread):
    """后台单独执行大纲生成"""

    # ---- 信号 ----
    outline_finished = Signal(bool, str)  # (success, message)
    log_message = Signal(str, str)        # (message, level)

    def __init__(
        self,
        config_path: str,
        env_path: str,
        force_outline: bool = False,
        extra_prompt: str = "",
        start_chapter: int = 0,
        end_chapter: int = 0,
    ):
        super().__init__()
        self._config_path = config_path
        self._env_path = env_path
        self._force_outline = force_outline
        self._extra_prompt = extra_prompt
        # 0 表示"未指定"，由 Worker 自动推断
        self._start_chapter = start_chapter
        self._end_chapter = end_chapter
        self._stop_event = threading.Event()

    def stop(self):
        """请求停止大纲生成"""
        self._stop_event.set()

    def run(self):
        logger = logging.getLogger("OutlineWorker")
        handler: SignalLogHandler | None = None

        try:
            # ---- 1. 加载配置（env + Config 串行化，避免并发 worker 污染 os.environ）----
            from ._env_lock import ENV_CONFIG_LOCK
            from dotenv import load_dotenv
            from src.config.config import Config
            from src.config.ai_config import AIConfig

            with ENV_CONFIG_LOCK:
                load_dotenv(self._env_path, override=True)
                config = Config(self._config_path)
                ai_config_snapshot = AIConfig()
                reranker_config = ai_config_snapshot.get_openai_config("reranker")

            # ---- 2. 初始化日志 ----
            from src.generators.common.utils import setup_logging
            setup_logging(config.log_config["log_dir"], clear_logs=False)

            # ---- 3. 安装日志桥接 Handler ----
            handler = SignalLogHandler()
            handler.emitter.log_message.connect(self.log_message.emit)
            root_logger = logging.getLogger()
            root_logger.addHandler(handler)

            # ---- 4. 创建模型实例 ----
            outline_model = create_model(config.get_model_config("outline_model"))
            content_model = create_model(config.get_model_config("content_model"))
            embedding_model = create_model(config.get_model_config("embedding_model"))
            outline_model.cancel_checker = self._stop_event.is_set

            # ---- 5. 创建知识库 ----
            from src.knowledge_base.knowledge_base import KnowledgeBase
            knowledge_base = KnowledgeBase(
                config.knowledge_base_config, embedding_model,
                reranker_config=reranker_config,
            )

            # ---- 6. 创建大纲生成器 ----
            from src.generators.outline.outline_generator import OutlineGenerator
            outline_generator = OutlineGenerator(
                config, outline_model, knowledge_base, content_model,
            )
            outline_generator.cancel_checker = self._stop_event.is_set

            # ---- 7. 获取目标章节数 ----
            target_chapters = config.novel_config.get("target_chapters")
            if not target_chapters or not isinstance(target_chapters, int) or target_chapters <= 0:
                raise RuntimeError(
                    QCoreApplication.translate(
                        "OutlineWorker",
                        "配置文件中未找到有效的目标章节数设置 (target_chapters)",
                    )
                )

            # ---- 8. 检查停止信号 ----
            if self._stop_event.is_set():
                logger.info(QCoreApplication.translate("OutlineWorker", "收到停止信号，大纲生成中止。"))
                self.outline_finished.emit(False, QCoreApplication.translate("OutlineWorker", "用户取消"))
                return

            # ---- 9. 确定生成范围 ----
            outline_generator._load_outline()
            current_count = len(outline_generator.chapter_outlines)

            # 用户指定了自定义范围
            custom_start = self._start_chapter if self._start_chapter > 0 else 0
            custom_end = self._end_chapter if self._end_chapter > 0 else 0

            if custom_start > 0 and custom_end > 0:
                # 自定义范围模式：直接覆盖指定区间
                if custom_start > custom_end:
                    raise RuntimeError(
                        QCoreApplication.translate(
                            "OutlineWorker", "起始章节 ({0}) 不能大于结束章节 ({1})"
                        ).format(custom_start, custom_end)
                    )
                if custom_end > target_chapters:
                    raise RuntimeError(
                        QCoreApplication.translate(
                            "OutlineWorker",
                            "结束章节 ({0}) 超过目标章节数 ({1})"
                        ).format(custom_end, target_chapters)
                    )
                start_ch, end_ch = custom_start, custom_end
                logger.info(
                    QCoreApplication.translate(
                        "OutlineWorker", "自定义范围生成大纲 ({0}~{1})"
                    ).format(start_ch, end_ch)
                )
            elif self._force_outline:
                # 强制重生成全部
                start_ch, end_ch = 1, target_chapters
                logger.info(
                    QCoreApplication.translate(
                        "OutlineWorker", "强制重新生成全部大纲 (1~{0})"
                    ).format(end_ch)
                )
            elif current_count >= target_chapters:
                msg = QCoreApplication.translate(
                    "OutlineWorker",
                    "大纲已完整（{0}/{1} 章），无需重新生成。如需覆盖请勾选「强制重生成大纲」或指定章节范围。",
                ).format(current_count, target_chapters)
                logger.info(msg)
                self.outline_finished.emit(True, msg)
                return
            else:
                # 自动补充模式
                start_ch = current_count + 1
                end_ch = target_chapters
                logger.info(
                    QCoreApplication.translate(
                        "OutlineWorker", "补充生成大纲 ({0}~{1})"
                    ).format(start_ch, end_ch)
                )

            # ---- 10. 执行生成 ----
            outline_ok = outline_generator.generate_outline(
                novel_type=config.novel_config.get("type"),
                theme=config.novel_config.get("theme"),
                style=config.novel_config.get("style"),
                mode="replace",
                replace_range=(start_ch, end_ch),
                extra_prompt=self._extra_prompt,
            )

            if outline_ok:
                msg = QCoreApplication.translate(
                    "OutlineWorker", "大纲生成成功！范围 {0}~{1} 章。"
                ).format(start_ch, end_ch)
                logger.info(msg)
                self.outline_finished.emit(True, msg)
            else:
                msg = QCoreApplication.translate("OutlineWorker", "大纲生成失败，请检查日志。")
                logger.error(msg)
                self.outline_finished.emit(False, msg)

        except Exception as exc:
            logger.error(
                QCoreApplication.translate("OutlineWorker", "大纲生成异常: {0}").format(exc),
                exc_info=True,
            )
            self.outline_finished.emit(False, str(exc))
        finally:
            if handler is not None:
                logging.getLogger().removeHandler(handler)
