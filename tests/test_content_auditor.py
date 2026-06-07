# -*- coding: utf-8 -*-
"""章节内容审计器测试。"""

import json
import os

from src.generators.content.content_auditor import (
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
