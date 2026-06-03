# -*- coding: utf-8 -*-
"""大纲质量闸门（阻断式）测试。

验证 src/generators/outline/outline_quality_gate.run_quality_gate：
- 审计无 fatal → 放行、不修订
- 有 fatal、修订后消除 → 放行、已修订
- 有 fatal、修订后仍存在 → 拦截
- enable_llm 开关控制是否跑 LLM 复核
- output_dir 给定时写回 outline.json + 备份 + 落盘报告
- 闸门自身执行异常 → fail-open 放行

区别于 test_outline_audit_gate.py（那测的是只读、不阻断的 _run_outline_audit）。
"""

import json
from unittest.mock import MagicMock

from src.generators.outline.outline_quality_gate import (
    QualityGateResult,
    run_quality_gate,
)
from src.generators.common.data_structures import ChapterOutline


def _clean_chapters():
    """无系统任务、无身份冲突 → 0 fatal。"""
    return [
        {
            "chapter_number": 1,
            "title": "第一章",
            "key_points": ["主角进城赶考"],
            "characters": ["主角"],
            "settings": ["城里"],
            "conflicts": ["赶考压力"],
            "foreshadowing": [],
        },
        {
            "chapter_number": 2,
            "title": "第二章",
            "key_points": ["主角金榜题名"],
            "characters": ["主角"],
            "settings": ["城里"],
            "conflicts": [],
            "foreshadowing": [],
        },
    ]


def _fatal_chapters():
    """第1章发布系统任务、后续无闭环 → O3 fatal。"""
    return [
        {
            "chapter_number": 1,
            "title": "第一章",
            "key_points": ["系统发布任务：清剿盘踞东郊的黑风寨匪患"],
            "characters": ["主角"],
            "settings": ["山村"],
            "conflicts": ["匪患"],
            "foreshadowing": [],
        },
        {
            "chapter_number": 2,
            "title": "第二章",
            "key_points": ["主角进城赶考，把山寨之事抛诸脑后"],
            "characters": ["主角"],
            "settings": ["城里"],
            "conflicts": ["赶考"],
            "foreshadowing": [],
        },
    ]


def _revision_resolving_task():
    """把黑风寨任务在第2章闭环的修订补丁。"""
    return json.dumps({
        "summary": "补上黑风寨任务闭环",
        "revisions": [{
            "chapter_number": 2,
            "reason": "补上第1章系统任务的收束",
            "fields": {"key_points": ["主角率众清剿黑风寨，匪患肃清，系统任务完成。"]},
        }],
    }, ensure_ascii=False)


def test_clean_outline_passes_without_revision():
    model = MagicMock()

    result = run_quality_gate(_clean_chapters(), model, enable_llm=False, output_dir=None)

    assert isinstance(result, QualityGateResult)
    assert result.passed is True
    assert result.revised is False
    assert result.initial_fatal == 0
    assert result.remaining_fatal == 0
    model.generate.assert_not_called()


def test_fatal_resolved_by_revision_passes():
    model = MagicMock()
    model.generate.return_value = _revision_resolving_task()

    result = run_quality_gate(_fatal_chapters(), model, enable_llm=False, output_dir=None)

    assert result.initial_fatal >= 1
    assert result.revised is True
    assert 2 in result.changed_chapters
    assert result.passed is True
    assert result.remaining_fatal == 0


def test_fatal_unresolved_blocks():
    model = MagicMock()
    # 修订器返回空补丁 → 大纲不变 → 重审仍 fatal
    model.generate.return_value = json.dumps({"summary": "无法修订", "revisions": []}, ensure_ascii=False)

    result = run_quality_gate(_fatal_chapters(), model, enable_llm=False, output_dir=None)

    assert result.initial_fatal >= 1
    assert result.passed is False
    assert result.remaining_fatal >= 1
    assert result.revised is False


def test_disable_llm_skips_llm_review(monkeypatch):
    from src.generators.outline import outline_quality_gate as qg
    spy = MagicMock()
    monkeypatch.setattr(qg, "llm_review_task_closure_with_stats", spy)

    run_quality_gate(_clean_chapters(), MagicMock(), enable_llm=False, output_dir=None)

    spy.assert_not_called()


