"""后台章节内容修订 Worker:根据内容审计报告修订章节正文。"""
import logging
import os
import threading

from PySide6.QtCore import QCoreApplication, QThread, Signal

from src.gui.utils.log_handler import SignalLogHandler
from src.gui.workers.model_factory import create_model


class ContentRevisionWorker(QThread):
    """后台执行章节内容审计修订。"""

    content_revision_finished = Signal(bool, str)  # (success, message)
    log_message = Signal(str, str)                 # (message, level)

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

    def stop(self) -> None:
        """请求停止修订（当前模型调用完成后生效）。"""
        self._stop_event.set()

    def _resolve_output_dir(self, output_dir: str) -> str:
        """解析输出目录，兼容相对路径配置。"""
        if not output_dir:
            output_dir = os.path.join(os.path.dirname(self._config_path), "data", "output")
        if not os.path.isabs(output_dir):
            output_dir = os.path.join(os.path.dirname(self._config_path), output_dir)
        return output_dir

    def run(self) -> None:
        """执行章节正文修订并写出修订报告。"""
        logger = logging.getLogger("ContentRevisionWorker")
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

            from src.generators.content.content_reviser import (
                resolve_content_audit_report_path,
                revise_content_files,
            )
            audit_report_path = resolve_content_audit_report_path(output_dir)

            if self._stop_event.is_set():
                msg = QCoreApplication.translate("ContentRevisionWorker", "用户取消")
                logger.info(msg)
                self.content_revision_finished.emit(False, msg)
                return

            if not os.path.exists(outline_path):
                raise FileNotFoundError(QCoreApplication.translate(
                    "ContentRevisionWorker", "未找到 outline.json，请先生成大纲: {0}"
                ).format(outline_path))
            if not os.path.exists(audit_report_path):
                raise FileNotFoundError(QCoreApplication.translate(
                    "ContentRevisionWorker",
                    "未找到内容审计报告，请先运行章节内容审计: {0}",
                ).format(audit_report_path))

            content_model_config = config.get_model_config("content_model")
            logger.info(QCoreApplication.translate(
                "ContentRevisionWorker", "开始根据内容审计报告修订章节正文..."
            ))
            content_model = create_model(content_model_config, context="ContentRevisionWorker")

            severities = ("fatal", "warning") if self._include_warning else ("fatal",)
            report = revise_content_files(
                output_dir=output_dir,
                outline_path=outline_path,
                audit_report_path=audit_report_path,
                model=content_model,
                severities=severities,
                dry_run=self._dry_run,
                stop_event=self._stop_event,
            )
            stats = report.get("stats", {})
            logger.info(QCoreApplication.translate(
                "ContentRevisionWorker",
                "内容修订完成：actionable {0} / requested {1} / applied {2} / written {3}",
            ).format(
                stats.get("actionable_findings", 0),
                stats.get("requested_revisions", 0),
                stats.get("applied_revisions", 0),
                stats.get("written_revisions", 0),
            ))

            if self._stop_event.is_set():
                msg = QCoreApplication.translate("ContentRevisionWorker", "用户取消")
                logger.info(msg)
                self.content_revision_finished.emit(False, msg)
                return

            applied = int(stats.get("applied_revisions", 0) or 0)
            written = int(stats.get("written_revisions", 0) or 0)
            changed = stats.get("changed_chapters", []) or []
            if applied:
                if self._dry_run:
                    message = QCoreApplication.translate(
                        "ContentRevisionWorker",
                        "内容修订 dry-run 完成，模型建议修改 {0} 章: {1}\n修订报告:\n{2}",
                    ).format(
                        applied,
                        ", ".join(str(n) for n in changed),
                        report.get("revision_report", ""),
                    )
                else:
                    backup_lines = "\n".join(
                        f"第{chapter}章: {path}"
                        for chapter, path in sorted(
                            (report.get("backup_paths", {}) or {}).items(),
                            key=lambda item: int(item[0]),
                        )
                    )
                    message = QCoreApplication.translate(
                        "ContentRevisionWorker",
                        "内容修订完成，已写回 {0} 章: {1}\n备份文件:\n{2}\n修订报告:\n{3}",
                    ).format(
                        written,
                        ", ".join(str(n) for n in changed),
                        backup_lines,
                        report.get("revision_report", ""),
                    )
            else:
                message = QCoreApplication.translate(
                    "ContentRevisionWorker",
                    "内容修订完成，未发现需要写回的正文修订。\n修订报告:\n{0}",
                ).format(report.get("revision_report", ""))
            self.content_revision_finished.emit(True, message)

        except Exception as exc:
            logger.error(
                QCoreApplication.translate("ContentRevisionWorker", "内容修订失败: {0}").format(exc),
                exc_info=True,
            )
            self.content_revision_finished.emit(False, str(exc))
        finally:
            if handler is not None:
                logging.getLogger().removeHandler(handler)
