# -*- coding: utf-8 -*-
"""章节内容审计修订核心测试。"""

import json
import os
from unittest.mock import MagicMock

from src.generators.content.content_reviser import (
    parse_revision_response,
    resolve_content_audit_report_path,
    revise_content_files,
    revise_content_from_audit,
    select_actionable_findings,
)


def _write_outline(output_dir):
    outline_path = os.path.join(output_dir, "outline.json")
    with open(outline_path, "w", encoding="utf-8") as fp:
        json.dump([
            {
                "chapter_number": 1,
                "title": "第一章",
                "key_points": ["主角在山村击退匪患"],
                "characters": ["主角"],
                "settings": ["山村"],
                "conflicts": ["匪患"],
            },
            {
                "chapter_number": 2,
                "title": "第二章",
                "key_points": ["主角进城调查线索"],
                "characters": ["主角"],
                "settings": ["县城"],
                "conflicts": ["线索断裂"],
            },
        ], fp, ensure_ascii=False)
    return outline_path


def _write_chapter(output_dir, chapter=1, title="第一章", content="旧正文"):
    path = os.path.join(output_dir, f"第{chapter}章_{title}.txt")
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(content)
    return path


def _audit_report(chapter_path):
    return {
        "total_findings": 4,
        "fatal": 2,
        "warning": 1,
        "findings": [
            {
                "rule": "C1",
                "severity": "fatal",
                "chapter": 1,
                "message": "正文没有体现击退匪患主线",
                "evidence": {"content_path": chapter_path, "reason": "主线缺失"},
            },
            {
                "rule": "C0",
                "severity": "fatal",
                "chapter": 3,
                "message": "缺少第3章正文",
            },
            {
                "rule": "C2",
                "severity": "warning",
                "chapter": 2,
                "message": "转场略生硬",
            },
            {
                "rule": "C1",
                "severity": "info",
                "chapter": 1,
                "message": "低风险提示",
            },
        ],
    }


def _revision_json(
    chapter=1,
    old_text="旧正文：主角没有处理匪患。",
    new_text="旧正文：主角在山村击退匪患。",
):
    return json.dumps({
        "summary": "补齐主线事件",
        "revisions": [
            {
                "chapter_number": chapter,
                "reason": "修复 C1 fatal",
                "finding_refs": ["C1@1"],
                "edits": [
                    {
                        "old_text": old_text,
                        "new_text": new_text,
                    }
                ],
            }
        ],
    }, ensure_ascii=False)


def test_resolve_content_audit_report_prefers_explicit_then_scope(tmp_path):
    output_dir = str(tmp_path)
    full = tmp_path / "content_audit_report.json"
    scoped = tmp_path / "content_audit_report_scope.json"
    explicit = tmp_path / "custom_report.json"
    full.write_text("{}", encoding="utf-8")

    assert resolve_content_audit_report_path(output_dir) == str(full)

    scoped.write_text("{}", encoding="utf-8")
    assert resolve_content_audit_report_path(output_dir) == str(scoped)
    assert resolve_content_audit_report_path(output_dir, str(explicit)) == str(explicit)


def test_select_actionable_findings_defaults_to_fatal_c1_c2_only(tmp_path):
    path = str(tmp_path / "第1章_第一章.txt")

    selected = select_actionable_findings(_audit_report(path))

    assert len(selected) == 1
    assert selected[0]["rule"] == "C1"
    assert selected[0]["severity"] == "fatal"


def test_parse_revision_response_accepts_fenced_json():
    raw = "模型说明\n```json\n" + _revision_json() + "\n```\n"

    summary, revisions = parse_revision_response(raw)

    assert summary == "补齐主线事件"
    assert len(revisions) == 1
    assert revisions[0].chapter_number == 1
    assert revisions[0].edits == [{"old_text": "旧正文：主角没有处理匪患。", "new_text": "旧正文：主角在山村击退匪患。"}]


