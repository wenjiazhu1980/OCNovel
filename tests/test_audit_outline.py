# -*- coding: utf-8 -*-
"""tools/audit_outline.py 大纲全局审计器测试

每条规则用最小合成大纲触发，断言检出/不误报。
"""

import json
import sys
from pathlib import Path

import pytest
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.audit_outline import (  # noqa: E402
    Finding,
    audit_foreshadowing,
    audit_entities,
    audit_task_closure,
    audit_identity,
    audit_recovery_rate,
    run_audit,
    main,
    llm_review_task_closure,
    llm_review_task_closure_with_stats,
)


def _ch(n, **kw):
    """构造最小合成章节 dict（仅填测试关心的字段，其余给空默认）"""
    return {
        "chapter_number": n,
        "title": kw.get("title", f"第{n}章"),
        "key_points": kw.get("key_points", []),
        "characters": kw.get("characters", []),
        "foreshadowing": kw.get("foreshadowing", []),
    }


class TestO1Foreshadowing:
    """O1 伏笔埋设-回收配对"""

    def test_flags_unrecovered_foreshadowing(self):
        chapters = [
            _ch(1, foreshadowing=["埋设：神秘玄铁令暗示主角身世"]),
            _ch(2, foreshadowing=["埋设：反派组织黑龙会浮现"]),
        ]
        findings = audit_foreshadowing(chapters)
        assert any(f.rule_id == "O1" for f in findings)
        # 悬挂的"玄铁令"伏笔应被点名
        assert any("玄铁令" in f.message for f in findings)

    def test_no_flag_when_recovered(self):
        chapters = [
            _ch(1, foreshadowing=["埋设：神秘玄铁令暗示主角身世"]),
            _ch(2, foreshadowing=["回收：玄铁令之谜揭晓，主角乃皇族遗孤"]),
        ]
        findings = audit_foreshadowing(chapters)
        # 玄铁令已回收，不应作为悬挂伏笔报出
        assert not any("玄铁令" in f.message and f.rule_id == "O1" for f in findings)


class TestO2Entities:
    """O2 命名实体生命线断裂"""

    def test_flags_disappearing_entity(self):
        # "黑风寨"前 5 章登场后消失；主角贯穿全 20 章
        chapters = []
        for n in range(1, 21):
            chars = ["主角"]
            if n <= 5:
                chars.append("黑风寨")
            chapters.append(_ch(n, characters=chars))
        findings = audit_entities(chapters)
        assert any(f.rule_id == "O2" and "黑风寨" in f.message for f in findings)

    def test_no_flag_for_persistent_entity(self):
        # 主角贯穿首尾，不应报断裂
        chapters = [_ch(n, characters=["主角"]) for n in range(1, 21)]
        findings = audit_entities(chapters)
        assert not any("主角" in f.message and f.rule_id == "O2" for f in findings)

    def test_ignores_one_off_minor_role(self):
        # 只出现 1 次的龙套不算"有存在感的线索"，不应报
        chapters = [_ch(n, characters=["主角"]) for n in range(1, 21)]
        chapters[2]["characters"].append("路人甲")  # 仅第3章出现一次
        findings = audit_entities(chapters)
        assert not any("路人甲" in f.message for f in findings)

    def test_normalizes_parenthetical_aliases(self):
        # "张铁柱（退休老刑警）"与"张铁柱"应视为同一实体，贯穿则不报
        chapters = []
        for n in range(1, 21):
            name = "张铁柱（退休老刑警）" if n % 2 == 0 else "张铁柱"
            chapters.append(_ch(n, characters=[name]))
        findings = audit_entities(chapters)
        assert not any("张铁柱" in f.message and f.rule_id == "O2" for f in findings)

    def test_definitive_closure_suppresses_disappearing_entity(self):
        chapters = []
        for n in range(1, 21):
            chars = ["主角"]
            key_points = []
            if n <= 5:
                chars.append("白蝠将军")
            if n == 5:
                key_points.append("主角正面击溃白蝠将军，将其一击轰碎，战场威胁彻底收束")
            chapters.append(_ch(n, characters=chars, key_points=key_points))

        findings = audit_entities(chapters)

        assert not any(f.rule_id == "O2" and "白蝠将军" in f.message for f in findings)

    def test_alias_normalization_merges_inspector_titles(self):
        chapters = []
        for n in range(1, 21):
            chars = ["主角"]
            if n in (1, 2):
                chars.append("天庭监察使")
            if n == 8:
                chars.append("晏天官(监察使)")
            if n == 18:
                chars.append("律法监察使")
            chapters.append(_ch(n, characters=chars))

        findings = audit_entities(chapters)

        assert not any(f.rule_id == "O2" and "律法监察使" in f.message for f in findings)

    def test_minor_entity_is_downgraded_to_info(self):
        chapters = []
        for n in range(1, 21):
            chars = ["主角"]
            if n <= 5:
                chars.append("青狐教众")
            chapters.append(_ch(n, characters=chars))

        findings = audit_entities(chapters)
        target = [f for f in findings if f.rule_id == "O2" and "青狐教众" in f.message]

        assert target
        assert target[0].severity == "info"
        assert target[0].evidence["importance"] == "minor"

    def test_o2_finding_contains_evidence_for_manual_review(self):
        chapters = []
        for n in range(1, 21):
            chars = ["主角"]
            if n <= 5:
                chars.append("黑风寨")
            chapters.append(_ch(n, characters=chars, key_points=[f"第{n}章关键事件"]))

        findings = audit_entities(chapters)
        target = next(f for f in findings if f.rule_id == "O2" and "黑风寨" in f.message)

        assert target.evidence["first_chapter"] == 1
        assert target.evidence["last_chapter"] == 5
        assert target.evidence["sample_occurrences"] == [1, 2, 3, 4, 5]
        assert "last_context" in target.evidence
        assert "possible_closure_context" in target.evidence


