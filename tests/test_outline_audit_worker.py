# -*- coding: utf-8 -*-
"""GUI 大纲审计 Worker 测试"""

import json
import os
from unittest.mock import MagicMock, patch

from src.generators.outline.outline_auditor import Finding, LLMReviewResult


def _write_outline(output_dir):
    os.makedirs(output_dir, exist_ok=True)
    outline_path = os.path.join(output_dir, "outline.json")
    with open(outline_path, "w", encoding="utf-8") as fp:
        json.dump([
            {
                "chapter_number": 1,
                "title": "第一章",
                "key_points": ["系统发布任务：清剿黑风寨"],
                "characters": ["主角"],
                "settings": ["山村"],
                "conflicts": ["匪患"],
                "foreshadowing": [],
            }
        ], fp, ensure_ascii=False)
    return outline_path


def _run_worker(worker):
    results = []
    worker.audit_finished.connect(lambda success, message: results.append((success, message)))
    worker.run()
    return results


class TestOutlineAuditWorker:
    """测试 OutlineAuditWorker 执行流程"""

    def test_worker_run_success_writes_report_and_uses_outline_model(self, mock_config, tmp_path):
        from src.gui.workers.outline_audit_worker import OutlineAuditWorker

        _write_outline(mock_config.output_config["output_dir"])
        config_path = str(tmp_path / "config.json")
        env_path = str(tmp_path / ".env")
        (tmp_path / "config.json").write_text("{}", encoding="utf-8")
        (tmp_path / ".env").write_text("", encoding="utf-8")

        algorithm_finding = Finding("O1", "warning", "伏笔", 1, "疑似伏笔未回收")
        llm_finding = Finding("O3-LLM", "fatal", "任务闭环", 1, "任务未闭环")
        mock_model = MagicMock()

        with patch("src.config.config.Config", return_value=mock_config), \
             patch("src.generators.common.utils.setup_logging"), \
             patch("src.gui.workers.outline_audit_worker.create_model", return_value=mock_model) as mock_create, \
             patch("src.generators.outline.outline_auditor.run_audit", return_value=[algorithm_finding]) as mock_run, \
             patch("src.generators.outline.outline_auditor.llm_review_task_closure_with_stats",
                   return_value=LLMReviewResult([llm_finding], {
                       "published_tasks": 1,
                       "skipped_tasks": 0,
                       "llm_reviewed_tasks": 1,
                       "llm_calls": 1,
                       "llm_findings": 1,
                       "llm_fatal_findings": 1,
                       "llm_warning_findings": 0,
                       "llm_call_failures": 0,
                       "llm_parse_failures": 0,
                       "closed_tasks": 0,
                       "open_tasks": 1,
                       "uncertain_tasks": 0,
                       "candidate_completion_chapters": 0,
                   })) as mock_llm:
            worker = OutlineAuditWorker(config_path=config_path, env_path=env_path)
            results = _run_worker(worker)

        assert results and results[0][0] is True
        assert "fatal" in results[0][1]
        mock_run.assert_called_once()
        mock_create.assert_called_once_with(
            mock_config.get_model_config("outline_model"),
            context="OutlineAuditWorker",
        )
        mock_llm.assert_called_once()
        assert mock_llm.call_args.args[1] is mock_model

        report_path = os.path.join(mock_config.output_config["output_dir"], "outline_audit_report.json")
        data = json.load(open(report_path, encoding="utf-8"))
        assert data["total"] == 2
        assert data["fatal"] == 1
        assert data["warning"] == 1
        assert data["llm_enabled"] is True
        assert data["llm_model_type"] == mock_config.get_model_config("outline_model")["type"]
        assert data["llm_stats"]["llm_calls"] == 1
        assert data["llm_stats"]["llm_findings"] == 1
        assert {item["rule"] for item in data["findings"]} == {"O1", "O3-LLM"}

    def test_missing_outline_returns_failure_without_audit(self, mock_config, tmp_path):
        from src.gui.workers.outline_audit_worker import OutlineAuditWorker

        config_path = str(tmp_path / "config.json")
        env_path = str(tmp_path / ".env")
        (tmp_path / "config.json").write_text("{}", encoding="utf-8")
        (tmp_path / ".env").write_text("", encoding="utf-8")

        with patch("src.config.config.Config", return_value=mock_config), \
             patch("src.generators.common.utils.setup_logging"), \
             patch("src.generators.outline.outline_auditor.run_audit") as mock_run:
            worker = OutlineAuditWorker(config_path=config_path, env_path=env_path)
            results = _run_worker(worker)

        assert results and results[0][0] is False
        assert "outline.json" in results[0][1]
        mock_run.assert_not_called()

    def test_outline_model_initialization_failure_returns_failure(self, mock_config, tmp_path):
        from src.gui.workers.outline_audit_worker import OutlineAuditWorker

        _write_outline(mock_config.output_config["output_dir"])
        config_path = str(tmp_path / "config.json")
        env_path = str(tmp_path / ".env")
        (tmp_path / "config.json").write_text("{}", encoding="utf-8")
        (tmp_path / ".env").write_text("", encoding="utf-8")

        with patch("src.config.config.Config", return_value=mock_config), \
             patch("src.generators.common.utils.setup_logging"), \
             patch("src.generators.outline.outline_auditor.run_audit", return_value=[]), \
             patch("src.gui.workers.outline_audit_worker.create_model",
                   side_effect=RuntimeError("model init failed")):
            worker = OutlineAuditWorker(config_path=config_path, env_path=env_path)
            results = _run_worker(worker)

        assert results and results[0][0] is False
        assert "model init failed" in results[0][1]

    def test_fatal_findings_are_successful_business_result(self, mock_config, tmp_path):
        from src.gui.workers.outline_audit_worker import OutlineAuditWorker

        _write_outline(mock_config.output_config["output_dir"])
        config_path = str(tmp_path / "config.json")
        env_path = str(tmp_path / ".env")
        (tmp_path / "config.json").write_text("{}", encoding="utf-8")
        (tmp_path / ".env").write_text("", encoding="utf-8")
        fatal = Finding("O3", "fatal", "任务闭环", 1, "任务未闭环")

        with patch("src.config.config.Config", return_value=mock_config), \
             patch("src.generators.common.utils.setup_logging"), \
             patch("src.gui.workers.outline_audit_worker.create_model", return_value=MagicMock()), \
             patch("src.generators.outline.outline_auditor.run_audit", return_value=[fatal]), \
             patch("src.generators.outline.outline_auditor.llm_review_task_closure_with_stats",
                   return_value=LLMReviewResult([], {
                       "published_tasks": 0,
                       "skipped_tasks": 0,
                       "llm_reviewed_tasks": 0,
                       "llm_calls": 0,
                       "llm_findings": 0,
                       "llm_fatal_findings": 0,
                       "llm_warning_findings": 0,
                       "llm_call_failures": 0,
                       "llm_parse_failures": 0,
                       "closed_tasks": 0,
                       "open_tasks": 0,
                       "uncertain_tasks": 0,
                       "candidate_completion_chapters": 0,
                   })):
            worker = OutlineAuditWorker(config_path=config_path, env_path=env_path)
            results = _run_worker(worker)

        assert results and results[0][0] is True
        report_path = os.path.join(mock_config.output_config["output_dir"], "outline_audit_report.json")
        data = json.load(open(report_path, encoding="utf-8"))
        assert data["fatal"] == 1
        assert data["llm_stats"]["llm_calls"] == 0
