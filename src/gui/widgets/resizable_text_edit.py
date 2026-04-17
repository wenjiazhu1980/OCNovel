"""可拖拽调整高度的 QTextEdit

在 QTextEdit 的右下角叠加一个 QSizeGrip，用户按住拖拽即可
垂直改变控件高度。保留 QTextEdit 的所有原生语义，可直接
用于 QFormLayout 等常规布局。
"""
from PySide6.QtCore import Qt, QEvent, QSize
from PySide6.QtWidgets import QTextEdit, QSizeGrip, QSizePolicy


class ResizableTextEdit(QTextEdit):
    """带右下角 QSizeGrip 的可拖拽调整高度文本框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptRichText(False)
        # 允许被用户改变高度；宽度仍交由父布局决定
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self._grip = QSizeGrip(self)
        self._grip.setFixedSize(12, 12)
        self._grip.setToolTip(self.tr("拖拽调整高度"))
        self._grip.raise_()
        # 给底部滚动条/边框让出空间
        self._grip_margin = 2

    # ------------------------------------------------------------------
    # 事件重载：始终把 size grip 贴在右下角
    # ------------------------------------------------------------------
    def resizeEvent(self, event):  # noqa: N802 - Qt 命名约定
        super().resizeEvent(event)
        self._reposition_grip()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._reposition_grip()

    def _reposition_grip(self):
        w = self.viewport().width()
        h = self.viewport().height()
        gs = self._grip.size()
        # 放在右下角，留一点边距避免压住滚动条
        x = w - gs.width() - self._grip_margin
        y = h - gs.height() - self._grip_margin
        self._grip.move(x, y)

    def sizeHint(self) -> QSize:  # noqa: N802
        base = super().sizeHint()
        return QSize(base.width(), max(base.height(), self.minimumHeight()))
