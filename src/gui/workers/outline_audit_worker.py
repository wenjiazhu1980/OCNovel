"""后台大纲审计 Worker:在 QThread 中执行全局审计与 LLM 复核"""
import json
import logging
import os
import threading

from PySide6.QtCore import QCoreApplication, QThread, Signal

from src.gui.utils.log_handler import SignalLogHandler
from src.gui.workers.model_factory import create_model


class OutlineAuditWorker(QThread):
    """后台执行大纲全局审计复核"""

    audit_finished = Signal(bool, str)  # (success, message)
    log_message = Signal(str, str)      # (message, level)

    def __init__(self, config_path: str, env_path: str):
        super().__init__()
        self._config_path = config_path
        self._env_path = env_path
        self._stop_event = threading.Event()

    def stop(self):
        """请求停止审计（当前步骤完成后生效）"""
        self._stop_event.set()

    def _resolve_output_dir(self, output_dir: str) -> str:
        if not output_dir:
            output_dir = os.path.join(os.path.dirname(self._config_path), "data", "output")
        if not os.path.isabs(output_dir):
            output_dir = os.path.join(os.path.dirname(self._config_path), output_dir)
        return output_dir

    def _load_chapters(self, outline_path: str) -> list:
        with open(outline_path, "r", encoding="utf-8") as fp:
            chapters = json.load(fp)
        if not isinstance(chapters, list):
            raise RuntimeError(
                QCoreApplication.translate(
                    "OutlineAuditWorker", "outline.json 顶层应为章节列表"
                )
            )
        return chapters

    def _write_report(
        self,
        report_path: str,
        findings: list,
        llm_model_type: str,
        llm_stats: dict,
    ) -> tuple[int, int]:
        from src.generators.outline.outline_auditor import serialize_finding

        fatal = [f for f in findings if getattr(f, "severity", "") == "fatal"]
        warning = [f for f in findings if getattr(f, "severity", "") == "warning"]
        with open(report_path, "w", encoding="utf-8") as fp:
            json.dump({
                "total": len(findings),
                "fatal": len(fatal),
                "warning": len(warning),
                "llm_enabled": True,
                "llm_model_type": llm_model_type,
                "llm_stats": llm_stats,
                "findings": [serialize_finding(f) for f in findings],
            }, fp, ensure_ascii=False, indent=2)
        return len(fatal), len(warning)

    def run(self):
        logger = logging.getLogger("OutlineAuditWorker")
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

            output_dir = self._resolve_output_dir(
                config.output_config.get("output_dir", "data/output")
            )
            outline_path = os.path.join(output_dir, "outline.json")
            report_path = os.path.join(output_dir, "outline_audit_report.json")

            if self._stop_event.is_set():
                msg = QCoreApplication.translate("OutlineAuditWorker", "用户取消")
                logger.info(msg)
                self.audit_finished.emit(False, msg)
                return

            if not os.path.exists(outline_path):
                raise FileNotFoundError(
                    QCoreApplication.translate(
                        "OutlineAuditWorker",
                        "未找到 outline.json，请先生成大纲: {0}",
                    ).format(outline_path)
                )

            logger.info(QCoreApplication.translate(
                "OutlineAuditWorker", "开始大纲全局审计: {0}"
            ).format(outline_path))
            chapters = self._load_chapters(outline_path)

            from src.generators.outline.outline_auditor import (
                llm_review_task_closure_with_stats,
                run_audit,
            )

            findings = run_audit(chapters)
            logger.info(QCoreApplication.translate(
                "OutlineAuditWorker", "算法审计完成，发现 {0} 处提示"
            ).format(len(findings)))

            if self._stop_event.is_set():
                msg = QCoreApplication.translate("OutlineAuditWorker", "用户取消")
                logger.info(msg)
                self.audit_finished.emit(False, msg)
                return

            outline_model_config = config.get_model_config("outline_model")
            llm_model_type = outline_model_config.get("type", "unknown")
            logger.info(QCoreApplication.translate(
                "OutlineAuditWorker", "开始 LLM 任务闭环复核（outline_model）..."
            ))
            outline_model = create_model(outline_model_config, context="OutlineAuditWorker")
            llm_result = llm_review_task_closure_with_stats(chapters, outline_model)
            findings.extend(llm_result.findings)
            logger.info(QCoreApplication.translate(
                "OutlineAuditWorker",
                "LLM 复核统计：发布任务 {0} 个，实际调用 {1} 次，发现 {2} 处，调用失败 {3} 次",
            ).format(
                llm_result.stats.get("published_tasks", 0),
                llm_result.stats.get("llm_calls", 0),
                llm_result.stats.get("llm_findings", 0),
                llm_result.stats.get("llm_call_failures", 0),
            ))

            fatal_count, warning_count = self._write_report(
                report_path, findings, llm_model_type, llm_result.stats
            )
            logger.info(QCoreApplication.translate(
                "OutlineAuditWorker",
                "大纲审计复核完成：total {0} / fatal {1} / warning {2}",
            ).format(len(findings), fatal_count, warning_count))
            logger.info(QCoreApplication.translate(
                "OutlineAuditWorker", "审计报告已保存到: {0}"
            ).format(report_path))

            if fatal_count:
                message = QCoreApplication.translate(
                    "OutlineAuditWorker",
                    "大纲审计复核完成，发现 {0} 处 fatal 问题、{1} 处 warning。\n"
                    "LLM 复核候选任务 {2} 个，实际调用 {3} 次。\n报告已保存到:\n{4}",
                ).format(
                    fatal_count,
                    warning_count,
                    llm_result.stats.get("published_tasks", 0),
                    llm_result.stats.get("llm_calls", 0),
                    report_path,
                )
            else:
                message = QCoreApplication.translate(
                    "OutlineAuditWorker",
                    "大纲审计复核完成，未发现 fatal 问题，warning {0} 处。\n"
                    "LLM 复核候选任务 {1} 个，实际调用 {2} 次。\n报告已保存到:\n{3}",
                ).format(
                    warning_count,
                    llm_result.stats.get("published_tasks", 0),
                    llm_result.stats.get("llm_calls", 0),
                    report_path,
                )
            self.audit_finished.emit(True, message)

        except Exception as exc:
            error_msg = QCoreApplication.translate(
                "OutlineAuditWorker", "大纲审计复核失败: {0}"
            ).format(exc)
            logger.error(error_msg, exc_info=True)
            self.audit_finished.emit(False, error_msg)
        finally:
            if handler is not None:
                logging.getLogger().removeHandler(handler)
