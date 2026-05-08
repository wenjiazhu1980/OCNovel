# -*- coding: utf-8 -*-
"""[L2-5b] Config._resolve_arc_config 三档解析测试

测试 Config 类对 arc_config.chapters_per_arc 的解析:
- user 优先:显式指定 cpa>0 → 使用该值
- auto 自动:cpa<=0 且 auto_compute=true 且 target>0 → 调用 compute 函数
- disabled 禁用:其他情况 → cpa=0
"""

import json
import logging
import os

import pytest

from src.config.config import Config


@pytest.fixture
def base_config_dict():
    """构造一个能成功初始化 Config 的最小 config.json 字典"""
    return {
        "novel_config": {
            "type": "末世",
            "theme": "生存",
            "style": "冷峻",
            "target_chapters": 400,
            "chapter_length": 3000,
            "writing_guide": {
                "world_building": {"magic_system": "", "social_system": "", "background": ""},
                "character_guide": {
                    "protagonist": {"background": "", "initial_personality": "", "growth_path": ""},
                    "supporting_roles": [],
                    "antagonists": [],
                },
                "plot_structure": {
                    "act_one": {}, "act_two": {}, "act_three": {},
                },
                "style_guide": {"tone": "", "pacing": "", "description_focus": []},
            },
        },
        "generation_config": {
            "max_retries": 1,
            "retry_delay": 0,
            "validation": {"enabled": False},
            "model_selection": {
                "outline": {"provider": "openai", "model_type": "outline"},
                "content": {"provider": "openai", "model_type": "content"},
            },
        },
        "knowledge_base_config": {
            "reference_files": [],
            "cache_dir": "data/cache",
        },
        "output_config": {"output_dir": "data/output"},
    }


def _write_config(tmp_path, cfg_dict):
    """把 dict 写成 config.json,返回路径"""
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(cfg_dict, ensure_ascii=False, indent=2), encoding="utf-8")
    # 同目录创建空 .env 防止 load_dotenv 报错
    (tmp_path / ".env").write_text("OPENAI_API_KEY=test\n", encoding="utf-8")
    return cfg_path


class TestUserPrecedence:
    """user 档:cpa>0 优先级最高"""

    def test_user_explicit_cpa_used_as_is(self, tmp_path, base_config_dict):
        base_config_dict["novel_config"]["arc_config"] = {"chapters_per_arc": 80}
        cfg = Config(str(_write_config(tmp_path, base_config_dict)))

        arc = cfg.novel_config["arc_config"]
        assert arc["chapters_per_arc"] == 80
        assert arc["_resolved_by"] == "user"

    def test_user_overrides_auto_compute(self, tmp_path, base_config_dict):
        """同时设置 cpa=80 与 auto_compute=true → 用户值优先"""
        base_config_dict["novel_config"]["arc_config"] = {
            "chapters_per_arc": 80,
            "auto_compute": True,
        }
        cfg = Config(str(_write_config(tmp_path, base_config_dict)))

        arc = cfg.novel_config["arc_config"]
        assert arc["chapters_per_arc"] == 80
        assert arc["_resolved_by"] == "user"