def test_revise_content_files_dry_run_writes_report_but_not_chapter(tmp_path):
    output_dir = str(tmp_path)
    _write_outline(output_dir)
    chapter_path = _write_chapter(output_dir, content="旧正文：主角没有处理匪患。")
    audit_path = tmp_path / "content_audit_report.json"
    audit_path.write_text(json.dumps(_audit_report(chapter_path), ensure_ascii=False), encoding="utf-8")
    report_path = tmp_path / "content_revision_report.json"
    model = MagicMock()
    model.generate.return_value = _revision_json()

    report = revise_content_files(
        output_dir=output_dir,
        model=model,
        audit_report_path=str(audit_path),
        output_report_path=str(report_path),
        dry_run=True,
    )

    assert os.path.exists(report_path)
    assert "旧正文" in open(chapter_path, encoding="utf-8").read()
    assert list(tmp_path.glob("*.bak.*")) == []
    assert report["dry_run"] is True
    assert report["backup_paths"] == {}
    assert report["stats"]["applied_revisions"] == 1
    assert report["stats"]["written_revisions"] == 0
    assert report["skipped_findings"][0]["finding"]["rule"] == "C0"


def test_revise_content_files_backs_up_and_overwrites_original_chapter(tmp_path):
    output_dir = str(tmp_path)
    _write_outline(output_dir)
    chapter_path = _write_chapter(output_dir, content="旧正文：主角没有处理匪患。")
    audit_path = tmp_path / "content_audit_report.json"
    audit_path.write_text(json.dumps(_audit_report(chapter_path), ensure_ascii=False), encoding="utf-8")
    model = MagicMock()
    model.generate.return_value = _revision_json(new_text="旧正文：主角在山村击退匪患，救下村民。")

    report = revise_content_files(output_dir=output_dir, model=model, audit_report_path=str(audit_path))

    updated = open(chapter_path, encoding="utf-8").read()
    assert "救下村民" in updated
    assert report["stats"]["written_revisions"] == 1
    assert report["stats"]["changed_chapters"] == [1]
    backup_path = report["backup_paths"]["1"]
    assert os.path.exists(backup_path)
    assert "旧正文" in open(backup_path, encoding="utf-8").read()


def test_revise_content_from_audit_records_invalid_model_revision(tmp_path):
    output_dir = str(tmp_path)
    outline_path = _write_outline(output_dir)
    chapter_path = _write_chapter(output_dir, content="旧正文：主角没有处理匪患。")
    report = _audit_report(chapter_path)
    model = MagicMock()
    model.generate.return_value = _revision_json(chapter=99, new_text="错误章节正文")

    result = revise_content_from_audit(output_dir, outline_path, report, model)

    assert result.revisions == []
    assert result.stats["failed_revisions"] == 1
    assert result.failed_revisions[0]["reason"] == "no_target_revision"
    assert result.failed_revisions[0]["returned_chapters"] == [99]


def test_revise_content_rejects_edit_not_found_in_original(tmp_path):
    output_dir = str(tmp_path)
    outline_path = _write_outline(output_dir)
    chapter_path = _write_chapter(output_dir, content="旧正文：主角没有处理匪患。")
    report = _audit_report(chapter_path)
    model = MagicMock()
    model.generate.return_value = _revision_json(
        old_text="模型凭空写的不存在片段",
        new_text="模型凭空写的新片段",
    )

    result = revise_content_from_audit(output_dir, outline_path, report, model)

    assert result.revisions == []
    assert result.failed_revisions[0]["reason"] == "old_text_not_found"


def test_revise_content_rejects_full_content_response(tmp_path):
    output_dir = str(tmp_path)
    outline_path = _write_outline(output_dir)
    chapter_path = _write_chapter(output_dir, content="旧正文：主角没有处理匪患。")
    report = _audit_report(chapter_path)
    model = MagicMock()
    model.generate.return_value = json.dumps({
        "summary": "尝试整章重写",
        "revisions": [
            {
                "chapter_number": 1,
                "reason": "错误地返回完整正文",
                "content": "新正文：这是模型重新生成的一整章。",
            }
        ],
    }, ensure_ascii=False)

    result = revise_content_from_audit(output_dir, outline_path, report, model)

    assert result.revisions == []
    assert result.failed_revisions[0]["reason"] == "missing_precise_edits"