def test_enable_llm_invokes_llm_review(monkeypatch):
    from src.generators.outline import outline_quality_gate as qg
    from src.generators.outline.outline_auditor import LLMReviewResult
    spy = MagicMock(return_value=LLMReviewResult(findings=[], stats={}, superseded_task_keys=set()))
    monkeypatch.setattr(qg, "llm_review_task_closure_with_stats", spy)
    monkeypatch.setattr(qg, "merge_llm_task_review_findings", lambda findings, llm: findings)

    run_quality_gate(_clean_chapters(), MagicMock(), enable_llm=True, output_dir=None)

    spy.assert_called_once()


def test_writes_back_outline_with_backup_and_report(tmp_path):
    outline_path = tmp_path / "outline.json"
    outline_path.write_text(json.dumps(_fatal_chapters(), ensure_ascii=False), encoding="utf-8")
    model = MagicMock()
    model.generate.return_value = _revision_resolving_task()

    result = run_quality_gate(_fatal_chapters(), model, enable_llm=False, output_dir=str(tmp_path))

    assert result.passed is True
    assert result.revised is True
    # 写回后的 outline.json 含修订内容
    updated = json.loads(outline_path.read_text(encoding="utf-8"))
    assert "任务完成" in updated[1]["key_points"][0]
    # 自动备份原大纲
    backups = list(tmp_path.glob("outline.json.bak.*"))
    assert len(backups) == 1
    # 落盘质量闸门报告
    report_path = tmp_path / "outline_quality_gate_report.json"
    assert report_path.exists()
    assert json.loads(report_path.read_text(encoding="utf-8"))["passed"] is True


def test_gate_internal_error_fails_open(monkeypatch):
    """闸门自身执行异常 → fail-open 放行（不阻断流水线）。"""
    from src.generators.outline import outline_quality_gate as qg
    monkeypatch.setattr(qg, "run_audit", MagicMock(side_effect=RuntimeError("boom")))

    result = run_quality_gate(_clean_chapters(), MagicMock(), enable_llm=False, output_dir=None)

    assert result.passed is True


# ---------------------------------------------------------------------------
# run_quality_gate_for_pipeline：CLI auto / GUI pipeline_worker 共用入口
# ---------------------------------------------------------------------------
class _FakeContentGen:
    def __init__(self, outlines):
        self.chapter_outlines = outlines
        self.load_calls = 0

    def _load_outline(self):
        self.load_calls += 1


def _fake_config(enabled=True, llm=True, rounds=1, output_dir="/tmp/qg"):
    cfg = MagicMock()
    cfg.generation_config = {
        "outline_quality_gate_enabled": enabled,
        "outline_quality_gate_llm_review": llm,
        "outline_quality_gate_max_rounds": rounds,
    }
    cfg.generator_config = {"output_dir": output_dir}
    return cfg


def _one_outline():
    return [ChapterOutline(1, "第一章", ["关键点"], ["主角"], ["场景"], ["冲突"])]


def test_pipeline_gate_disabled_skips_and_passes(monkeypatch):
    from src.generators.outline import outline_quality_gate as qg
    spy = MagicMock()
    monkeypatch.setattr(qg, "run_quality_gate", spy)
    cg = _FakeContentGen(_one_outline())

    result = qg.run_quality_gate_for_pipeline(_fake_config(enabled=False), cg, MagicMock())

    assert result.passed is True
    spy.assert_not_called()
    assert cg.load_calls == 0


def test_pipeline_gate_enabled_passes_config_through(monkeypatch):
    from src.generators.outline import outline_quality_gate as qg
    spy = MagicMock(return_value=QualityGateResult(
        passed=True, initial_fatal=0, remaining_fatal=0, rounds_run=1, revised=False))
    monkeypatch.setattr(qg, "run_quality_gate", spy)
    cg = _FakeContentGen(_one_outline())
    model = MagicMock()

    qg.run_quality_gate_for_pipeline(
        _fake_config(enabled=True, llm=False, rounds=2, output_dir="/tmp/out"), cg, model)

    spy.assert_called_once()
    args, kwargs = spy.call_args
    assert args[0][0]["chapter_number"] == 1     # chapter_outlines 转成 dict
    assert args[1] is model
    assert kwargs["enable_llm"] is False
    assert kwargs["max_rounds"] == 2
    assert kwargs["output_dir"] == "/tmp/out"


