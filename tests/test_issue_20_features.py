# -*- coding: utf-8 -*-
"""测试 GitHub Issue #20 新增 / 修复的功能

覆盖范围：
- 方案 1: description_focus 全链路（prompts.py 安全下标 + GUI 列表编辑器 + Worker 字段）
- 方案 2: ResizableTextEdit 控件
- 方案 3: 角色结构化编辑器 + 自动生成数量/性别参数
- 方案 4.1: 灾难锚点 GUI 字段 load/save 往返
- 方案 4.2-4.4: outline prompt 6 段细分 / 收尾收敛 / 伏笔预算
"""

import os
import json
import shutil
import tempfile
from unittest.mock import patch

import pytest

from src.generators.prompts import get_outline_prompt


# ---------------------------------------------------------------------------
# Qt 环境 fixture（GUI 测试共用）
# ---------------------------------------------------------------------------
_qapp = None


@pytest.fixture(scope="module")
def qapp():
    """整个测试模块共享一个 offscreen QApplication 实例"""
    global _qapp
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        pytest.skip("PySide6 未安装，跳过 GUI 测试")
    _qapp = QApplication.instance() or QApplication([])
    yield _qapp


@pytest.fixture
def example_config_path(tmp_path):
    """复制 config.json.example 到 tmp_path 提供可写副本"""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = os.path.join(project_root, "config.json.example")
    dst = tmp_path / "config.json"
    shutil.copy(src, dst)
    return str(dst)


@pytest.fixture
def novel_params_tab(qapp, example_config_path):
    """构造一个加载了 example 配置的 NovelParamsTab"""
    from src.gui.tabs.novel_params_tab import NovelParamsTab
    return NovelParamsTab(config_path=example_config_path)


# ===========================================================================
# 方案 1 后端：prompts.py 安全下标
# ===========================================================================
class TestDescriptionFocusSafeIndexing:
    """get_outline_prompt 不再因 description_focus 不足 3 条而 IndexError"""

    def _cfg(self, focus_list):
        return {
            "writing_guide": {
                "world_building": {},
                "character_guide": {"protagonist": {}, "supporting_roles": [], "antagonists": []},
                "plot_structure": {"act_one": {}, "act_two": {}, "act_three": {}},
                "style_guide": {"tone": "热血", "pacing": "快", "description_focus": focus_list},
            }
        }

    def test_empty_focus_uses_fallback(self):
        prompt = get_outline_prompt(
            "玄幻", "成长", "热血", 1, 5,
            novel_config=self._cfg([]),
            total_chapters=100,
        )
        # 应回落到 3 条占位文本，不抛异常
        assert "描写的第一个侧重点" in prompt

    def test_two_items_no_indexerror(self):
        """历史 bug：少于 3 条会触发 IndexError，现在应正常生成"""
        prompt = get_outline_prompt(
            "玄幻", "成长", "热血", 1, 5,
            novel_config=self._cfg(["战斗描写", "世界观塑造"]),
            total_chapters=100,
        )
        assert "战斗描写" in prompt
        assert "世界观塑造" in prompt

    def test_more_than_three_all_rendered(self):
        """超过 3 条时全部应被渲染（之前硬下标只取前 3）"""
        focus = ["战斗", "世界观", "人物", "权谋", "情感"]
        prompt = get_outline_prompt(
            "玄幻", "成长", "热血", 1, 5,
            novel_config=self._cfg(focus),
            total_chapters=100,
        )
        for item in focus:
            assert item in prompt

    def test_none_value_uses_fallback(self):
        """style_guide.description_focus 为 None 时应使用占位文本"""
        cfg = self._cfg(None)
        # _cfg 直接传 None
        prompt = get_outline_prompt(
            "玄幻", "成长", "热血", 1, 5,
            novel_config=cfg,
            total_chapters=100,
        )
        assert "描写的第一个侧重点" in prompt


