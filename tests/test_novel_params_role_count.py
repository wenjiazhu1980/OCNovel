# -*- coding: utf-8 -*-
"""
测试 NovelParamsTab._on_generate_guide 的「目标总数 - 已有数量」语义

回归保护提交 3576b44 的核心修复:
  spinbox 表示「配角/反派的目标总数」,真正传给 WritingGuideWorker 的
  n_supporting/n_antagonists 必须是 max(0, target - existing)。
"""

import os
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Qt 环境 fixture
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def qapp():
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        pytest.skip("PySide6 not installed, skipping GUI tests")

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


# ---------------------------------------------------------------------------
# 测试夹具:构建 NovelParamsTab,绕过真正的 worker 与 messagebox
# ---------------------------------------------------------------------------
@pytest.fixture
def tab(qapp):
    """
    构造 NovelParamsTab,使用不存在的 config 路径(silent=True 时无副作用),
    并 patch 掉 WritingGuideWorker / QMessageBox 让 _on_generate_guide 可单步执行。
    """
    from src.gui.tabs import novel_params_tab as mod

    with patch.object(mod, "WritingGuideWorker") as mock_worker_cls, \
         patch.object(mod, "QMessageBox") as mock_msgbox:
        # 让 worker.start() 不真正起线程;返回的实例使用 MagicMock
        mock_worker = MagicMock()
        mock_worker_cls.return_value = mock_worker

        t = mod.NovelParamsTab(config_path="/nonexistent/__test__.json")
        # 暴露 mock 给测试函数,便于断言构造参数
        t._test_mock_worker_cls = mock_worker_cls
        t._test_mock_worker = mock_worker
        t._test_mock_msgbox = mock_msgbox

        yield t

        # 清理:不要让 Qt 持有 mock 对象的悬挂引用
        t.deleteLater()


def _set_role_data(tab, sup_count: int, ant_count: int):
    """直接灌注 _sup_data / _ant_data,模拟"已有 N 个角色"场景"""
    tab._sup_data = [{"name": f"配角{i}"} for i in range(sup_count)]
    tab._ant_data = [{"name": f"反派{i}"} for i in range(ant_count)]


def _trigger_generate(tab, target_sup: int, target_ant: int, story_idea: str = "测试故事种子"):
    """填好必要字段后调用 _on_generate_guide,返回 worker 构造时的 kwargs"""
    tab._le_story_idea.setText(story_idea)
    tab._sp_gen_supporting.setValue(target_sup)
    tab._sp_gen_antagonists.setValue(target_ant)
    tab._on_generate_guide()
    # WritingGuideWorker 至少被调用一次(无论 diff 是否 <=0,worker 仍启动)
    assert tab._test_mock_worker_cls.called, "WritingGuideWorker 未被实例化"
    _, kwargs = tab._test_mock_worker_cls.call_args
    return kwargs


# ---------------------------------------------------------------------------
# 核心语义测试
# ---------------------------------------------------------------------------
class TestRoleCountSemantics:
    """目标总数 - 已有数量 = 实际新增数量(下限 0)"""

    def test_zero_existing_full_target(self, tab):
        """已有 0,目标 6 → 新增 6"""
        _set_role_data(tab, 0, 0)
        kw = _trigger_generate(tab, target_sup=6, target_ant=4)
        assert kw["n_supporting"] == 6
        assert kw["n_antagonists"] == 4

    def test_existing_below_target(self, tab):
        """已有 4,目标 6 → 新增 2(典型增补场景)"""
        _set_role_data(tab, 4, 1)
        kw = _trigger_generate(tab, target_sup=6, target_ant=4)
        assert kw["n_supporting"] == 2
        assert kw["n_antagonists"] == 3

    def test_existing_equals_target(self, tab):
        """已有 6,目标 6 → 新增 0(不再生成新角色,但 worker 仍启动以更新其他字段)"""
        _set_role_data(tab, 6, 4)
        kw = _trigger_generate(tab, target_sup=6, target_ant=4)
        assert kw["n_supporting"] == 0
        assert kw["n_antagonists"] == 0

    def test_existing_exceeds_target_clamped_to_zero(self, tab):
        """已有 10 > 目标 6 → 钳制到 0(GUI 不支持反向删除,保持现状)"""
        _set_role_data(tab, 10, 8)
        kw = _trigger_generate(tab, target_sup=6, target_ant=4)
        assert kw["n_supporting"] == 0
        assert kw["n_antagonists"] == 0

    def test_state_cached_for_result_dialog(self, tab):
        """生成请求时缓存 target/existing/request 三元组,供完成弹框引用"""
        _set_role_data(tab, 4, 1)
        _trigger_generate(tab, target_sup=6, target_ant=4)
        assert tab._guide_target_sup == 6
        assert tab._guide_target_ant == 4
        assert tab._guide_existing_sup == 4
        assert tab._guide_existing_ant == 1
        assert tab._guide_request_sup == 2
        assert tab._guide_request_ant == 3

    def test_empty_story_idea_aborts(self, tab):
        """故事种子为空时直接 return,worker 不应被实例化"""
        _set_role_data(tab, 0, 0)
        tab._le_story_idea.setText("")  # 关键:故事种子留空
        tab._sp_gen_supporting.setValue(6)
        tab._sp_gen_antagonists.setValue(4)
        tab._on_generate_guide()
        assert not tab._test_mock_worker_cls.called, \
            "故事种子为空时不应启动 worker"

    def test_data_attributes_uninitialized_safe(self, qapp):
        """_sup_data / _ant_data 未初始化时仍应安全(getattr 默认空列表)"""
        from src.gui.tabs import novel_params_tab as mod
        with patch.object(mod, "WritingGuideWorker") as mock_worker_cls, \
             patch.object(mod, "QMessageBox"):
            mock_worker_cls.return_value = MagicMock()
            t = mod.NovelParamsTab(config_path="/nonexistent/__test2__.json")
            try:
                # 故意删除属性,模拟极端边界
                if hasattr(t, "_sup_data"):
                    delattr(t, "_sup_data")
                if hasattr(t, "_ant_data"):
                    delattr(t, "_ant_data")
                t._le_story_idea.setText("seed")
                t._sp_gen_supporting.setValue(5)
                t._sp_gen_antagonists.setValue(3)
                # 不应抛异常
                t._on_generate_guide()
                _, kwargs = mock_worker_cls.call_args
                assert kwargs["n_supporting"] == 5
                assert kwargs["n_antagonists"] == 3
            finally:
                t.deleteLater()
