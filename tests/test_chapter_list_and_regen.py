# -*- coding: utf-8 -*-
"""
测试章节列表组件、章节目录加载、重新生成指定章节功能
覆盖：ChapterListWidget 状态管理、ProgressTab.load_chapters、PipelineWorker 指定章节模式
"""

import os
import json
import pytest
from unittest.mock import patch, MagicMock

# ---------------------------------------------------------------------------
# Qt 环境 fixture
# ---------------------------------------------------------------------------
_qapp = None


@pytest.fixture(scope="module")
def qapp():
    """确保整个测试模块共享一个 QApplication 实例"""
    global _qapp
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        pytest.skip("PySide6 not installed, skipping GUI tests")

    _qapp = QApplication.instance()
    if _qapp is None:
        _qapp = QApplication([])
    yield _qapp


# ---------------------------------------------------------------------------
# ChapterListWidget 测试
# ---------------------------------------------------------------------------
class TestChapterListWidget:
    """测试章节列表组件的状态管理和查询功能"""

    def _make_widget(self, qapp, total=10):
        from src.gui.widgets.chapter_list import ChapterListWidget
        w = ChapterListWidget()
        w.init_chapters(total)
        return w

    def test_init_chapters(self, qapp):
        """初始化后应有正确数量的条目，且全部为 pending"""
        w = self._make_widget(qapp, 5)
        assert w.count() == 5
        assert w.get_completed_count() == 0

    def test_set_chapter_status_completed(self, qapp):
        """标记章节完成后，完成计数应增加"""
        w = self._make_widget(qapp, 5)
        w.set_chapter_status(1, "completed")
        w.set_chapter_status(3, "completed")
        assert w.get_completed_count() == 2

    def test_set_chapter_status_stores_user_role(self, qapp):
        """状态应存储在 item 的 UserRole 中"""
        from PySide6.QtCore import Qt
        w = self._make_widget(qapp, 3)
        w.set_chapter_status(2, "failed")
        item = w.item(1)  # chapter 2 = index 1
        assert item.data(Qt.UserRole) == "failed"

    def test_set_chapter_status_out_of_range(self, qapp):
        """超出范围的章节号不应导致异常"""
        w = self._make_widget(qapp, 3)
        w.set_chapter_status(0, "completed")   # 0 < 1
        w.set_chapter_status(99, "completed")  # 99 > 3
        assert w.get_completed_count() == 0

    def test_get_selected_chapter_numbers_empty(self, qapp):
        """无选中时返回空列表"""
        w = self._make_widget(qapp, 5)
        assert w.get_selected_chapter_numbers() == []

    def test_get_selected_chapter_numbers(self, qapp):
        """选中条目后应返回正确的章节编号列表"""
        w = self._make_widget(qapp, 5)
        # 模拟选中第 2 和第 4 项
        w.item(1).setSelected(True)
        w.item(3).setSelected(True)
        result = w.get_selected_chapter_numbers()
        assert result == [2, 4]

    def test_get_non_completed_chapter_numbers(self, qapp):
        """应返回所有非 completed 状态的章节编号"""
        w = self._make_widget(qapp, 5)
        w.set_chapter_status(1, "completed")
        w.set_chapter_status(3, "completed")
        w.set_chapter_status(4, "failed")
        result = w.get_non_completed_chapter_numbers()
        assert result == [2, 4, 5]

    def test_reinit_clears_old_items(self, qapp):
        """重新初始化应清除旧条目"""
        w = self._make_widget(qapp, 10)
        w.set_chapter_status(5, "completed")
        assert w.get_completed_count() == 1

        w.init_chapters(3)
        assert w.count() == 3
        assert w.get_completed_count() == 0

    def test_running_status_scrolls(self, qapp):
        """设置 running 状态不应异常（验证 scrollToItem 不崩溃）"""
        w = self._make_widget(qapp, 10)
        w.set_chapter_status(8, "running")
        from PySide6.QtCore import Qt
        assert w.item(7).data(Qt.UserRole) == "running"


