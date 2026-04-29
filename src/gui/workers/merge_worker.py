"""后台合并 Worker:在 QThread 中执行章节合并"""
import os
import logging
import threading
from PySide6.QtCore import QThread, Signal, QCoreApplication

from src.gui.utils.log_handler import SignalLogHandler
from src.gui.workers.model_factory import create_model


class MergeWorker(QThread):
    """后台执行章节合并"""

    # ---- 信号 ----
    merge_finished = Signal(bool, str)  # (success, message/path)
    log_message = Signal(str, str)      # (message, level)

    def __init__(self, config_path: str, env_path: str):
        super().__init__()
        self._config_path = config_path
        self._env_path = env_path
        self._stop_event = threading.Event()

    def stop(self):
        """请求停止合并（当前操作完成后生效）"""
        self._stop_event.set()

    def run(self):
        logger = logging.getLogger("MergeWorker")
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
            content_model = create_model(config.get_model_config("content_model"))
            embedding_model = create_model(config.get_model_config("embedding_model"))

            # ---- 5. 创建知识库 ----
            from src.knowledge_base.knowledge_base import KnowledgeBase
            knowledge_base = KnowledgeBase(
                config.knowledge_base_config, embedding_model,
                reranker_config=reranker_config
            )

            # ---- 6. 创建 ContentGenerator ----
            from src.generators.finalizer.finalizer import NovelFinalizer
            from src.generators.content.content_generator import ContentGenerator

            finalizer = NovelFinalizer(config, content_model, knowledge_base)
            content_generator = ContentGenerator(
                config, content_model, knowledge_base, finalizer=finalizer
            )

            # ---- 7. 执行合并 ----
            if self._stop_event.is_set():
                logger.info(QCoreApplication.translate("MergeWorker", "收到停止信号,合并中止。"))
                self.merge_finished.emit(False, QCoreApplication.translate("MergeWorker", "用户取消"))
                return

            logger.info(QCoreApplication.translate("MergeWorker", "开始合并所有章节..."))
            merged_path = content_generator.merge_all_chapters()

            if merged_path:
                logger.info(QCoreApplication.translate("MergeWorker", "章节合并成功: {0}").format(merged_path))
                self.merge_finished.emit(True, merged_path)
            else:
                logger.warning(QCoreApplication.translate("MergeWorker", "章节合并未成功,请检查日志"))
                self.merge_finished.emit(False, QCoreApplication.translate("MergeWorker", "合并失败,请检查日志"))

        except Exception as exc:
            logger.error(QCoreApplication.translate("MergeWorker", "合并异常: {0}").format(exc), exc_info=True)
            self.merge_finished.emit(False, str(exc))
        finally:
            # 移除日志桥接
            if handler is not None:
                logging.getLogger().removeHandler(handler)