class TestAutoMode:
    """auto 档:cpa<=0 且 auto_compute=true 且 target>0"""

    def test_auto_compute_for_target_400(self, tmp_path, base_config_dict):
        base_config_dict["novel_config"]["target_chapters"] = 400
        base_config_dict["novel_config"]["arc_config"] = {
            "chapters_per_arc": 0,
            "auto_compute": True,
        }
        cfg = Config(str(_write_config(tmp_path, base_config_dict)))

        arc = cfg.novel_config["arc_config"]
        assert arc["chapters_per_arc"] == 80   # 推算结果
        assert arc["_resolved_by"] == "auto"
        assert "_resolved_reason" in arc
        assert "K=5" in arc["_resolved_reason"]

    def test_auto_compute_for_target_600(self, tmp_path, base_config_dict):
        base_config_dict["novel_config"]["target_chapters"] = 600
        base_config_dict["novel_config"]["arc_config"] = {
            "chapters_per_arc": 0,
            "auto_compute": True,
        }
        cfg = Config(str(_write_config(tmp_path, base_config_dict)))

        arc = cfg.novel_config["arc_config"]
        assert arc["chapters_per_arc"] == 66
        assert arc["_resolved_by"] == "auto"

    def test_auto_with_negative_cpa_treated_as_zero(self, tmp_path, base_config_dict):
        """cpa=-5 (异常值) 应视为 0,触发 auto"""
        base_config_dict["novel_config"]["arc_config"] = {
            "chapters_per_arc": -5,
            "auto_compute": True,
        }
        cfg = Config(str(_write_config(tmp_path, base_config_dict)))

        arc = cfg.novel_config["arc_config"]
        assert arc["chapters_per_arc"] == 80    # auto 计算结果
        assert arc["_resolved_by"] == "auto"


class TestDisabledMode:
    """disabled 档:其他情况"""

    def test_no_arc_config_disabled(self, tmp_path, base_config_dict):
        """完全没有 arc_config 字段 → 禁用"""
        cfg = Config(str(_write_config(tmp_path, base_config_dict)))

        arc = cfg.novel_config["arc_config"]
        assert arc["chapters_per_arc"] == 0
        assert arc["_resolved_by"] == "disabled"
        assert "_resolved_reason" not in arc   # disabled 不写 reason

    def test_cpa_zero_no_auto_disabled(self, tmp_path, base_config_dict):
        base_config_dict["novel_config"]["arc_config"] = {"chapters_per_arc": 0}
        cfg = Config(str(_write_config(tmp_path, base_config_dict)))

        arc = cfg.novel_config["arc_config"]
        assert arc["chapters_per_arc"] == 0
        assert arc["_resolved_by"] == "disabled"

    def test_auto_but_target_missing_disabled_with_warning(self, tmp_path, base_config_dict, caplog):
        """auto_compute=true 但 target_chapters=0 → 禁用并 WARNING"""
        base_config_dict["novel_config"]["target_chapters"] = 0
        base_config_dict["novel_config"]["arc_config"] = {
            "chapters_per_arc": 0,
            "auto_compute": True,
        }
        with caplog.at_level(logging.WARNING):
            cfg = Config(str(_write_config(tmp_path, base_config_dict)))

        arc = cfg.novel_config["arc_config"]
        assert arc["chapters_per_arc"] == 0
        assert arc["_resolved_by"] == "disabled"
        # WARNING 应提示用户设置 target_chapters
        warns = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("target_chapters" in m for m in warns)


class TestRobustness:
    """边界值与类型容错"""

    def test_string_cpa_treated_as_zero(self, tmp_path, base_config_dict):
        """cpa 是非数值字符串 → 视为 0"""
        base_config_dict["novel_config"]["arc_config"] = {"chapters_per_arc": "abc"}
        cfg = Config(str(_write_config(tmp_path, base_config_dict)))

        arc = cfg.novel_config["arc_config"]
        assert arc["chapters_per_arc"] == 0
        assert arc["_resolved_by"] == "disabled"

    def test_resolved_by_idempotent_on_reload(self, tmp_path, base_config_dict):
        """第二次构造 Config(同 config) 解析结果应一致"""
        base_config_dict["novel_config"]["arc_config"] = {
            "chapters_per_arc": 0,
            "auto_compute": True,
        }
        path = _write_config(tmp_path, base_config_dict)
        cfg1 = Config(str(path))
        cfg2 = Config(str(path))
        assert cfg1.novel_config["arc_config"]["chapters_per_arc"] == cfg2.novel_config["arc_config"]["chapters_per_arc"]
        assert cfg1.novel_config["arc_config"]["_resolved_by"] == cfg2.novel_config["arc_config"]["_resolved_by"]