def test_pipeline_gate_reloads_outline_when_revised(monkeypatch):
    from src.generators.outline import outline_quality_gate as qg
    monkeypatch.setattr(qg, "run_quality_gate", MagicMock(return_value=QualityGateResult(
        passed=False, initial_fatal=2, remaining_fatal=1, rounds_run=1, revised=True)))
    cg = _FakeContentGen(_one_outline())

    result = qg.run_quality_gate_for_pipeline(_fake_config(enabled=True), cg, MagicMock())

    assert cg.load_calls == 1
    assert result.passed is False


def test_pipeline_gate_no_reload_when_not_revised(monkeypatch):
    from src.generators.outline import outline_quality_gate as qg
    monkeypatch.setattr(qg, "run_quality_gate", MagicMock(return_value=QualityGateResult(
        passed=True, initial_fatal=0, remaining_fatal=0, rounds_run=1, revised=False)))
    cg = _FakeContentGen(_one_outline())

    qg.run_quality_gate_for_pipeline(_fake_config(enabled=True), cg, MagicMock())

    assert cg.load_calls == 0


def test_pipeline_gate_handles_none_slots(monkeypatch):
    """chapter_outlines 含 None 稀疏槽位时不应抛错。"""
    from src.generators.outline import outline_quality_gate as qg
    spy = MagicMock(return_value=QualityGateResult(
        passed=True, initial_fatal=0, remaining_fatal=0, rounds_run=1, revised=False))
    monkeypatch.setattr(qg, "run_quality_gate", spy)
    cg = _FakeContentGen([ChapterOutline(1, "第一章", ["k"], ["c"], ["s"], ["x"]), None])

    qg.run_quality_gate_for_pipeline(_fake_config(enabled=True), cg, MagicMock())

    chapters_arg = spy.call_args.args[0]
    assert chapters_arg[1] is None


def test_no_reaudit_when_revision_makes_no_change(monkeypatch):
    """修订未改动大纲（revised=False）时不应再跑一轮重审，避免空转浪费 LLM。

    真实场景：O4 身份冲突等修订器改不动的 fatal，补丁为空 → 大纲不变，
    再审结果必然与首轮相同，重审纯属浪费（enable_llm 时还会重复跑 LLM 复核）。
    """
    from src.generators.outline import outline_quality_gate as qg

    real_run_audit = qg.run_audit
    calls = {"n": 0}

    def counting(chapters):
        calls["n"] += 1
        return real_run_audit(chapters)

    monkeypatch.setattr(qg, "run_audit", counting)

    model = MagicMock()
    # 修订器返回空补丁 → 大纲不变 → revised=False
    model.generate.return_value = json.dumps(
        {"summary": "无法修订", "revisions": []}, ensure_ascii=False
    )

    result = run_quality_gate(_fatal_chapters(), model, enable_llm=False, output_dir=None)

    # 首轮审计 1 次；修订无改动 → 提前 break，不重审 → 总计 1 次
    assert calls["n"] == 1
    assert result.revised is False
    assert result.passed is False
    assert result.rounds_run == 1


def test_pipeline_fails_open_when_reload_raises(monkeypatch):
    """revised 后 _load_outline 抛错 → for_pipeline 应 fail-open（passed=True），不传播异常。

    fail-open 设计承诺覆盖整个闸门入口：转换 chapter_outlines、跑闸门、重载大纲
    任一环节异常都不应让流水线 fail-closed 中止（尤其 GUI 会 emit(False)）。
    """
    from src.generators.outline import outline_quality_gate as qg
    monkeypatch.setattr(qg, "run_quality_gate", MagicMock(return_value=QualityGateResult(
        passed=True, initial_fatal=1, remaining_fatal=0, rounds_run=1, revised=True)))

    class _BoomReload(_FakeContentGen):
        def _load_outline(self):
            raise RuntimeError("reload boom")

    cg = _BoomReload(_one_outline())

    result = qg.run_quality_gate_for_pipeline(_fake_config(enabled=True), cg, MagicMock())

    assert result.passed is True
