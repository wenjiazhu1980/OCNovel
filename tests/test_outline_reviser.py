# -*- coding: utf-8 -*-
"""大纲审计修订核心与 CLI 测试"""

import json
from unittest.mock import MagicMock, patch

from src.generators.outline.outline_reviser import (
    _build_revision_prompt,
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


def _large_outline(n=200):
    """构造字段较饱满的大纲，模拟真实 400 章规模下单章 compact 后的体积。"""
    chapters = []
    for i in range(1, n + 1):
        chapters.append({
            "chapter_number": i,
            "title": f"第{i}章标题",
            "key_points": [
                f"关键点{i}-{j}：一段足够长的章节关键情节描述文字用来撑大上下文体积测试"
                for j in range(12)
            ],
            "characters": [f"角色{k}号人物" for k in range(6)],
            "settings": [f"场景地点{i}"],
            "conflicts": [f"核心冲突{i}", f"次要冲突{i}"],
            "foreshadowing": [f"伏笔线索{i}-{j}" for j in range(5)],
        })
    return chapters


def test_build_revision_prompt_respects_char_budget_with_many_fatal():
    """大量 fatal（上下文章节累加爆炸）时 prompt 不应超过模型层 65536 硬截断。

    回归：400 章规模下 7 个 O3-LLM fatal 累加上下文达 59 章，prompt 撑到 ~90K，
    被 openai_model 砍尾部 27%，恰好丢掉末尾 [输出格式] 说明 → 修订响应无法解析。
    修复后 context 受字符预算约束、输出格式前置，prompt 落在硬截断线内且核心章节保留。
    """
    chapters = _large_outline(200)
    core_chapters = [10, 35, 60, 85, 110, 135, 160, 185]
    findings = [
        {
            "rule": "O3-LLM",
            "severity": "fatal",
            "chapter": c,
            "message": f"第{c}章发布的系统任务长期未闭环，需要补收束动作",
            "evidence": {"candidate_chapters": list(range(c, c + 20))},
        }
        for c in core_chapters
    ]

    prompt = _build_revision_prompt(chapters, findings)

    # 不触发模型层 65536 硬截断
    assert len(prompt) <= 65536, f"prompt 长度 {len(prompt)} 仍超过硬截断线"
    # 关键指令与输出格式不被丢弃（截断曾砍掉这块）
    assert "输出格式" in prompt
    assert '"summary"' in prompt
    assert '"revisions"' in prompt
    # 每个 fatal 的核心章节仍保留在上下文中（保证可被修订）
    for c in core_chapters:
        assert f'"chapter_number": {c}' in prompt, f"核心章节 {c} 被裁掉了"


def test_build_revision_prompt_small_input_unchanged_behavior():
    """小规模输入不触发裁剪：上下文章节与输出格式都完整。"""
    chapters = _large_outline(10)
    findings = [{
        "rule": "O3-LLM", "severity": "fatal", "chapter": 3,
        "message": "第3章任务未闭环",
        "evidence": {"candidate_chapters": [4, 5]},
    }]

    prompt = _build_revision_prompt(chapters, findings)

    assert len(prompt) <= 65536
    assert "输出格式" in prompt
    assert '"chapter_number": 3' in prompt
