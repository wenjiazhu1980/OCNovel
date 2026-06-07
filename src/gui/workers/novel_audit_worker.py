"""后台整部小说内容审计 Worker:在 QThread 中执行章节正文审计。"""
import json
import logging
import os
import threading
import time

from PySide6.QtCore import QCoreApplication, QThread, Signal

from src.gui.utils.log_handler import SignalLogHandler
from src.gui.workers.model_factory import create_model


_DEBUG_SESSION_ID = "bda02d"
_DEBUG_LOG_PATH = "/Users/zzz/Codespace/OCNovel/.cursor/debug-bda02d.log"


def _debug_bda02d(hypothesis_id: str, location: str, message: str, data: dict | None = None) -> None:
    """写入本次调试会话的 NDJSON 运行证据。"""
    try:
        os.makedirs(os.path.dirname(_DEBUG_LOG_PATH), exist_ok=True)
        payload = {
            "sessionId": _DEBUG_SESSION_ID,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data or {},
            "timestamp": int(time.time() * 1000),
        }
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


class NovelAuditWorker(QThread):
    """后台执行整部小说章节内容审计。"""

    novel_audit_finished = Signal(bool, str)  # (success, message)
    log_message = Signal(str, str)            # (message, level)

    def __init__(
        self,
        config_path: str,
        env_path: str,
        chapter_numbers: list[int] | None = None,
        batch_size: int | None = None,
    ):
        super().__init__()
        self._config_path = config_path
        self._env_path = env_path
        if chapter_numbers is None:
            self._chapter_numbers = None
        else:
            normalized_chapters = []
            for value in chapter_numbers:
                try:
                    chapter_number = int(value)
                except (TypeError, ValueError):
                    continue
                if chapter_number > 0:
                    normalized_chapters.append(chapter_number)
            self._chapter_numbers = sorted(set(normalized_chapters))
        self._batch_size = batch_size
        self._stop_event = threading.Event()

    def stop(self) -> None:
        """请求停止审计（当前章节/相邻章检查完成后生效）。"""
        self._stop_event.set()

    def _resolve_output_dir(self, output_dir: str) -> str:
        """解析输出目录，兼容相对路径配置。"""
        if not output_dir:
            output_dir = os.path.join(os.path.dirname(self._config_path), "data", "output")
        if not os.path.isabs(output_dir):
            output_dir = os.path.join(os.path.dirname(self._config_path), output_dir)
        return output_dir

    def run(self) -> None:
        """执行整部小说内容审计并写出报告。"""
        logger = logging.getLogger("NovelAuditWorker")
        handler: SignalLogHandler | None = None

        try:
            if self._chapter_numbers == []:
                msg = QCoreApplication.translate("NovelAuditWorker", "未选择有效章节，已取消小说内容审计。")
                logger.info(msg)
                self.novel_audit_finished.emit(False, msg)
                return

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
            report_name = "content_audit_report_scope.json" if self._chapter_numbers else "content_audit_report.json"
            report_path = os.path.join(output_dir, report_name)

            if self._stop_event.is_set():
                msg = QCoreApplication.translate("NovelAuditWorker", "用户取消")
                logger.info(msg)
                self.novel_audit_finished.emit(False, msg)
                return

            if not os.path.exists(outline_path):
                raise FileNotFoundError(
                    QCoreApplication.translate(
                        "NovelAuditWorker",
                        "未找到 outline.json，请先生成大纲: {0}",
                    ).format(outline_path)
                )
            if not os.path.isdir(output_dir):
                raise FileNotFoundError(
                    QCoreApplication.translate(
                        "NovelAuditWorker",
                        "未找到输出目录，请先生成章节内容: {0}",
                    ).format(output_dir)
                )

            if self._chapter_numbers:
                scope_text = ", ".join(str(chapter) for chapter in self._chapter_numbers)
                logger.info(QCoreApplication.translate(
                    "NovelAuditWorker", "开始指定章节内容审计: {0}；章节: {1}"
                ).format(output_dir, scope_text))
            else:
                logger.info(QCoreApplication.translate(
                    "NovelAuditWorker", "开始整部小说内容审计: {0}"
                ).format(output_dir))

            content_model_config = dict(config.get_model_config("content_model"))
            llm_model_type = content_model_config.get("type", "unknown")
            original_reasoning_enabled = bool(content_model_config.get("reasoning_enabled", False))
            if original_reasoning_enabled:
                content_model_config["reasoning_enabled"] = False
                logger.info(QCoreApplication.translate(
                    "NovelAuditWorker",
                    "章节内容审计为结构化 JSON 任务，已临时关闭 content_model 推理输出以减少截断。",
                ))
            # region debug-bda02d
            _debug_bda02d(
                "H4",
                "src/gui/workers/novel_audit_worker.py:run:audit_model_config",
                "整部小说审计创建 content_model 前记录推理开关处理结果",
                {
                    "original_reasoning_enabled": original_reasoning_enabled,
                    "effective_reasoning_enabled": bool(content_model_config.get("reasoning_enabled", False)),
                    "model_type": llm_model_type,
                    "model_name_present": bool(content_model_config.get("model_name")),
                },
            )
            # endregion
            logger.info(QCoreApplication.translate(
                "NovelAuditWorker", "开始 LLM 章节内容审计（content_model）..."
            ))
            content_model = create_model(content_model_config, context="NovelAuditWorker")

            from src.generators.content.content_auditor import build_report, run_audit

            generation_config = getattr(config, "generation_config", {}) or {}
            if self._batch_size is not None:
                resolved_batch_size = self._batch_size
            else:
                resolved_batch_size = generation_config.get("content_audit_batch_size", 1)

            result = run_audit(
                output_dir=output_dir,
                outline_path=outline_path,
                model=content_model,
                stop_event=self._stop_event,
                chapter_numbers=self._chapter_numbers,
                batch_size=resolved_batch_size,
            )

            report = build_report(
                result=result,
                output_dir=output_dir,
                outline_path=outline_path,
                llm_enabled=True,
                llm_model_type=llm_model_type,
            )
            with open(report_path, "w", encoding="utf-8") as fp:
                json.dump(report, fp, ensure_ascii=False, indent=2)

            fatal_count = report["fatal"]
            warning_count = report["warning"]
            info_count = report["info"]
            llm_stats = result.stats

            logger.info(QCoreApplication.translate(
                "NovelAuditWorker",
                "章节内容审计完成：total {0} / fatal {1} / warning {2} / info {3}",
            ).format(report["total_findings"], fatal_count, warning_count, info_count))
            logger.info(QCoreApplication.translate(
                "NovelAuditWorker", "审计报告已保存到: {0}"
            ).format(report_path))

            if self._stop_event.is_set():
                message = QCoreApplication.translate(
                    "NovelAuditWorker",
                    "整部小说内容审计已停止，已写出当前进度报告。\n报告已保存到:\n{0}",
                ).format(report_path)
                self.novel_audit_finished.emit(False, message)
                return

            if fatal_count:
                message = QCoreApplication.translate(
                    "NovelAuditWorker",
                    "小说内容审计完成，发现 {0} 处 fatal 问题、{1} 处 warning、{2} 处 info。\n"
                    "已审计章节 {3} 章，LLM 调用 {4} 次。\n报告已保存到:\n{5}",
                ).format(
                    fatal_count,
                    warning_count,
                    info_count,
                    llm_stats.get("audited_chapters", 0),
                    llm_stats.get("llm_calls", 0),
                    report_path,
                )
            else:
                message = QCoreApplication.translate(
                    "NovelAuditWorker",
                    "小说内容审计完成，未发现 fatal 问题，warning {0} 处、info {1} 处。\n"
                    "已审计章节 {2} 章，LLM 调用 {3} 次。\n报告已保存到:\n{4}",
                ).format(
                    warning_count,
                    info_count,
                    llm_stats.get("audited_chapters", 0),
                    llm_stats.get("llm_calls", 0),
                    report_path,
                )
            self.novel_audit_finished.emit(True, message)

        except Exception as exc:
            error_msg = QCoreApplication.translate(
                "NovelAuditWorker", "整部小说内容审计失败: {0}"
            ).format(exc)
            logger.error(error_msg, exc_info=True)
            self.novel_audit_finished.emit(False, error_msg)
        finally:
            if handler is not None:
                logging.getLogger().removeHandler(handler)