class TestO3TaskClosure:
    """O3 系统任务闭环"""

    def test_flags_unclosed_task(self):
        chapters = [
            _ch(1, key_points=["系统发布任务：清剿盘踞东郊的黑风寨匪患"]),
            _ch(2, key_points=["主角在镇上吃了碗阳春面"]),
            _ch(3, key_points=["主角动身进城赶考，把山寨的事抛在脑后"]),
        ]
        findings = audit_task_closure(chapters)
        assert any(f.rule_id == "O3" and "黑风寨" in f.message for f in findings)

    def test_no_flag_when_completed(self):
        chapters = [
            _ch(1, key_points=["系统发布任务：清剿盘踞东郊的黑风寨匪患"]),
            _ch(2, key_points=["主角夜探黑风寨，摸清匪患布防"]),
            _ch(3, key_points=["主角荡平黑风寨匪患，任务完成，获得丰厚奖励"]),
        ]
        findings = audit_task_closure(chapters)
        assert not any(f.rule_id == "O3" and "黑风寨" in f.message for f in findings)


class TestO4Identity:
    """O4 人物身份一致性（仅信任 characters 字段的括号注释，避免邻近窗口污染）"""

    def test_flags_identity_conflict(self):
        chapters = [
            _ch(1, characters=["老王（镇上的医生）"]),
            _ch(5, characters=["老王（潜伏的刑警）"]),
        ]
        findings = audit_identity(chapters)
        assert any(f.rule_id == "O4" and "老王" in f.message for f in findings)

    def test_no_flag_consistent_identity(self):
        chapters = [
            _ch(1, characters=["老王（医生）"]),
            _ch(5, characters=["老王（医生）"]),
        ]
        findings = audit_identity(chapters)
        assert not any(f.rule_id == "O4" and "老王" in f.message for f in findings)

    def test_synonyms_not_treated_as_conflict(self):
        # "大夫"与"医生"是同义，不应判为身份冲突
        chapters = [
            _ch(1, characters=["老王（医生）"]),
            _ch(5, characters=["老王（人称好大夫）"]),
        ]
        findings = audit_identity(chapters)
        assert not any(f.rule_id == "O4" and "老王" in f.message for f in findings)

    def test_no_false_positive_from_co_occurring_roles(self):
        # 张铁柱(刑警)与混混同场，不应把"混混"误判给张铁柱（邻近窗口污染的回归测试）
        chapters = [
            _ch(1, characters=["张铁柱（退休刑警）", "地痞混混"],
                key_points=["张铁柱呵斥地痞混混赶紧离开"]),
            _ch(2, characters=["张铁柱（退休刑警）"]),
        ]
        findings = audit_identity(chapters)
        assert not any(f.rule_id == "O4" and "张铁柱" in f.message for f in findings)


class TestO5RecoveryRate:
    """O5 结局回收率"""

    def test_reports_recovery_stats(self):
        chapters = [
            _ch(1, foreshadowing=["埋设：甲线索暗藏玄机", "埋设：乙线索扑朔迷离"]),
            _ch(2, foreshadowing=["埋设：丙线索悬而未决"]),
        ]
        findings = audit_recovery_rate(chapters)
        assert any(f.rule_id == "O5" for f in findings)
        # 埋设 3 条应体现在统计里
        assert any("3" in f.message for f in findings if f.rule_id == "O5")

    def test_high_hang_ratio_is_warning(self):
        # 3 埋 0 回收 → 悬挂率高 → warning
        chapters = [
            _ch(1, foreshadowing=["埋设：甲线索暗藏玄机"]),
            _ch(2, foreshadowing=["埋设：乙线索扑朔迷离"]),
            _ch(3, foreshadowing=["埋设：丙线索悬而未决"]),
        ]
        o5 = [f for f in audit_recovery_rate(chapters) if f.rule_id == "O5"][0]
        assert o5.severity == "warning"


