# -*- coding: utf-8 -*-
"""generate_outline 终局审计闸门测试

验证 OutlineGenerator._run_outline_audit：
- 全书生成后跑算法审计并落盘 outline_audit_report.json
- 配置 outline_audit_enabled=False 时跳过
- 对 None 槽位/异常数据不抛错（只读报告，绝不阻断生成）
"""

import json
import os
from unittest.mock import MagicMock

import pytest

from src.generators.common.data_structures import ChapterOutline
from src.generators.outline.outline_generator import OutlineGenerator


def _gen(mock_config):
    """构造一个可注入 chapter_outlines 的 OutlineGenerator。"""
    mm = MagicMock()
    mm.model_name = "mock"
    mk = MagicMock()
    mk.is_built = False
    od = mock_config.output_config["output_dir"]
    os.makedirs(od, exist_ok=True)
    with open(os.path.join(od, "outline.json"), "w", encoding="utf-8") as f:
        json.dump([], f)
    return OutlineGenerator(mock_config, mm, mk)


def _report_path(mock_config):
    return os.path.join(mock_config.output_config["output_dir"], "outline_audit_report.json")


class TestOutlineAuditGate:

    def test_writes_report_with_fatal(self, mock_config):
        gen = _gen(mock_config)
        gen.chapter_outlines = [
            ChapterOutline(1, "第1章", ["系统发布任务：清剿盘踞东郊的黑风寨匪患"],
                           ["主角"], ["山村"], ["匪患"]),
            ChapterOutline(2, "第2章", ["主角进城赶考，把山寨之事抛诸脑后"],
                           ["主角"], ["城里"], ["赶考"]),
        ]
        gen._run_outline_audit()
        report = _report_path(mock_config)
        assert os.path.exists(report)
        data = json.load(open(report, encoding="utf-8"))
        # 黑风寨任务无"任务完成" → O3 fatal
        assert data["fatal"] >= 1

    def test_disabled_skips_report(self, mock_config):
        mock_config.generation_config["outline_audit_enabled"] = False
        gen = _gen(mock_config)
        gen.chapter_outlines = [
            ChapterOutline(1, "第1章", ["系统发布任务：清剿黑风寨"],
                           ["主角"], ["x"], ["y"]),
        ]
        gen._run_outline_audit()
        assert not os.path.exists(_report_path(mock_config))

    def test_does_not_raise_on_none_slots(self, mock_config):
        gen = _gen(mock_config)
        gen.chapter_outlines = [None, None]
        # 不抛异常即通过；报告仍应生成（0 fatal）
        gen._run_outline_audit()
        assert os.path.exists(_report_path(mock_config))
