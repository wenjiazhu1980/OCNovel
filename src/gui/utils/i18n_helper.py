# -*- coding: utf-8 -*-
"""[5.4] i18n retranslate 注册式辅助模块

PySide6 在收到 QEvent.LanguageChange 时不会自动重新调用 self.tr() 对
代码构建的 UI 重应用翻译。本模块提供一个轻量注册表,各 Tab 在 __init__
时调用 register() 登记需要刷新的(widget, setter, source_text)三元组,
在 changeEvent(LanguageChange) 时统一回放即可。

设计要点:
- 不依赖 Qt Designer / .ui 文件的 retranslateUi 机制
- source_text 必须是原始中文字符串,与 self.tr(...) 调用时传入的 key 一致,
  这样 .qm 文件能正确匹配翻译条目
- 支持自定义 args 以覆盖 setText/setTitle/setToolTip/setPlaceholderText 等
- 异常隔离:某个 widget 已被销毁或方法不存在不影响其他 widget
"""
from __future__ import annotations

import logging
from typing import Callable, List, Tuple

logger = logging.getLogger(__name__)

# (callable, source_text, kwargs)
# callable 形如 lambda text: widget.setText(text), 接受单个翻译后的字符串
_RetranslateEntry = Tuple[Callable[[str], None], str, dict]


class RetranslateRegistry:
    """各 Tab 持有的可翻译 widget 注册表"""

    def __init__(self, tr_func: Callable[[str], str]):
        """
        Args:
            tr_func: 通常是 widget 的 self.tr (绑定方法),用于运行时翻译
        """
        self._tr = tr_func
        self._entries: List[_RetranslateEntry] = []

    def register_text(self, widget, source_text: str) -> None:
        """注册 setText(self.tr(source_text))"""
        if widget is None:
            return
        self._entries.append((lambda t, w=widget: w.setText(t), source_text, {}))

    def register_title(self, widget, source_text: str) -> None:
        """注册 setTitle(self.tr(source_text)) 用于 QGroupBox"""
        if widget is None:
            return
        self._entries.append((lambda t, w=widget: w.setTitle(t), source_text, {}))

    def register_tooltip(self, widget, source_text: str) -> None:
        """注册 setToolTip"""
        if widget is None:
            return
        self._entries.append((lambda t, w=widget: w.setToolTip(t), source_text, {}))

    def register_placeholder(self, widget, source_text: str) -> None:
        """注册 setPlaceholderText (QLineEdit / QTextEdit)"""
        if widget is None:
            return
        self._entries.append((lambda t, w=widget: w.setPlaceholderText(t), source_text, {}))

    def register_window_title(self, widget, source_text: str) -> None:
        """注册 setWindowTitle"""
        if widget is None:
            return
        self._entries.append((lambda t, w=widget: w.setWindowTitle(t), source_text, {}))

    def register_custom(self, setter: Callable[[str], None], source_text: str) -> None:
        """注册自定义 setter,适合需要拼接的复杂场景"""
        self._entries.append((setter, source_text, {}))

    def retranslate_all(self) -> int:
        """对所有已注册的项重新调用 setter(self.tr(source_text))

        Returns:
            成功刷新的 widget 数量
        """
        count = 0
        for setter, source_text, _ in self._entries:
            try:
                setter(self._tr(source_text))
                count += 1
            except RuntimeError:
                # widget 已被销毁(C++ 侧释放),静默跳过
                pass
            except Exception as e:
                logger.warning(f"i18n retranslate 失败: {e}")
        return count

    def __len__(self) -> int:
        return len(self._entries)