class TestCLI:
    """CLI main 契约"""

    def _write(self, tmp_path, outline):
        p = tmp_path / "outline.json"
        p.write_text(json.dumps(outline, ensure_ascii=False), encoding="utf-8")
        return str(p)

    def test_reports_and_exits(self, tmp_path, capsys):
        path = self._write(tmp_path, [
            _ch(1, foreshadowing=["埋设：神秘卷轴现世"], characters=["主角"]),
        ])
        rc = main(["--outline", path])
        out = capsys.readouterr().out
        assert "大纲审计报告" in out
        assert rc in (0, 1)

    def test_json_mode_flags_fatal(self, tmp_path, capsys):
        # 未闭环系统任务 → fatal → 退出码 1
        path = self._write(tmp_path, [
            _ch(1, key_points=["系统发布任务：找回失落的上古圣剑残片"], characters=["主角"]),
        ])
        rc = main(["--outline", path, "--json"])
        data = json.loads(capsys.readouterr().out)
        assert "findings" in data
        assert rc == 1 and data["fatal"] >= 1

    def test_bad_path_exits_two(self, capsys):
        rc = main(["--outline", "/nonexistent/path/xx.json"])
        assert rc == 2

    def test_llm_without_config_exits_two(self, tmp_path, capsys):
        path = self._write(tmp_path, [_ch(1, characters=["主角"])])
        rc = main(["--outline", path, "--llm"])
        assert rc == 2

    def test_llm_flag_integrates_review(self, tmp_path, capsys, monkeypatch):
        path = self._write(tmp_path, [
            _ch(1, key_points=["系统发布任务：调查处理西街老李头家的念影"]),
            _ch(5, key_points=["帮退休教师化解念影，任务完成"]),
        ])
        import tools.audit_outline as mod
        fake = MagicMock()
        fake.generate.return_value = '{"closed": false, "reason": "非老李头本人"}'
        monkeypatch.setattr(mod, "_build_content_model", lambda cfg: fake)
        rc = main(["--outline", path, "--llm", "--config", "dummy.json"])
        out = capsys.readouterr().out
        assert "O3-LLM" in out
        assert rc == 1


class TestLLMReview:
    """LLM 语义复核（用 MagicMock 模拟模型，验证流程与 JSON 容错）"""

    def _motif_chapters(self):
        # 老李头任务在第1章发布；第5章用"退休教师"完成了同母题(念影)事件
        return [
            _ch(1, key_points=["系统发布任务：调查处理西街老李头家的念影怪事"]),
            _ch(5, key_points=["主角帮退休教师化解了念影，任务完成，获得新能力"]),
        ]

    def test_flags_false_closure_from_motif_reuse(self):
        model = MagicMock()
        model.generate.return_value = '{"closed": false, "reason": "完成的是退休教师的念影，非老李头本人"}'
        findings = llm_review_task_closure(self._motif_chapters(), model)
        assert any(f.rule_id == "O3-LLM" and "老李头" in f.message for f in findings)
        assert model.generate.called
        assert model.generate.call_args.kwargs["temperature"] == 0

    def test_respects_closed_verdict(self):
        model = MagicMock()
        model.generate.return_value = '{"closed": true, "reason": "已办结"}'
        findings = llm_review_task_closure(self._motif_chapters(), model)
        assert not any(f.rule_id == "O3-LLM" for f in findings)

    def test_handles_markdown_wrapped_json(self):
        model = MagicMock()
        model.generate.return_value = '```json\n{"closed": false, "reason": "未完成"}\n```'
        findings = llm_review_task_closure(self._motif_chapters(), model)
        assert any(f.rule_id == "O3-LLM" for f in findings)

    def test_unparseable_response_becomes_warning(self):
        model = MagicMock()
        model.generate.return_value = "抱歉，我无法判断这个任务。"
        findings = llm_review_task_closure(self._motif_chapters(), model)
        assert any(f.rule_id == "O3-LLM" and f.severity == "warning" for f in findings)

    def test_stats_show_zero_calls_when_no_published_tasks(self):
        model = MagicMock()
        result = llm_review_task_closure_with_stats([
            _ch(1, key_points=["主角在山村修炼"]),
            _ch(2, key_points=["主角击败普通妖兽"]),
        ], model)

        assert result.findings == []
        assert result.stats["published_tasks"] == 0
        assert result.stats["llm_calls"] == 0
        assert result.stats["llm_reviewed_tasks"] == 0
        model.generate.assert_not_called()

    def test_stats_count_llm_calls_and_findings(self):
        model = MagicMock()
        model.generate.return_value = '{"closed": false, "reason": "完成的是退休教师的念影，非老李头本人"}'
        result = llm_review_task_closure_with_stats(self._motif_chapters(), model)

        assert result.stats["published_tasks"] == 1
        assert result.stats["llm_calls"] == 1
        assert result.stats["llm_findings"] == 1
        assert result.stats["open_tasks"] == 1
        assert model.generate.call_args.kwargs["temperature"] == 0
        assert any(f.rule_id == "O3-LLM" and f.severity == "fatal" for f in result.findings)
