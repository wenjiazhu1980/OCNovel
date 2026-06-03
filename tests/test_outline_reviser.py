# -*- coding: utf-8 -*-
"""大纲审计修订核心与 CLI 测试"""

import json
from unittest.mock import MagicMock, patch

from src.generators.outline.outline_reviser import (
    apply_revisions,
    parse_revision_response,
    revise_outline_file,
    revise_outline_from_audit,
    select_actionable_findings,
)
from tools.revise_outline_from_audit import main as revise_cli_main


def _chapters():
    return [
        {
            "chapter_number": 1,
            "title": "第一章",
            "key_points": ["系统发布任务：寻找黑风寨密信"],
            "characters": ["主角"],
            "settings": ["山路"],
            "conflicts": ["密信未明"],
            "foreshadowing": [],
        },
        {
            "chapter_number": 2,
            "title": "第二章",
            "key_points": ["主角继续赶路"],
            "characters": ["主角"],
            "settings": ["山路"],
            "conflicts": [],
            "foreshadowing": [],
        },
    ]


def _audit_report():
    return {
        "total": 2,
        "fatal": 1,
        "warning": 1,
        "findings": [
            {
                "rule": "O3-LLM",
                "severity": "fatal",
                "chapter": 1,
                "message": "第1章发布的任务未闭环：寻找黑风寨密信",
                "evidence": {"task_description": "寻找黑风寨密信", "candidate_chapters": [2]},
            },
            {
                "rule": "O2",
                "severity": "warning",
                "chapter": 1,
                "message": "实体消失",
            },
        ],
    }


def _revision_json():
    return json.dumps({
        "summary": "补充密信任务闭环",
        "revisions": [
            {
                "chapter_number": 2,
                "reason": "补上第1章任务收束",
                "finding_refs": ["O3-LLM@1"],
                "fields": {
                    "key_points": ["主角找到黑风寨密信，任务完成，确认后续追查方向。"],
                    "foreshadowing": ["回收：第1章寻找黑风寨密信任务，本章正式办结。"],
                },
            }
        ],
    }, ensure_ascii=False)


def test_select_actionable_findings_defaults_to_fatal_only():
    selected = select_actionable_findings(_audit_report())

    assert len(selected) == 1
    assert selected[0]["severity"] == "fatal"


def test_parse_revision_response_and_apply_revisions():
    _, revisions = parse_revision_response(_revision_json())
    revised, applied = apply_revisions(_chapters(), revisions)

    assert len(applied) == 1
    assert revised[1]["key_points"] == ["主角找到黑风寨密信，任务完成，确认后续追查方向。"]
    assert "正式办结" in revised[1]["foreshadowing"][0]


def test_revise_outline_from_audit_calls_model_with_temperature_zero():
    model = MagicMock()
    model.generate.return_value = _revision_json()

    result = revise_outline_from_audit(_chapters(), _audit_report(), model)

    assert result.stats["model_called"] is True
    assert result.stats["actionable_findings"] == 1
    assert result.stats["applied_revisions"] == 1
    assert result.stats["changed_chapters"] == [2]
    assert model.generate.call_args.kwargs["temperature"] == 0


def test_revise_outline_batches_large_audit_prompt_under_model_limit():
    chapters = []
    for n in range(1, 80):
        chapters.append({
            "chapter_number": n,
            "title": f"第{n}章",
            "key_points": ["主角追查黑风寨密信。" + ("长上下文" * 300)],
            "characters": ["主角"],
            "settings": ["山路"],
            "conflicts": ["线索未明"],
            "foreshadowing": ["埋设：黑风寨密信仍未回收。" + ("证据" * 200)],
        })
    findings = []
    for idx in range(1, 25):
        findings.append({
            "rule": "O3-LLM",
            "severity": "fatal",
            "chapter": idx,
            "message": "第{0}章发布的任务未闭环：寻找黑风寨密信。".format(idx) + ("说明" * 400),
            "evidence": {
                "task_description": "寻找黑风寨密信",
                "candidate_chapters": list(range(idx + 1, 79)),
                "last_context": "候选上下文" * 500,
            },
        })
    audit_report = {"findings": findings}
    model = MagicMock()
    model.generate.return_value = json.dumps({"summary": "无需修订", "revisions": []}, ensure_ascii=False)

    result = revise_outline_from_audit(chapters, audit_report, model)

    assert result.stats["revision_batches"] == 3
    assert model.generate.call_count == 3
    for call in model.generate.call_args_list:
        assert len(call.args[0]) < 65536
        assert call.kwargs["temperature"] == 0


def test_revise_outline_file_writes_backup_outline_and_report(tmp_path):
    outline_path = tmp_path / "outline.json"
    audit_path = tmp_path / "outline_audit_report.json"
    report_path = tmp_path / "outline_revision_report.json"
    outline_path.write_text(json.dumps(_chapters(), ensure_ascii=False), encoding="utf-8")
    audit_path.write_text(json.dumps(_audit_report(), ensure_ascii=False), encoding="utf-8")
    model = MagicMock()
    model.generate.return_value = _revision_json()

    report = revise_outline_file(
        str(outline_path),
        str(audit_path),
        model,
        output_report_path=str(report_path),
    )

    updated = json.loads(outline_path.read_text(encoding="utf-8"))
    assert "任务完成" in updated[1]["key_points"][0]
    assert report["backup_path"]
    assert report_path.exists()
    assert report["stats"]["applied_revisions"] == 1


def test_revise_outline_file_dry_run_does_not_write_outline(tmp_path):
    outline_path = tmp_path / "outline.json"
    audit_path = tmp_path / "outline_audit_report.json"
    original = json.dumps(_chapters(), ensure_ascii=False)
    outline_path.write_text(original, encoding="utf-8")
    audit_path.write_text(json.dumps(_audit_report(), ensure_ascii=False), encoding="utf-8")
    model = MagicMock()
    model.generate.return_value = _revision_json()

    report = revise_outline_file(str(outline_path), str(audit_path), model, dry_run=True)

    assert outline_path.read_text(encoding="utf-8") == original
    assert report["backup_path"] == ""
    assert report["dry_run"] is True


def test_cli_revise_outline_dry_run_json(tmp_path, capsys):
    outline_path = tmp_path / "outline.json"
    audit_path = tmp_path / "outline_audit_report.json"
    config_path = tmp_path / "config.json"
    outline_path.write_text(json.dumps(_chapters(), ensure_ascii=False), encoding="utf-8")
    audit_path.write_text(json.dumps(_audit_report(), ensure_ascii=False), encoding="utf-8")
    config_path.write_text("{}", encoding="utf-8")
    model = MagicMock()
    model.generate.return_value = _revision_json()

    with patch("tools.revise_outline_from_audit._build_outline_model", return_value=model):
        rc = revise_cli_main([
            "--outline", str(outline_path),
            "--audit-report", str(audit_path),
            "--config", str(config_path),
            "--dry-run",
            "--json",
        ])

    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert data["dry_run"] is True
    assert data["stats"]["applied_revisions"] == 1
