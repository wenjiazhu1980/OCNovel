# -*- coding: utf-8 -*-
"""GUI 整部小说内容审计 Worker 测试。"""

import json
import os
from unittest.mock import MagicMock, patch

from src.generators.content.content_auditor import Finding, LLMReviewResult


def _write_outline_and_chapter(output_dir):
    os.makedirs(output_dir, exist_ok=True)
    outline_path = os.path.join(output_dir, "outline.json")
    with open(outline_path, "w", encoding="utf-8") as fp:
        json.dump([
            {
                "chapter_number": 1,
                "title": "第一章",
                "key_points": ["主角完成第一章关键事件"],
                "characters": ["主角"],
                "settings": ["山村"],
                "conflicts": ["匪患"],
            }
        ], fp, ensure_ascii=False)
    with open(os.path.join(output_dir, "第1章_第一章.txt"), "w", encoding="utf-8") as fp:
        fp.write("主角完成第一章关键事件。")
    return outline_path


def _run_worker(worker):
    results = []
    worker.novel_audit_finished.connect(lambda success, message: results.append((success, message)))
    worker.run()
    return results


class TestNovelAuditWorker:
    """测试 NovelAuditWorker 执行流程。"""

    def test_worker_run_success_writes_report_and_uses_content_model(self, mock_config, tmp_path):
        from src.gui.workers.novel_audit_worker import NovelAuditWorker

        _write_outline_and_chapter(mock_config.output_config["output_dir"])
        config_path = str(tmp_path / "config.json")
        env_path = str(tmp_path / ".env")
        (tmp_path / "config.json").write_text("{}", encoding="utf-8")
        (tmp_path / ".env").write_text("", encoding="utf-8")

        finding = Finding("C1", "warning", "章节正文与大纲一致性", 1, "展开略弱")
        mock_model = MagicMock()
        result = LLMReviewResult([finding], {
            "outline_chapters": 1,
            "audited_chapters": 1,
            "missing_chapters": 0,
            "chapter_checks": 1,
            "transition_checks": 0,
            "llm_calls": 1,
        })

        with patch("src.config.config.Config", return_value=mock_config), \
             patch("src.generators.common.utils.setup_logging"), \
             patch("src.gui.workers.novel_audit_worker.create_model", return_value=mock_model) as mock_create, \
             patch("src.generators.content.content_auditor.run_audit", return_value=result) as mock_run:
            worker = NovelAuditWorker(config_path=config_path, env_path=env_path)
            results = _run_worker(worker)

        assert results and results[0][0] is True
        assert "整部小说内容审计完成" in results[0][1]
        mock_create.assert_called_once_with(
            mock_config.get_model_config("content_model"),
            context="NovelAuditWorker",
        )
        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["model"] is mock_model

        report_path = os.path.join(mock_config.output_config["output_dir"], "content_audit_report.json")
        data = json.load(open(report_path, encoding="utf-8"))
        assert data["total_findings"] == 1
        assert data["fatal"] == 0
        assert data["warning"] == 1
        assert data["llm_enabled"] is True
        assert data["llm_model_type"] == mock_config.get_model_config("content_model")["type"]
        assert data["llm_stats"]["llm_calls"] == 1
        assert data["findings"][0]["rule"] == "C1"

    def test_missing_outline_returns_failure_without_audit(self, mock_config, tmp_path):
        from src.gui.workers.novel_audit_worker import NovelAuditWorker

        config_path = str(tmp_path / "config.json")
        env_path = str(tmp_path / ".env")
        (tmp_path / "config.json").write_text("{}", encoding="utf-8")
        (tmp_path / ".env").write_text("", encoding="utf-8")

        with patch("src.config.config.Config", return_value=mock_config), \
             patch("src.generators.common.utils.setup_logging"), \
             patch("src.generators.content.content_auditor.run_audit") as mock_run:
            worker = NovelAuditWorker(config_path=config_path, env_path=env_path)
            results = _run_worker(worker)

        assert results and results[0][0] is False
        assert "outline.json" in results[0][1]
        mock_run.assert_not_called()

    def test_content_model_initialization_failure_returns_failure(self, mock_config, tmp_path):
        from src.gui.workers.novel_audit_worker import NovelAuditWorker

        _write_outline_and_chapter(mock_config.output_config["output_dir"])
        config_path = str(tmp_path / "config.json")
        env_path = str(tmp_path / ".env")
        (tmp_path / "config.json").write_text("{}", encoding="utf-8")
        (tmp_path / ".env").write_text("", encoding="utf-8")

        with patch("src.config.config.Config", return_value=mock_config), \
             patch("src.generators.common.utils.setup_logging"), \
             patch("src.gui.workers.novel_audit_worker.create_model", side_effect=RuntimeError("model init failed")):
            worker = NovelAuditWorker(config_path=config_path, env_path=env_path)
            results = _run_worker(worker)

        assert results and results[0][0] is False
        assert "model init failed" in results[0][1]