# ---------------------------------------------------------------------------
# ProgressTab.load_chapters 测试
# ---------------------------------------------------------------------------
class TestProgressTabLoadChapters:
    """测试章节目录的自动/手动加载"""

    def _make_tab(self, qapp, tmp_path, target_chapters=10, summary_data=None):
        """创建一个 ProgressTab，配置文件和 summary.json 放在 tmp_path"""
        config_path = str(tmp_path / "config.json")
        env_path = str(tmp_path / ".env")
        output_dir = str(tmp_path / "output")
        os.makedirs(output_dir, exist_ok=True)

        cfg = {
            "novel_config": {"target_chapters": target_chapters},
            "output_config": {"output_dir": output_dir},
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)

        with open(env_path, "w") as f:
            f.write("")

        if summary_data is not None:
            summary_file = os.path.join(output_dir, "summary.json")
            with open(summary_file, "w", encoding="utf-8") as f:
                json.dump(summary_data, f)

        from src.gui.tabs.progress_tab import ProgressTab
        tab = ProgressTab(config_path, env_path)
        return tab

    def test_load_chapters_basic(self, qapp, tmp_path):
        """无 summary.json 时应全部为 pending"""
        tab = self._make_tab(qapp, tmp_path, target_chapters=5)
        tab.load_chapters()
        assert tab.chapter_list.count() == 5
        assert tab.chapter_list.get_completed_count() == 0
        assert tab.progress_bar.maximum() == 5
        assert tab.progress_bar.value() == 0

    def test_load_chapters_with_summary(self, qapp, tmp_path):
        """有 summary.json 时应正确标记已完成章节"""
        summary = {"1": {"title": "ch1"}, "3": {"title": "ch3"}, "5": {"title": "ch5"}}
        tab = self._make_tab(qapp, tmp_path, target_chapters=5, summary_data=summary)
        tab.load_chapters()
        assert tab.chapter_list.get_completed_count() == 3
        assert tab.progress_bar.value() == 3

    def test_load_chapters_ignores_out_of_range(self, qapp, tmp_path):
        """summary 中超出 target_chapters 范围的章节应忽略"""
        summary = {"1": {}, "99": {}}  # 99 超出范围
        tab = self._make_tab(qapp, tmp_path, target_chapters=5, summary_data=summary)
        tab.load_chapters()
        assert tab.chapter_list.get_completed_count() == 1

    def test_load_chapters_skipped_during_pipeline(self, qapp, tmp_path):
        """流水线运行中调用 load_chapters 不应重置列表"""
        tab = self._make_tab(qapp, tmp_path, target_chapters=5)
        tab.load_chapters()
        tab.chapter_list.set_chapter_status(2, "running")

        # 模拟流水线运行中
        tab._worker = MagicMock()
        tab.load_chapters()

        # running 状态不应被覆盖
        from PySide6.QtCore import Qt
        assert tab.chapter_list.item(1).data(Qt.UserRole) == "running"

        tab._worker = None  # cleanup

    def test_load_chapters_invalid_target(self, qapp, tmp_path):
        """target_chapters <= 0 时 load_chapters 不应崩溃"""
        tab = self._make_tab(qapp, tmp_path, target_chapters=0)
        tab.load_chapters()  # 应静默返回
        assert tab.chapter_list.count() == 0

    def test_load_chapters_corrupted_summary(self, qapp, tmp_path):
        """损坏的 summary.json 不应导致崩溃"""
        config_path = str(tmp_path / "config.json")
        env_path = str(tmp_path / ".env")
        output_dir = str(tmp_path / "output")
        os.makedirs(output_dir, exist_ok=True)

        cfg = {
            "novel_config": {"target_chapters": 5},
            "output_config": {"output_dir": output_dir},
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        with open(env_path, "w") as f:
            f.write("")

        # 写入损坏的 JSON
        with open(os.path.join(output_dir, "summary.json"), "w") as f:
            f.write("{invalid json")

        from src.gui.tabs.progress_tab import ProgressTab
        tab = ProgressTab(config_path, env_path)
        tab.load_chapters()  # 不应崩溃
        assert tab.chapter_list.count() == 5
        assert tab.chapter_list.get_completed_count() == 0


# ---------------------------------------------------------------------------
# PipelineWorker 指定章节模式测试（纯逻辑，不启动线程）
# ---------------------------------------------------------------------------
class TestPipelineWorkerTargetChapters:
    """测试 PipelineWorker 的 target_chapters_list 参数"""

    def test_default_no_target_list(self):
        """默认构造时 target_chapters_list 为 None"""
        from src.gui.workers.pipeline_worker import PipelineWorker
        worker = PipelineWorker(
            config_path="dummy.json",
            env_path="dummy.env",
        )
        assert worker._target_chapters_list is None

    def test_with_target_list(self):
        """指定章节列表应正确存储"""
        from src.gui.workers.pipeline_worker import PipelineWorker
        worker = PipelineWorker(
            config_path="dummy.json",
            env_path="dummy.env",
            target_chapters_list=[3, 5, 7],
        )
        assert worker._target_chapters_list == [3, 5, 7]

    def test_chapter_list_generation_logic(self):
        """验证指定章节模式下的章节列表构建逻辑"""
        # 模拟 PipelineWorker.run() 中的核心逻辑
        target_chapters_list = [3, 5, 8]
        end_chapter = 10

        # 指定章节模式
        chapters_to_generate = [
            ch for ch in target_chapters_list
            if 1 <= ch <= end_chapter
        ]
        assert chapters_to_generate == [3, 5, 8]

    def test_chapter_list_filters_out_of_range(self):
        """超出范围的章节应被过滤"""
        target_chapters_list = [0, 3, 5, 15]
        end_chapter = 10

        chapters_to_generate = [
            ch for ch in target_chapters_list
            if 1 <= ch <= end_chapter
        ]
        assert chapters_to_generate == [3, 5]

    def test_target_mode_outline_requirement_uses_selected_chapter_upper_bound(self):
        """指定章节模式下，只应要求大纲覆盖到所选章节上限"""
        from src.gui.workers.pipeline_worker import PipelineWorker

        worker = PipelineWorker(
            config_path="dummy.json",
            env_path="dummy.env",
            target_chapters_list=[3, 5, 15],
        )

        assert worker._get_requested_target_chapters(10) == [3, 5]
        assert worker._get_required_outline_chapters(10) == 5

    def test_run_allows_regen_when_outline_covers_selected_chapter_only(self, qapp, mock_config):
        """即使 target_chapters 更大，只要大纲覆盖所选章节就应允许重生成"""
        from src.gui.workers.pipeline_worker import PipelineWorker

        mock_config.novel_config["target_chapters"] = 10

        mock_ai_config = MagicMock()
        mock_ai_config.get_openai_config.return_value = {"type": "openai"}

        mock_outline_generator = MagicMock()
        mock_outline_generator.chapter_outlines = [
            MagicMock(title="第1章"),
            MagicMock(title="第2章"),
            MagicMock(title="第3章"),
        ]

        mock_content_generator = MagicMock()
        mock_content_generator.chapter_outlines = [
            MagicMock(title="第1章"),
            MagicMock(title="第2章"),
            MagicMock(title="第3章"),
        ]
        mock_content_generator.generate_content.return_value = True
        # [Follow-up to a1232e7] _outline_discontinuous 必须为空列表(否则触发补洞分支)
        mock_content_generator._outline_discontinuous = []
        mock_content_generator._chapters_in_summary = set()
        mock_content_generator._length_warnings = {}
        # 补洞函数若被调用应返回 (succeeded, still_missing) 元组
        mock_outline_generator.patch_missing_chapters.return_value = ([], [])

        worker = PipelineWorker(
            config_path="dummy.json",
            env_path="dummy.env",
            target_chapters_list=[3],
        )

        finished = []
        completed = []
        worker.pipeline_finished.connect(lambda ok: finished.append(ok))
        worker.chapter_completed.connect(lambda num, title: completed.append((num, title)))

        with patch("src.config.config.Config", return_value=mock_config), \
             patch("src.config.ai_config.AIConfig", return_value=mock_ai_config), \
             patch("src.generators.common.utils.setup_logging"), \
             patch("src.gui.workers.pipeline_worker.create_model", return_value=MagicMock()), \
             patch("src.knowledge_base.knowledge_base.KnowledgeBase", return_value=MagicMock()), \
             patch("src.generators.finalizer.finalizer.NovelFinalizer", return_value=MagicMock()), \
             patch("src.generators.outline.outline_generator.OutlineGenerator", return_value=mock_outline_generator), \
             patch("src.generators.content.content_generator.ContentGenerator", return_value=mock_content_generator):
            worker.run()

        mock_outline_generator.generate_outline.assert_not_called()
        mock_content_generator.generate_content.assert_called_once_with(
            target_chapter=3,
            external_prompt=None,
            is_target_chapter=True,
        )
        assert completed == [(3, "第3章")]
        assert finished == [True]

    def test_continuous_mode_logic(self):
        """连续模式下应生成从 start 到 end 的完整范围"""
        target_chapters_list = None
        start_chapter = 6
        end_chapter = 10

        if target_chapters_list:
            chapters_to_generate = [
                ch for ch in target_chapters_list
                if 1 <= ch <= end_chapter
            ]
        else:
            chapters_to_generate = list(range(start_chapter, end_chapter + 1))

        assert chapters_to_generate == [6, 7, 8, 9, 10]


# ---------------------------------------------------------------------------
# ProgressTab._start_pipeline 重新生成模式测试
# ---------------------------------------------------------------------------
class TestProgressTabRegen:
    """测试重新生成选中章节的 UI 逻辑"""

    def _make_tab(self, qapp, tmp_path, target_chapters=10, summary_data=None):
        config_path = str(tmp_path / "config.json")
        env_path = str(tmp_path / ".env")
        output_dir = str(tmp_path / "output")
        os.makedirs(output_dir, exist_ok=True)

        cfg = {
            "novel_config": {"target_chapters": target_chapters},
            "output_config": {"output_dir": output_dir},
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        with open(env_path, "w") as f:
            f.write("")

        if summary_data is not None:
            with open(os.path.join(output_dir, "summary.json"), "w", encoding="utf-8") as f:
                json.dump(summary_data, f)

        from src.gui.tabs.progress_tab import ProgressTab
        return ProgressTab(config_path, env_path)

    def test_regen_marks_selected_as_pending(self, qapp, tmp_path):
        """重新生成模式下，被选中的已完成章节应标记为 pending"""
        summary = {str(i): {"title": f"ch{i}"} for i in range(1, 11)}
        tab = self._make_tab(qapp, tmp_path, target_chapters=10, summary_data=summary)

        # 模拟 _start_pipeline 中的标记逻辑（不实际启动 worker）
        from src.gui.utils.config_io import load_config
        cfg = load_config(tab._config_path)
        target_chapters = cfg["novel_config"]["target_chapters"]
        target_list = [3, 5, 7]

        tab.chapter_list.init_chapters(target_chapters)

        output_dir = cfg["output_config"]["output_dir"]
        if not os.path.isabs(output_dir):
            output_dir = os.path.join(os.path.dirname(tab._config_path), output_dir)
        summary_file = os.path.join(output_dir, "summary.json")
        completed_count = 0
        with open(summary_file, "r", encoding="utf-8") as f:
            summary_data = json.load(f)
        for key in summary_data:
            if key.isdigit():
                ch = int(key)
                if 1 <= ch <= target_chapters:
                    if ch in target_list:
                        tab.chapter_list.set_chapter_status(ch, "pending")
                    else:
                        tab.chapter_list.set_chapter_status(ch, "completed")
                        completed_count += 1

        # 第 3、5、7 章应为 pending，其余为 completed
        from PySide6.QtCore import Qt
        assert tab.chapter_list.item(2).data(Qt.UserRole) == "pending"   # ch3
        assert tab.chapter_list.item(4).data(Qt.UserRole) == "pending"   # ch5
        assert tab.chapter_list.item(6).data(Qt.UserRole) == "pending"   # ch7
        assert tab.chapter_list.item(0).data(Qt.UserRole) == "completed" # ch1
        assert tab.chapter_list.item(8).data(Qt.UserRole) == "completed" # ch9
        assert completed_count == 7

    def test_button_state_on_selection(self, qapp, tmp_path):
        """选中章节时 regen 按钮应启用，清除选择后禁用"""
        tab = self._make_tab(qapp, tmp_path, target_chapters=5)
        tab.load_chapters()

        # 无选中 → 禁用
        assert tab.btn_regen.isEnabled() is False

        # 选中 → 启用
        tab.chapter_list.item(1).setSelected(True)
        tab._on_selection_changed()
        assert tab.btn_regen.isEnabled() is True
        assert "1" in tab.btn_regen.text()

        # 清除选择 → 禁用
        tab.chapter_list.clearSelection()
        tab._on_selection_changed()
        assert tab.btn_regen.isEnabled() is False

    def test_button_disabled_during_pipeline(self, qapp, tmp_path):
        """流水线运行中 regen 按钮应禁用"""
        tab = self._make_tab(qapp, tmp_path, target_chapters=5)
        tab.load_chapters()
        tab.chapter_list.item(0).setSelected(True)

        # 模拟流水线运行中
        tab._worker = MagicMock()
        tab._on_selection_changed()
        assert tab.btn_regen.isEnabled() is False

        tab._worker = None


# ---------------------------------------------------------------------------
# ProgressTab 大纲审计复核入口测试
# ---------------------------------------------------------------------------
class TestProgressTabOutlineAudit:
    """测试手动大纲审计复核按钮"""

    def _make_tab(self, qapp, tmp_path, with_outline=False, with_audit_report=False):
        config_path = str(tmp_path / "config.json")
        env_path = str(tmp_path / ".env")
        output_dir = tmp_path / "output"
        output_dir.mkdir(exist_ok=True)

        cfg = {
            "novel_config": {"target_chapters": 5},
            "output_config": {"output_dir": str(output_dir)},
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        with open(env_path, "w", encoding="utf-8") as f:
            f.write("")

        if with_outline:
            with open(output_dir / "outline.json", "w", encoding="utf-8") as f:
                json.dump([
                    {
                        "chapter_number": 1,
                        "title": "第一章",
                        "key_points": ["系统发布任务：清剿黑风寨"],
                        "characters": ["主角"],
                        "settings": ["山村"],
                        "conflicts": ["匪患"],
                    }
                ], f, ensure_ascii=False)

        if with_audit_report:
            with open(output_dir / "outline_audit_report.json", "w", encoding="utf-8") as f:
                json.dump({
                    "total": 1,
                    "fatal": 1,
                    "warning": 0,
                    "findings": [
                        {
                            "rule": "O3-LLM",
                            "severity": "fatal",
                            "chapter": 1,
                            "message": "任务未闭环",
                        }
                    ],
                }, f, ensure_ascii=False)

        from src.gui.tabs.progress_tab import ProgressTab
        return ProgressTab(config_path, env_path)

    def test_button_exists(self, qapp, tmp_path):
        """ProgressTab 初始化后应包含大纲审计按钮"""
        tab = self._make_tab(qapp, tmp_path)
        assert hasattr(tab, "btn_outline_audit")
        assert "大纲审计复核" in tab.btn_outline_audit.text()

    def test_novel_audit_range_resolver_requires_complete_range(self, qapp, tmp_path):
        """小说审计范围应区分整部、完整闭区间与不完整范围。"""
        tab = self._make_tab(qapp, tmp_path)

        tab.spin_audit_start.setValue(0)
        tab.spin_audit_end.setValue(0)
        assert tab._resolve_novel_audit_chapters(selected_only=False) is None

        tab.spin_audit_start.setValue(10)
        tab.spin_audit_end.setValue(0)
        assert tab._resolve_novel_audit_chapters(selected_only=False) == []

        tab.spin_audit_start.setValue(0)
        tab.spin_audit_end.setValue(20)
        assert tab._resolve_novel_audit_chapters(selected_only=False) == []

        tab.spin_audit_start.setValue(5)
        tab.spin_audit_end.setValue(3)
        assert tab._resolve_novel_audit_chapters(selected_only=False) == [3, 4, 5]

    def test_running_task_blocks_outline_audit(self, qapp, tmp_path):
        """已有任务运行时不应创建审计 worker"""
        tab = self._make_tab(qapp, tmp_path, with_outline=True)
        tab._worker = MagicMock()

        with patch("src.gui.tabs.progress_tab.QMessageBox.warning") as mock_warning:
            tab._on_run_outline_audit()

        mock_warning.assert_called_once()
        assert tab._outline_audit_worker is None
        tab._worker = None

    def test_missing_outline_blocks_outline_audit(self, qapp, tmp_path):
        """缺少 outline.json 时不应启动审计"""
        tab = self._make_tab(qapp, tmp_path, with_outline=False)

        with patch("src.gui.tabs.progress_tab.QMessageBox.warning") as mock_warning:
            tab._on_run_outline_audit()

        mock_warning.assert_called_once()
        assert tab._outline_audit_worker is None

    def test_start_outline_audit_creates_worker_and_busy_state(self, qapp, tmp_path):
        """正常启动时应创建 worker 并进入忙碌状态"""
        tab = self._make_tab(qapp, tmp_path, with_outline=True)
        running_states = []
        tab.pipeline_running_changed.connect(running_states.append)

        mock_worker = MagicMock()
        mock_worker.audit_finished.connect = MagicMock()
        mock_worker.log_message.connect = MagicMock()
        mock_worker.finished.connect = MagicMock()
        mock_worker.start = MagicMock()
        mock_worker.isRunning.return_value = True

        from PySide6.QtWidgets import QMessageBox

        with patch("src.gui.tabs.progress_tab.QMessageBox.question",
                   return_value=QMessageBox.Yes) as mock_question, \
             patch("src.gui.tabs.progress_tab.OutlineAuditWorker",
                   return_value=mock_worker) as mock_worker_cls:
            tab._on_run_outline_audit()

        mock_question.assert_called_once()
        mock_worker_cls.assert_called_once_with(
            config_path=tab._config_path,
            env_path=tab._env_path,
        )
        assert tab._outline_audit_worker is mock_worker
        assert tab.btn_outline_audit.isEnabled() is False
        assert "审计中" in tab.btn_outline_audit.text()
        assert tab.btn_start.isEnabled() is False
        assert tab.btn_outline_only.isEnabled() is False
        assert tab.btn_regen.isEnabled() is False
        assert tab.btn_refresh.isEnabled() is False
        assert tab.btn_merge.isEnabled() is False
        assert tab.btn_marketing.isEnabled() is False
        assert tab.btn_stop.isEnabled() is True
        assert running_states == [True]
        mock_worker.start.assert_called_once()

    def test_outline_audit_finished_restores_success_state(self, qapp, tmp_path):
        """审计成功完成后应恢复按钮状态"""
        tab = self._make_tab(qapp, tmp_path, with_outline=True)
        tab.btn_outline_audit.setEnabled(False)
        tab.btn_outline_audit.setText("⏳  审计中...")
        tab.btn_start.setEnabled(False)
        tab.btn_outline_only.setEnabled(False)
        tab.btn_merge.setEnabled(False)
        tab.btn_marketing.setEnabled(False)
        tab.btn_stop.setEnabled(True)

        with patch("src.gui.tabs.progress_tab.QMessageBox.information") as mock_info:
            tab._on_outline_audit_finished(True, "done")

        mock_info.assert_called_once()
        assert tab.btn_outline_audit.isEnabled() is True
        assert "大纲审计复核" in tab.btn_outline_audit.text()
        assert tab.btn_start.isEnabled() is True
        assert tab.btn_outline_only.isEnabled() is True
        assert tab.btn_refresh.isEnabled() is True
        assert tab.btn_merge.isEnabled() is True
        assert tab.btn_marketing.isEnabled() is True
        assert tab.btn_stop.isEnabled() is False

    def test_revision_button_exists(self, qapp, tmp_path):
        """ProgressTab 初始化后应包含大纲修订按钮"""
        tab = self._make_tab(qapp, tmp_path)
        assert hasattr(tab, "btn_outline_revision")
        assert "修订大纲" in tab.btn_outline_revision.text()

    def test_action_bar_buttons_keep_visible_gaps(self, qapp, tmp_path):
        """操作按钮应保留可见间距，避免默认窗口宽度下相邻按钮粘连"""
        tab = self._make_tab(qapp, tmp_path)
        tab.resize(1100, 700)
        tab.show()
        qapp.processEvents()

        assert all(layout.spacing() >= 12 for layout in tab._action_bar_layouts)

        button_rows = [
            [tab.btn_open_output, tab.btn_refresh, tab.btn_regen],
            [tab.btn_merge, tab.btn_marketing, tab.btn_outline_audit, tab.btn_outline_revision],
        ]
        for buttons in button_rows:
            gaps = []
            for left, right in zip(buttons, buttons[1:]):
                left_rect = left.geometry()
                right_rect = right.geometry()
                gaps.append(right_rect.x() - (left_rect.x() + left_rect.width()))

            assert min(gaps) >= 12

    def test_missing_audit_report_blocks_outline_revision(self, qapp, tmp_path):
        """缺少审计报告时不应启动修订"""
        tab = self._make_tab(qapp, tmp_path, with_outline=True, with_audit_report=False)

        with patch("src.gui.tabs.progress_tab.QMessageBox.warning") as mock_warning:
            tab._on_revise_outline_from_audit()

        mock_warning.assert_called_once()
        assert tab._outline_revision_worker is None

    def test_start_outline_revision_creates_worker_and_busy_state(self, qapp, tmp_path):
        """正常启动修订时应创建 worker 并进入忙碌状态"""
        tab = self._make_tab(qapp, tmp_path, with_outline=True, with_audit_report=True)
        running_states = []
        tab.pipeline_running_changed.connect(running_states.append)

        mock_worker = MagicMock()
        mock_worker.revision_finished.connect = MagicMock()
        mock_worker.log_message.connect = MagicMock()
        mock_worker.finished.connect = MagicMock()
        mock_worker.start = MagicMock()
        mock_worker.isRunning.return_value = True

        from PySide6.QtWidgets import QMessageBox

        with patch("src.gui.tabs.progress_tab.QMessageBox.question",
                   return_value=QMessageBox.Yes) as mock_question, \
             patch("src.gui.tabs.progress_tab.OutlineRevisionWorker",
                   return_value=mock_worker) as mock_worker_cls:
            tab._on_revise_outline_from_audit()

        mock_question.assert_called_once()
        mock_worker_cls.assert_called_once_with(
            config_path=tab._config_path,
            env_path=tab._env_path,
        )
        assert tab._outline_revision_worker is mock_worker
        assert tab.btn_outline_revision.isEnabled() is False
        assert "修订中" in tab.btn_outline_revision.text()
        assert tab.btn_outline_audit.isEnabled() is False
        assert tab.btn_start.isEnabled() is False
        assert tab.btn_outline_only.isEnabled() is False
        assert tab.btn_regen.isEnabled() is False
        assert tab.btn_refresh.isEnabled() is False
        assert tab.btn_merge.isEnabled() is False
        assert tab.btn_marketing.isEnabled() is False
        assert tab.btn_stop.isEnabled() is True
        assert running_states == [True]
        mock_worker.start.assert_called_once()

    def test_outline_revision_finished_restores_success_state(self, qapp, tmp_path):
        """修订完成后应恢复按钮状态"""
        tab = self._make_tab(qapp, tmp_path, with_outline=True, with_audit_report=True)
        tab.btn_outline_revision.setEnabled(False)
        tab.btn_outline_revision.setText("⏳  修订中...")
        tab.btn_outline_audit.setEnabled(False)
        tab.btn_start.setEnabled(False)
        tab.btn_outline_only.setEnabled(False)
        tab.btn_merge.setEnabled(False)
        tab.btn_marketing.setEnabled(False)
        tab.btn_stop.setEnabled(True)

        with patch("src.gui.tabs.progress_tab.QMessageBox.information") as mock_info:
            tab._on_outline_revision_finished(True, "done")

        mock_info.assert_called_once()
        assert tab.btn_outline_revision.isEnabled() is True
        assert "修订大纲" in tab.btn_outline_revision.text()
        assert tab.btn_outline_audit.isEnabled() is True
        assert tab.btn_start.isEnabled() is True
        assert tab.btn_outline_only.isEnabled() is True
        assert tab.btn_refresh.isEnabled() is True
        assert tab.btn_merge.isEnabled() is True
        assert tab.btn_marketing.isEnabled() is True
        assert tab.btn_stop.isEnabled() is False

    def test_outline_audit_finished_restores_failure_state(self, qapp, tmp_path):
        """审计失败完成后也应恢复按钮状态"""
        tab = self._make_tab(qapp, tmp_path, with_outline=True)
        tab.btn_outline_audit.setEnabled(False)
        tab.btn_start.setEnabled(False)
        tab.btn_outline_only.setEnabled(False)
        tab.btn_merge.setEnabled(False)
        tab.btn_marketing.setEnabled(False)
        tab.btn_stop.setEnabled(True)

        with patch("src.gui.tabs.progress_tab.QMessageBox.critical") as mock_critical:
            tab._on_outline_audit_finished(False, "bad")

        mock_critical.assert_called_once()
        assert tab.btn_outline_audit.isEnabled() is True
        assert tab.btn_start.isEnabled() is True
        assert tab.btn_outline_only.isEnabled() is True
        assert tab.btn_refresh.isEnabled() is True
        assert tab.btn_merge.isEnabled() is True
        assert tab.btn_marketing.isEnabled() is True
        assert tab.btn_stop.isEnabled() is False
