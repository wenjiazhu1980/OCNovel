# -*- coding: utf-8 -*-
"""章节内容审计器测试。"""

import json
import os

from src.generators.content.content_auditor import (
    CONTENT_AUDIT_PROMPT_MAX_CHARS,
    Finding,
    build_report,
    find_chapter_candidates,
    load_outline_map,
    run_audit,
    serialize_finding,
)


class QueueModel:
    """按顺序返回预设 JSON 的模型桩。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def generate(self, prompt: str, **kwargs) -> str:
        self.prompts.append(prompt)
        if self.responses:
            return self.responses.pop(0)
        return '{"findings": []}'


def _write_outline(output_dir, data):
    path = os.path.join(output_dir, "outline.json")
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False)
    return path


def _write_chapter(output_dir, chapter_number: int, title: str, content: str):
    path = os.path.join(output_dir, f"第{chapter_number}章_{title}.txt")
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(content)
    return path


def _chapter(chapter_number: int, title: str):
    return {
        "chapter_number": chapter_number,
        "title": title,
        "key_points": [f"第{chapter_number}章关键事件"],
        "characters": ["林小凡"],
        "settings": ["青云宗"],
        "conflicts": ["外门冲突"],
    }


class TestContentAuditor:
    """测试章节内容审计核心。"""

    def test_serialize_finding_aligns_report_schema(self):
        finding = Finding("C1", "fatal", "章节正文与大纲一致性", 1, "关键事件缺失", {"reason": "未出现"})

        data = serialize_finding(finding)

        assert data == {
            "rule": "C1",
            "severity": "fatal",
            "title": "章节正文与大纲一致性",
            "chapter": 1,
            "message": "关键事件缺失",
            "evidence": {"reason": "未出现"},
        }

    def test_load_outline_map_supports_wrapped_sparse_and_duplicates(self, tmp_path):
        outline_path = _write_outline(tmp_path, {
            "chapters": [
                _chapter(1, "起势"),
                None,
                _chapter(3, "转折"),
                _chapter(3, "重复"),
                "bad-item",
            ]
        })

        outline_map, findings, stats = load_outline_map(str(outline_path))

        assert sorted(outline_map) == [1, 3]
        assert stats["outline_chapters"] == 2
        assert stats["duplicate_outline_chapters"] == 1
        assert stats["non_dict_outline_items"] == 1
        assert any(f.severity == "fatal" and f.chapter == 2 for f in findings)
        assert any("重复 chapter_number=3" in f.message for f in findings)

    def test_find_chapter_candidates_excludes_non_content_files_and_prefers_outline_title(self, tmp_path):
        output_dir = str(tmp_path)
        expected = _write_chapter(output_dir, 1, "当前标题", "正文")
        _write_chapter(output_dir, 1, "旧标题", "旧正文")
        _write_chapter(output_dir, 1, "摘要", "摘要")
        (tmp_path / "第1章_当前标题_imitated.txt").write_text("仿写", encoding="utf-8")
        (tmp_path / "第1章_当前标题_original.txt").write_text("原文", encoding="utf-8")

        candidates = find_chapter_candidates(output_dir, 1, {"title": "当前标题"})

        assert candidates[0] == expected
        assert all("_imitated" not in path for path in candidates)
        assert all("_original" not in path for path in candidates)
        assert all("_摘要" not in path for path in candidates)

    def test_run_audit_calls_llm_for_chapters_and_transitions(self, tmp_path):
        output_dir = str(tmp_path)
        outline_path = _write_outline(tmp_path, [_chapter(1, "起势"), _chapter(2, "承接")])
        _write_chapter(output_dir, 1, "起势", "# 第一章\n林小凡完成第1章关键事件，夜色里准备继续前进。")
        _write_chapter(output_dir, 2, "承接", "第二章开头自然承接夜色，林小凡继续前进并完成第2章关键事件。")
        model = QueueModel([
            '{"findings": []}',
            '{"findings": [{"severity": "warning", "message": "第2章关键点略显仓促", "evidence": {"reason": "展开不足"}}]}',
            '{"findings": [{"severity": "fatal", "message": "章节衔接存在时间线冲突", "evidence": {"reason": "昼夜跳变"}}]}',
        ])

        result = run_audit(output_dir, outline_path=str(outline_path), model=model)
        report = build_report(result, output_dir, str(outline_path), llm_enabled=True, llm_model_type="mock")

        assert result.stats["audited_chapters"] == 2
        assert result.stats["chapter_checks"] == 2
        assert result.stats["transition_checks"] == 1
        assert result.stats["llm_calls"] == 3
        assert report["fatal"] == 1
        assert report["warning"] == 1
        assert {item["rule"] for item in report["findings"]} == {"C1", "C2"}

    def test_run_audit_without_model_only_runs_input_precheck(self, tmp_path):
        output_dir = str(tmp_path)
        outline_path = _write_outline(tmp_path, [_chapter(1, "缺正文")])

        result = run_audit(output_dir, outline_path=str(outline_path), model=None)

        assert result.stats["llm_calls"] == 0
        assert result.stats["missing_chapters"] == 1
        assert any(f.rule_id == "C0" and f.severity == "fatal" for f in result.findings)

    def test_run_audit_selected_chapter_uses_boundary_context(self, tmp_path):
        output_dir = str(tmp_path)
        outline_path = _write_outline(tmp_path, [_chapter(1, "起势"), _chapter(2, "承接"), _chapter(3, "转折")])
        _write_chapter(output_dir, 1, "起势", "第一章结尾，林小凡踏入夜色。")
        _write_chapter(output_dir, 2, "承接", "第二章开头承接夜色，林小凡完成第2章关键事件。")
        _write_chapter(output_dir, 3, "转折", "第三章正文。")
        model = QueueModel([
            '{"findings": []}',
            '{"findings": [{"severity": "warning", "message": "过渡略快"}]}',
        ])

        result = run_audit(output_dir, outline_path=str(outline_path), model=model, chapter_numbers=[2])

        assert result.stats["requested_chapters"] == 1
        assert result.stats["selected_chapters"] == 1
        assert result.stats["context_chapters_loaded"] == 1
        assert result.stats["audited_chapters"] == 1
        assert result.stats["chapter_checks"] == 1
        assert result.stats["transition_checks"] == 1
        assert result.stats["llm_calls"] == 2
        assert result.audit_scope["mode"] == "selected"
        assert result.audit_scope["requested_chapters"] == [2]
        assert all(f.chapter == 2 for f in result.findings if f.rule_id in {"C1", "C2"})

    def test_run_audit_selected_chapter_reports_missing_previous_context(self, tmp_path):
        output_dir = str(tmp_path)
        outline_path = _write_outline(tmp_path, [_chapter(1, "起势"), _chapter(2, "承接")])
        _write_chapter(output_dir, 2, "承接", "第二章正文，林小凡完成第2章关键事件。")
        model = QueueModel(['{"findings": []}'])

        result = run_audit(output_dir, outline_path=str(outline_path), model=model, chapter_numbers=[2])

        assert result.stats["chapter_checks"] == 1
        assert result.stats["transition_checks"] == 0
        assert result.stats["llm_calls"] == 1
        assert any(
            finding.rule_id == "C0"
            and finding.severity == "warning"
            and finding.chapter == 2
            and "无法检查第 1 章到第 2 章衔接" in finding.message
            for finding in result.findings
        )

    def test_run_audit_selected_first_chapter_has_no_transition(self, tmp_path):
        output_dir = str(tmp_path)
        outline_path = _write_outline(tmp_path, [_chapter(1, "起势"), _chapter(2, "承接")])
        _write_chapter(output_dir, 1, "起势", "第一章正文，林小凡完成第1章关键事件。")
        _write_chapter(output_dir, 2, "承接", "第二章正文。")
        model = QueueModel(['{"findings": []}'])

        result = run_audit(output_dir, outline_path=str(outline_path), model=model, chapter_numbers=[1])

        assert result.stats["chapter_checks"] == 1
        assert result.stats["transition_checks"] == 0
        assert result.stats["llm_calls"] == 1

    def test_run_audit_selected_missing_outline_does_not_call_llm(self, tmp_path):
        output_dir = str(tmp_path)
        outline_path = _write_outline(tmp_path, [_chapter(1, "起势")])
        _write_chapter(output_dir, 1, "起势", "第一章正文。")
        model = QueueModel(['{"findings": []}'])

        result = run_audit(output_dir, outline_path=str(outline_path), model=model, chapter_numbers=[99])

        assert result.stats["selection_missing_outline_chapters"] == 1
        assert result.stats["llm_calls"] == 0
        assert any(f.rule_id == "C0" and f.chapter == 99 for f in result.findings)

    def test_run_audit_batches_chapters_and_transitions(self, tmp_path):
        output_dir = str(tmp_path)
        chapters = [_chapter(index, f"第{index}章") for index in range(1, 6)]
        outline_path = _write_outline(tmp_path, chapters)
        for index in range(1, 6):
            _write_chapter(output_dir, index, f"第{index}章", f"第{index}章正文，完成第{index}章关键事件。")
        model = QueueModel([
            '{"findings": [{"rule": "C1", "chapter": 2, "severity": "warning", "message": "第2章展开不足"}]}',
            '{"findings": []}',
            '{"findings": []}',
            '{"findings": [{"rule": "C2", "chapter": 3, "severity": "fatal", "message": "第2到第3章断裂"}]}',
            '{"findings": []}',
        ])

        result = run_audit(output_dir, outline_path=str(outline_path), model=model, batch_size=2)

        assert result.stats["chapter_checks"] == 5
        assert result.stats["chapter_check_batches"] == 3
        assert result.stats["transition_checks"] == 4
        assert result.stats["transition_check_batches"] == 2
        assert result.stats["llm_calls"] == 5
        assert result.stats["llm_batch_max_items"] == 2
        assert any(f.rule_id == "C1" and f.chapter == 2 for f in result.findings)
        assert any(f.rule_id == "C2" and f.chapter == 3 and f.severity == "fatal" for f in result.findings)

    def test_run_audit_splits_batches_when_prompt_would_exceed_budget(self, tmp_path):
        output_dir = str(tmp_path)
        chapters = [_chapter(index, f"第{index}章") for index in range(1, 4)]
        outline_path = _write_outline(tmp_path, chapters)
        long_content = "正文" + "甲" * 20000
        for index in range(1, 4):
            _write_chapter(output_dir, index, f"第{index}章", f"第{index}章{long_content}")
        model = QueueModel(['{"findings": []}'] * 10)

        result = run_audit(output_dir, outline_path=str(outline_path), model=model, batch_size=5)

        assert result.stats["chapter_checks"] == 3
        assert result.stats["chapter_check_batches"] > 1
        assert result.stats["llm_prompt_over_budget"] == 0
        assert result.stats["llm_prompt_max_chars"] <= CONTENT_AUDIT_PROMPT_MAX_CHARS
        assert all(len(prompt) <= CONTENT_AUDIT_PROMPT_MAX_CHARS for prompt in model.prompts)