# ===========================================================================
# 方案 4.2 - 4.4: outline prompt 阶段表 / 收敛 / 伏笔预算
# ===========================================================================
class TestOutlinePhaseAndForeshadowing:
    def _cfg(self):
        return {
            "writing_guide": {
                "world_building": {},
                "character_guide": {"protagonist": {}, "supporting_roles": [], "antagonists": []},
                "plot_structure": {
                    "act_one": {}, "act_two": {}, "act_three": {},
                    "disasters": {
                        "first_disaster": "首灾",
                        "second_disaster": "中灾",
                        "third_disaster": "终灾",
                    },
                },
                "style_guide": {"description_focus": ["a", "b", "c"]},
            }
        }

    @pytest.mark.parametrize("end_ch,expected_phrase", [
        (5, "开场钩子"),         # 5%
        (20, "第一幕推进"),      # 20%
        (40, "第二幕上半"),      # 40%
        (70, "第二幕下半"),      # 70%
        (85, "第三幕冲刺"),      # 85%
        (95, "尾声收束"),        # 95%
    ])
    def test_six_phase_breakdown(self, end_ch, expected_phrase):
        prompt = get_outline_prompt(
            "玄幻", "成长", "热血", 1, end_ch,
            novel_config=self._cfg(),
            total_chapters=100,
            current_end_chapter_num=end_ch,
        )
        assert expected_phrase in prompt

    def test_endgame_constraint_only_after_80pct(self):
        """收敛约束仅在 >80% 且非最终批次时触发"""
        cfg = self._cfg()
        # 50% 时不应有收敛约束
        p_mid = get_outline_prompt(
            "", "", "", 41, 10,
            novel_config=cfg, total_chapters=100, current_end_chapter_num=50,
        )
        assert "收敛阶段约束" not in p_mid
        # 85% 非最终批次：应触发
        p_end = get_outline_prompt(
            "", "", "", 81, 5,
            novel_config=cfg, total_chapters=100, current_end_chapter_num=85,
        )
        assert "收敛阶段约束" in p_end

    def test_final_batch_note_present(self):
        prompt = get_outline_prompt(
            "", "", "", 91, 10,
            novel_config=self._cfg(),
            total_chapters=100, current_end_chapter_num=100,
        )
        assert "最后一批章节" in prompt

    def test_pending_foreshadowing_injected(self):
        prompt = get_outline_prompt(
            "", "", "", 30, 10,
            novel_config=self._cfg(), total_chapters=100, current_end_chapter_num=39,
            pending_foreshadowing=["玉佩发光的秘密", "神秘老者身份"],
        )
        assert "未回收伏笔" in prompt
        assert "玉佩发光的秘密" in prompt
        assert "神秘老者身份" in prompt
        assert "至少需通过" in prompt

    def test_pending_foreshadowing_empty_no_section(self):
        prompt = get_outline_prompt(
            "", "", "", 30, 10,
            novel_config=self._cfg(), total_chapters=100, current_end_chapter_num=39,
            pending_foreshadowing=[],
        )
        assert "未回收伏笔" not in prompt

    def test_density_hint_present(self):
        prompt = get_outline_prompt(
            "", "", "", 1, 10,
            novel_config=self._cfg(), total_chapters=100, current_end_chapter_num=10,
        )
        assert "本阶段节奏指引" in prompt

    def test_disaster_anchor_triggered_around_25pct(self):
        """跨过 25% 边界的批次应注入第一次灾难锚点"""
        prompt = get_outline_prompt(
            "", "", "", 21, 10,
            novel_config=self._cfg(), total_chapters=100, current_end_chapter_num=30,
        )
        assert "灾难锚点" in prompt
        assert "首灾" in prompt


# ===========================================================================
# 方案 2: ResizableTextEdit
# ===========================================================================
class TestResizableTextEdit:
    def test_instantiation_has_size_grip(self, qapp):
        from src.gui.widgets.resizable_text_edit import ResizableTextEdit, _VResizeHandle
        te = ResizableTextEdit()
        assert te._grip is not None
        # QSizeGrip 只能调整顶层窗口，这里改用自定义 _VResizeHandle 拖拽调整文本框高度
        assert isinstance(te._grip, _VResizeHandle)

    def test_grip_repositions_on_resize(self, qapp):
        from src.gui.widgets.resizable_text_edit import ResizableTextEdit
        te = ResizableTextEdit()
        te.resize(400, 200)
        te.show()
        qapp.processEvents()
        # grip 应位于右下角附近（允许 ±20 像素误差）
        gx = te._grip.x() + te._grip.width()
        gy = te._grip.y() + te._grip.height()
        assert abs(gx - te.viewport().width()) <= 20
        assert abs(gy - te.viewport().height()) <= 20
        te.close()

    def test_accept_rich_text_disabled(self, qapp):
        from src.gui.widgets.resizable_text_edit import ResizableTextEdit
        te = ResizableTextEdit()
        assert te.acceptRichText() is False


