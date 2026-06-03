"""后台大纲修订 Worker:根据审计报告修订 outline.json"""
import logging
import os
import threading

from PySide6.QtCore import QCoreApplication, QThread, Signal

from src.gui.utils.log_handler import SignalLogHandler
from src.gui.workers.model_factory import create_model


class OutlineRevisionWorker(QThread):
    """后台执行大纲审计修订"""

    revision_finished = Signal(bool, str)  # (success, message)
    log_message = Signal(str, str)         # (message, level)

    def __init__(
        self,
        config_path: str,
        env_path: str,
        include_warning: bool = False,
        dry_run: bool = False,
    ):
        super().__init__()
        self._config_path = config_path
        self._env_path = env_path
        self._include_warning = include_warning
        self._dry_run = dry_run
        self._stop_event = threading.Event()

    def stop(self):
        """请求停止修订（当前模型调用完成后生效）"""
        self._stop_event.set()

    def _resolve_output_dir(self, output_dir: str) -> str:
        if not output_dir:
            output_dir = os.path.join(os.path.dirname(self._config_path), "data", "output")
        if not os.path.isabs(output_dir):
            output_dir = os.path.join(os.path.dirname(self._config_path), output_dir)
        return output_dir

    def run(self):
        logger = logging.getLogger("OutlineRevisionWorker")
        handler: SignalLogHandler | None = None

        try:
            from ._env_lock import ENV_CONFIG_LOCK
            from dotenv import load_dotenv
            from src.config.config import Config

            with ENV_CONFIG_LOCK:
                load_dotenv(self._env_path, override=True)
                config = Config(self._config_path)

            from src.generators.common.utils import setup_logging
            setup_logging(config.log_config["log_dir"], clear_logs=False)

            handler = SignalLogHandler()
            handler.emitter.log_message.connect(self.log_message.emit)
            root_logger = logging.getLogger()
            root_logger.addHandler(handler)

            output_dir = self._resolve_output_dir(config.output_config.get("output_dir", ""))
            outline_path = os.path.join(output_dir, "outline.json")
            audit_report_path = os.path.join(output_dir, "outline_audit_report.json")
            revision_report_path = os.path.join(output_dir, "outline_revision_report.json")

            if self._stop_event.is_set():
                msg = QCoreApplication.translate("OutlineRevisionWorker", "用户取消")
                logger.info(msg)
                self.revision_finished.emit(False, msg)
                return

            if not os.path.exists(outline_path):
                raise FileNotFoundError(QCoreApplication.translate(
                    "OutlineRevisionWorker", "未找到 outline.json，请先生成大纲: {0}"
                ).format(outline_path))
            if not os.path.exists(audit_report_path):
                raise FileNotFoundError(QCoreApplication.translate(
                    "OutlineRevisionWorker", "未找到 outline_audit_report.json，请先运行大纲审计复核: {0}"
                ).format(audit_report_path))

            outline_model_config = config.get_model_config("outline_model")
            logger.info(QCoreApplication.translate(
                "OutlineRevisionWorker", "开始根据审计报告修订大纲..."
            ))
            outline_model = create_model(outline_model_config, context="OutlineRevisionWorker")

            from src.generators.outline.outline_reviser import revise_outline_file

            severities = ("fatal", "warning") if self._include_warning else ("fatal",)
            report = revise_outline_file(
                outline_path=outline_path,
                audit_report_path=audit_report_path,
                model=outline_model,
                output_report_path=revision_report_path,
                severities=severities,
                dry_run=self._dry_run,
            )
            stats = report.get("stats", {})
            logger.info(QCoreApplication.translate(
                "OutlineRevisionWorker",
                "大纲修订完成：actionable {0} / requested {1} / applied {2}",
            ).format(
                stats.get("actionable_findings", 0),
                stats.get("requested_revisions", 0),
                stats.get("applied_revisions", 0),
            ))

            if self._stop_event.is_set():
                msg = QCoreApplication.translate("OutlineRevisionWorker", "用户取消")
                logger.info(msg)
                self.revision_finished.emit(False, msg)
                return

            applied = int(stats.get("applied_revisions", 0) or 0)
            changed = stats.get("changed_chapters", []) or []
            if applied:
                message = QCoreApplication.translate(
                    "OutlineRevisionWorker",
                    "大纲修订完成，已修改 {0} 章: {1}\n备份文件:\n{2}\n修订报告:\n{3}",
                ).format(
                    applied,
                    ", ".join(str(n) for n in changed),
                    report.get("backup_path", ""),
                    report.get("revision_report", revision_report_path),
                )
            else:
                message = QCoreApplication.translate(
                    "OutlineRevisionWorker",
                    "大纲修订完成，未发现需要写回的修订。\n修订报告:\n{0}",
                ).format(report.get("revision_report", revision_report_path))
            self.revision_finished.emit(True, message)

        except Exception as exc:
            logger.error(
                QCoreApplication.translate("OutlineRevisionWorker", "大纲修订失败: {0}").format(exc),
                exc_info=True,
            )
            self.revision_finished.emit(False, str(exc))
        finally:
            if handler is not None:
                logging.getLogger().removeHandler(handler)
