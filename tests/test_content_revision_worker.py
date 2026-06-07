# -*- coding: utf-8 -*-
"""GUI 章节内容修订 Worker 测试。"""

import json
import os
from unittest.mock import MagicMock, patch


def _write_files(output_dir, with_outline=True, with_report=True, scoped=True):
    os.makedirs(output_dir, exist_ok=True)
    if with_outline:
        with open(os.path.join(output_dir, "outline.json"), "w", encoding="utf-8") as fp:
            json.dump([
                {
                    "chapter_number": 1,
                    "title": "第一章",
                    "key_points": ["主角击退匪患"],
                    "characters": ["主角"],
                    "settings": ["山村"],
                    "conflicts": ["匪患"],
                }
            ], fp, ensure_ascii=False)
    if with_report:
        report_name = "content_audit_report_scope.json" if scoped else "content_audit_report.json"
        with open(os.path.join(output_dir, report_name), "w", encoding="utf-8") as fp:
            json.dump({
                "total_findings": 1,
                "fatal": 1,
                "warning": 0,
                "findings": [
                    {
                        "rule": "C1",
                        "severity": "fatal",
                        "chapter": 1,
                        "message": "正文未覆盖主线",
                    }
                ],
            }, fp, ensure_ascii=False)


def _run_worker(worker):
    results = []
    worker.content_revision_finished.connect(lambda success, message: results.append((success, message)))
    worker.run()
    return results


class TestContentRevisionWorker:
    """测试 ContentRevisionWorker 执行流程。"""

    def test_worker_success_uses_content_model_and_scope_report(self, mock_config, tmp_path):
        from src.gui.workers.content_revision_worker import ContentRevisionWorker

        _write_files(mock_config.output_config["output_dir"], scoped=True)
        config_path = str(tmp_path / "config.json")
        env_path = str(tmp_path / ".env")
        (tmp_path / "config.json").write_text("{}", encoding="utf-8")
        (tmp_path / ".env").write_text("", encoding="utf-8")
        mock_model = MagicMock()
        fake_report = {
            "stats": {
                "actionable_findings": 1,
                "requested_revisions": 1,
                "applied_revisions": 1,
                "written_revisions": 1,
                "changed_chapters": [1],
            },
            "backup_paths": {"1": os.path.join(mock_config.output_config["output_dir"], "第1章_第一章.txt.bak.1")},
            "revision_report": os.path.join(mock_config.output_config["output_dir"], "content_revision_report_scope.json"),
        }

        with patch("src.config.config.Config", return_value=mock_config), \
             patch("src.generators.common.utils.setup_logging"), \
             patch("src.gui.workers.content_revision_worker.create_model", return_value=mock_model) as mock_create, \
             patch("src.generators.content.content_reviser.revise_content_files", return_value=fake_report) as mock_revise:
            worker = ContentRevisionWorker(config_path=config_path, env_path=env_path)
            results = _run_worker(worker)

        assert results and results[0][0] is True
        assert "已写回" in results[0][1]
        mock_create.assert_called_once_with(
            mock_config.get_model_config("content_model"),
            context="ContentRevisionWorker",
        )
        mock_revise.assert_called_once()
        assert mock_revise.call_args.kwargs["model"] is mock_model
        assert mock_revise.call_args.kwargs["severities"] == ("fatal",)
        assert mock_revise.call_args.kwargs["audit_report_path"].endswith("content_audit_report_scope.json")

    def test_worker_missing_audit_report_returns_failure(self, mock_config, tmp_path):
        from src.gui.workers.content_revision_worker import ContentRevisionWorker

        _write_files(mock_config.output_config["output_dir"], with_outline=True, with_report=False)
        config_path = str(tmp_path / "config.json")
        env_path = str(tmp_path / ".env")
        (tmp_path / "config.json").write_text("{}", encoding="utf-8")
        (tmp_path / ".env").write_text("", encoding="utf-8")

        with patch("src.config.config.Config", return_value=mock_config), \
             patch("src.generators.common.utils.setup_logging"):
            worker = ContentRevisionWorker(config_path=config_path, env_path=env_path)
            results = _run_worker(worker)

        assert results and results[0][0] is False
        assert "内容审计报告" in results[0][1]

    def test_worker_include_warning_passes_warning_severity(self, mock_config, tmp_path):
        from src.gui.workers.content_revision_worker import ContentRevisionWorker

        _write_files(mock_config.output_config["output_dir"], scoped=False)
        config_path = str(tmp_path / "config.json")
        env_path = str(tmp_path / ".env")
        (tmp_path / "config.json").write_text("{}", encoding="utf-8")
        (tmp_path / ".env").write_text("", encoding="utf-8")
        fake_report = {
            "stats": {
                "actionable_findings": 0,
                "requested_revisions": 0,
                "applied_revisions": 0,
                "written_revisions": 0,
                "changed_chapters": [],
            },
            "backup_paths": {},
            "revision_report": os.path.join(mock_config.output_config["output_dir"], "content_revision_report.json"),
        }

        with patch("src.config.config.Config", return_value=mock_config), \
             patch("src.generators.common.utils.setup_logging"), \
             patch("src.gui.workers.content_revision_worker.create_model", return_value=MagicMock()), \
             patch("src.generators.content.content_reviser.revise_content_files", return_value=fake_report) as mock_revise:
            worker = ContentRevisionWorker(
                config_path=config_path,
                env_path=env_path,
                include_warning=True,
            )
            results = _run_worker(worker)

        assert results and results[0][0] is True
        assert mock_revise.call_args.kwargs["severities"] == ("fatal", "warning")