# ===========================================================================
# 方案 1 GUI: description_focus 列表编辑器数据流
# ===========================================================================
class TestDescriptionFocusEditor:
    def test_initial_load_from_example(self, novel_params_tab):
        """example 配置含 3 条 description_focus，应被加载"""
        assert len(novel_params_tab._desc_focus_data) == 3

    def test_add_and_delete(self, novel_params_tab, qapp):
        tab = novel_params_tab
        initial = len(tab._desc_focus_data)
        tab._add_desc_focus()
        assert len(tab._desc_focus_data) == initial + 1
        tab._lw_desc_focus.setCurrentRow(initial)  # 选中刚添加的空项
        tab._del_desc_focus()
        assert len(tab._desc_focus_data) == initial

    def test_move_up_down(self, novel_params_tab):
        tab = novel_params_tab
        tab._desc_focus_data = ["A", "B", "C"]
        tab._refresh_desc_focus_list()
        tab._lw_desc_focus.setCurrentRow(2)
        tab._move_desc_focus(-1)
        assert tab._desc_focus_data == ["A", "C", "B"]
        tab._move_desc_focus(1)
        assert tab._desc_focus_data == ["A", "B", "C"]

    def test_save_filters_blank_entries(self, novel_params_tab, example_config_path):
        tab = novel_params_tab
        tab._desc_focus_data = ["有效内容", "  ", "", "另一条"]
        with patch("src.gui.tabs.novel_params_tab.QMessageBox"):
            tab._save_to_file()
        cfg = json.load(open(example_config_path))
        focus = cfg["novel_config"]["writing_guide"]["style_guide"]["description_focus"]
        assert focus == ["有效内容", "另一条"]


# ===========================================================================
# 方案 4.1: 灾难锚点 load / save 往返
# ===========================================================================
class TestDisasterAnchorRoundTrip:
    def test_load_from_example(self, novel_params_tab):
        # config.json.example 含三条灾难
        assert "漓江派" in novel_params_tab._te_disaster_1.toPlainText()
        assert "天魔教" in novel_params_tab._te_disaster_2.toPlainText()
        assert "延康国" in novel_params_tab._te_disaster_3.toPlainText()

    def test_round_trip(self, novel_params_tab, example_config_path):
        tab = novel_params_tab
        tab._te_disaster_1.setPlainText("D1 修改后")
        tab._te_disaster_2.setPlainText("D2 修改后")
        tab._te_disaster_3.setPlainText("D3 修改后")
        with patch("src.gui.tabs.novel_params_tab.QMessageBox"):
            tab._save_to_file()
        cfg = json.load(open(example_config_path))
        d = cfg["novel_config"]["writing_guide"]["plot_structure"]["disasters"]
        assert d["first_disaster"] == "D1 修改后"
        assert d["second_disaster"] == "D2 修改后"
        assert d["third_disaster"] == "D3 修改后"


# ===========================================================================
# 方案 3: 角色结构化编辑器
# ===========================================================================
class TestRoleEditor:
    def test_initial_load_keeps_count(self, novel_params_tab):
        """example 含 6 配角 + 4 反派"""
        assert len(novel_params_tab._sup_data) == 6
        assert len(novel_params_tab._ant_data) == 4

    def test_add_role(self, novel_params_tab):
        tab = novel_params_tab
        before = len(tab._sup_data)
        tab._add_role("_sup_data")
        assert len(tab._sup_data) == before + 1
        # 新增项应包含必备 key
        new_item = tab._sup_data[-1]
        assert {"name", "gender", "role_type", "personality", "relationship"}.issubset(set(new_item.keys()))

    def test_add_antagonist_uses_conflict_key(self, novel_params_tab):
        tab = novel_params_tab
        tab._add_role("_ant_data")
        new_item = tab._ant_data[-1]
        assert "conflict_point" in new_item
        assert "relationship" not in new_item

    def test_delete_role(self, novel_params_tab):
        tab = novel_params_tab
        before = len(tab._sup_data)
        tab._sup_lw.setCurrentRow(0)
        tab._del_role("_sup_data")
        assert len(tab._sup_data) == before - 1

    def test_move_role(self, novel_params_tab):
        tab = novel_params_tab
        tab._sup_data = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
        tab._refresh_role_list("_sup_data")
        tab._sup_lw.setCurrentRow(0)
        tab._move_role("_sup_data", 1)
        assert tab._sup_data[0]["name"] == "B"
        assert tab._sup_data[1]["name"] == "A"

    def test_load_roles_handles_string_items(self, novel_params_tab):
        """容错：若历史配置中有 str 元素应转为 dict"""
        tab = novel_params_tab
        tab._load_roles("_sup_data", ["旧字符串配角", {"name": "新dict"}])
        assert tab._sup_data[0] == {"name": "旧字符串配角"}
        assert tab._sup_data[1]["name"] == "新dict"

    def test_save_filters_blank_roles(self, novel_params_tab, example_config_path):
        tab = novel_params_tab
        tab._sup_data = [
            {"name": "实角色", "gender": "男", "role_type": "导师", "personality": "稳重", "relationship": "师父"},
            {"name": "", "gender": "", "role_type": "", "personality": "", "relationship": ""},
        ]
        tab._ant_data = []
        with patch("src.gui.tabs.novel_params_tab.QMessageBox"):
            tab._save_to_file()
        cfg = json.load(open(example_config_path))
        sr = cfg["novel_config"]["writing_guide"]["character_guide"]["supporting_roles"]
        assert len(sr) == 1
        assert sr[0]["name"] == "实角色"

    def test_role_detail_edit_propagates(self, novel_params_tab):
        tab = novel_params_tab
        tab._sup_data = [{"name": "原名", "gender": "", "role_type": "", "personality": "", "relationship": ""}]
        tab._refresh_role_list("_sup_data")
        tab._sup_lw.setCurrentRow(0)
        tab._sup_le_name.setText("新名字")
        # textChanged 触发 _on_role_detail_changed
        assert tab._sup_data[0]["name"] == "新名字"


