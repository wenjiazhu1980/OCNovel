# -*- coding: utf-8 -*-
"""GUI 大纲修订 Worker 测试"""

import json
import os
from unittest.mock import MagicMock, patch


def _write_files(output_dir, with_outline=True, with_report=True):
    os.makedirs(output_dir, exist_ok=True)
    if with_outline:
        with open(os.path.join(output_dir, "outline.json"), "w", encoding="utf-8") as fp:
            json.dump([
                {
                    "chapter_number": 1,
                    "title": "第一章",
                    "key_points": ["系统发布任务：寻找黑风寨密信"],
                    "characters": ["主角"],
                    "settings": ["山路"],
                    "conflicts": [],
                    "foreshadowing": [],
                }
            ], fp, ensure_ascii=False)
    if with_report:
        with open(os.path.join(output_dir, "outline_audit_report.json"), "w", encoding="utf-8") as fp:
            json.dump({
                "total": 1,
                "fatal": 1,
                "warning": 0,
                "findings": [
                    {
                        "rule": "O3-LLM",
                        "severity": "fatal",
                        "chapter": 1,
                        "message": "任务未闭环",
                    }
                ],
            }, fp, ensure_ascii=False)


def _run_worker(worker):
    results = []
    worker.revision_finished.connect(lambda success, message: results.append((success, message)))
    worker.run()
    return results


class TestOutlineRevisionWorker:
    """测试 OutlineRevisionWorker 执行流程"""

    def test_worker_success_uses_outline_model_and_writes_report(self, mock_config, tmp_path):
        from src.gui.workers.outline_revision_worker import OutlineRevisionWorker

        _write_files(mock_config.output_config["output_dir"])
        config_path = str(tmp_path / "config.json")
        env_path = str(tmp_path / ".env")
        (tmp_path / "config.json").write_text("{}", encoding="utf-8")
        (tmp_path / ".env").write_text("", encoding="utf-8")
        mock_model = MagicMock()

        fake_report = {
            "stats": {"actionable_findings": 1, "requested_revisions": 1, "applied_revisions": 1, "changed_chapters": [1]},
            "backup_path": os.path.join(mock_config.output_config["output_dir"], "outline.json.bak.1"),
            "revision_report": os.path.join(mock_config.output_config["output_dir"], "outline_revision_report.json"),
        }

        with patch("src.config.config.Config", return_value=mock_config), \
             patch("src.generators.common.utils.setup_logging"), \
             patch("src.gui.workers.outline_revision_worker.create_model", return_value=mock_model) as mock_create, \
             patch("src.generators.outline.outline_reviser.revise_outline_file", return_value=fake_report) as mock_revise:
            worker = OutlineRevisionWorker(config_path=config_path, env_path=env_path)
            results = _run_worker(worker)

        assert results and results[0][0] is True
        assert "已修改" in results[0][1]
        mock_create.assert_called_once_with(
            mock_config.get_model_config("outline_model"),
            context="OutlineRevisionWorker",
        )
        mock_revise.assert_called_once()
        assert mock_revise.call_args.kwargs["model"] is mock_model
        assert mock_revise.call_args.kwargs["severities"] == ("fatal",)

    def test_missing_audit_report_returns_failure(self, mock_config, tmp_path):
        from src.gui.workers.outline_revision_worker import OutlineRevisionWorker

        _write_files(mock_config.output_config["output_dir"], with_outline=True, with_report=False)
        config_path = str(tmp_path / "config.json")
        env_path = str(tmp_path / ".env")
        (tmp_path / "config.json").write_text("{}", encoding="utf-8")
        (tmp_path / ".env").write_text("", encoding="utf-8")

        with patch("src.config.config.Config", return_value=mock_config), \
             patch("src.generators.common.utils.setup_logging"):
            worker = OutlineRevisionWorker(config_path=config_path, env_path=env_path)
            results = _run_worker(worker)

        assert results and results[0][0] is False
        assert "outline_audit_report.json" in results[0][1]

    def test_include_warning_passes_warning_severity(self, mock_config, tmp_path):
        from src.gui.workers.outline_revision_worker import OutlineRevisionWorker

        _write_files(mock_config.output_config["output_dir"])
        config_path = str(tmp_path / "config.json")
        env_path = str(tmp_path / ".env")
        (tmp_path / "config.json").write_text("{}", encoding="utf-8")
        (tmp_path / ".env").write_text("", encoding="utf-8")

        fake_report = {
            "stats": {"actionable_findings": 0, "requested_revisions": 0, "applied_revisions": 0, "changed_chapters": []},
            "backup_path": "",
            "revision_report": os.path.join(mock_config.output_config["output_dir"], "outline_revision_report.json"),
        }

        with patch("src.config.config.Config", return_value=mock_config), \
             patch("src.generators.common.utils.setup_logging"), \
             patch("src.gui.workers.outline_revision_worker.create_model", return_value=MagicMock()), \
             patch("src.generators.outline.outline_reviser.revise_outline_file", return_value=fake_report) as mock_revise:
            worker = OutlineRevisionWorker(
                config_path=config_path,
                env_path=env_path,
                include_warning=True,
            )
            results = _run_worker(worker)

        assert results and results[0][0] is True
        assert mock_revise.call_args.kwargs["severities"] == ("fatal", "warning")
