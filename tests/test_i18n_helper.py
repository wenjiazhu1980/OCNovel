# -*- coding: utf-8 -*-
"""[5.4] RetranslateRegistry 注册式 i18n 辅助测试"""

import pytest
from unittest.mock import MagicMock
from src.gui.utils.i18n_helper import RetranslateRegistry


@pytest.fixture
def registry():
    """注册表 + 简单的 tr (中→英映射,模拟 .qm 翻译)"""
    translations = {
        "保存": "Save",
        "加载": "Load",
        "选项": "Options",
        "请输入": "Please enter",
    }
    tr_func = lambda s: translations.get(s, s)
    return RetranslateRegistry(tr_func)


def _make_widget():
    """伪 widget,记录所有 setter 调用"""
    w = MagicMock()
    return w


class TestRetranslateRegistry:
    def test_register_text_and_retranslate(self, registry):
        w = _make_widget()
        registry.register_text(w, "保存")
        count = registry.retranslate_all()
        assert count == 1
        w.setText.assert_called_once_with("Save")

    def test_register_title(self, registry):
        gb = _make_widget()
        registry.register_title(gb, "选项")
        registry.retranslate_all()
        gb.setTitle.assert_called_once_with("Options")

    def test_register_tooltip(self, registry):
        w = _make_widget()
        registry.register_tooltip(w, "保存")
        registry.retranslate_all()
        w.setToolTip.assert_called_once_with("Save")

    def test_register_placeholder(self, registry):
        le = _make_widget()
        registry.register_placeholder(le, "请输入")
        registry.retranslate_all()
        le.setPlaceholderText.assert_called_once_with("Please enter")

    def test_register_window_title(self, registry):
        win = _make_widget()
        registry.register_window_title(win, "保存")
        registry.retranslate_all()
        win.setWindowTitle.assert_called_once_with("Save")

    def test_multiple_widgets(self, registry):
        w1 = _make_widget()
        w2 = _make_widget()
        w3 = _make_widget()
        registry.register_text(w1, "保存")
        registry.register_text(w2, "加载")
        registry.register_title(w3, "选项")
        count = registry.retranslate_all()
        assert count == 3
        w1.setText.assert_called_once_with("Save")
        w2.setText.assert_called_once_with("Load")
        w3.setTitle.assert_called_once_with("Options")

    def test_destroyed_widget_skipped(self, registry):
        """RuntimeError(widget 已销毁) 应被静默跳过,不影响其他 widget"""
        dead = MagicMock()
        dead.setText.side_effect = RuntimeError("Internal C++ object already deleted")
        live = MagicMock()
        registry.register_text(dead, "保存")
        registry.register_text(live, "加载")
        # 不应抛
        count = registry.retranslate_all()
        # 一个成功,一个被异常吃掉
        assert count == 1
        live.setText.assert_called_once_with("Load")

    def test_idempotent_multiple_calls(self, registry):
        """多次切换语言不会累积/丢失注册项"""
        w = _make_widget()
        registry.register_text(w, "保存")
        registry.retranslate_all()
        registry.retranslate_all()
        registry.retranslate_all()
        assert w.setText.call_count == 3

    def test_none_widget_ignored(self, registry):
        """传入 None 不应炸"""
        registry.register_text(None, "保存")
        registry.register_title(None, "选项")
        # 注册表应忽略 None
        assert len(registry) == 0

    def test_custom_setter(self, registry):
        """自定义 setter 用于拼接场景"""
        captured = []
        registry.register_custom(
            lambda translated: captured.append(f"[{translated}]"),
            "保存",
        )
        registry.retranslate_all()
        assert captured == ["[Save]"]

    def test_unknown_key_returns_self(self, registry):
        """未翻译的 key 应保留原文(通常是中文 fallback)"""
        w = _make_widget()
        registry.register_text(w, "未在词典中的中文")
        registry.retranslate_all()
        w.setText.assert_called_once_with("未在词典中的中文")

    def test_len(self, registry):
        assert len(registry) == 0
        registry.register_text(_make_widget(), "保存")
        registry.register_title(_make_widget(), "选项")
        assert len(registry) == 2