# ===========================================================================
# 方案 3: WritingGuideWorker 数量参数注入
# ===========================================================================
class TestWritingGuideWorkerCountParams:
    def test_constructor_clamps_values(self, qapp):
        from src.gui.workers.writing_guide_worker import WritingGuideWorker
        w = WritingGuideWorker(
            env_path="", story_idea="x", title="T",
            novel_type="N", theme="Th", style="S",
            n_supporting=-3, n_antagonists=999,
            female_ratio=1.5,
        )
        assert w._n_supporting == 0      # 负值被夹到 0
        assert w._n_antagonists == 999   # 上限不限制（GUI 的 SpinBox 已限制）
        assert w._female_ratio == 1.0    # 比例被夹到 [0,1]

    def test_prompt_template_renders_with_counts(self, qapp):
        from src.gui.workers.writing_guide_worker import _PROMPT
        text = _PROMPT.format(
            story_idea="少年成神", title="T", novel_type="玄幻",
            theme="成长", style="热血",
            n_supporting=7, n_antagonists=5, female_pct=40,
            target_chapters=200, total_words_wan="50",
        )
        assert "恰好生成 7" in text
        assert "恰好生成 5" in text
        assert "40%" in text
        assert "200 章" in text
        assert "50 万字" in text
        # 必含字段名
        assert "description_focus" in text
        assert '"name"' in text
        assert '"gender"' in text
        assert "disasters" in text
        # 篇幅建议
        assert "短篇" in text
        assert "长篇" in text


# ===========================================================================
# 方案 4.3: OutlineGenerator 注入伏笔（轻量 mock 路径）
# ===========================================================================
class TestOutlineGeneratorPendingForeshadowing:
    def test_pending_extracted_from_sync_info(self, mock_config, mock_model):
        """OutlineGenerator 从 sync_info 抽取未回收伏笔传给 prompt"""
        from src.generators.outline.outline_generator import OutlineGenerator

        gen = OutlineGenerator(mock_config, mock_model, knowledge_base=None)
        gen.sync_info = {
            "剧情发展": {
                "悬念伏笔": [
                    "玉佩之谜",
                    {"内容": "神秘老者", "其他": "ignore"},
                    {"名称": "无忧乡传说"},
                ]
            }
        }
        captured = {}

        def fake_get_outline_prompt(**kwargs):
            captured.update(kwargs)
            return "PROMPT"

        # 替换 prompts 模块中的函数（OutlineGenerator 顶部 from import 拿到的引用）
        with patch("src.generators.outline.outline_generator.get_outline_prompt",
                   side_effect=fake_get_outline_prompt):
            mock_model.generate_responses = ["[]"]
            try:
                gen._generate_batch(
                    batch_start_num=1, batch_end_num=5,
                    novel_type="玄幻", theme="成长", style="热血",
                    extra_prompt=None,
                    successful_outlines_in_run=[],
                )
            except Exception:
                # 即使后续流程失败，我们只关心 captured 中的 pending_foreshadowing
                pass

        pf = captured.get("pending_foreshadowing", [])
        assert "玉佩之谜" in pf
        assert "神秘老者" in pf
        assert "无忧乡传说" in pf
