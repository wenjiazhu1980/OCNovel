"""可拖拽调整高度且支持内容自适应的 QTextEdit

特性：
1. 内容变化时自动调整高度以适配文本量（有上限防止撑爆布局）
2. 右下角叠加自定义垂直拖拽把手，用户可手动拖拽微调高度
3. 保留 QTextEdit 的所有原生语义，可直接用于 QFormLayout
"""
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QCursor, QPainter, QColor, QPen
from PySide6.QtWidgets import QTextEdit, QFrame, QSizePolicy


class _VResizeHandle(QFrame):
    """右下角自定义垂直拖拽把手

    说明：Qt 内置的 QSizeGrip 只会调整顶层窗口，不会调整普通子控件高度；
    这里改为自定义 handle，在鼠标事件中直接修改目标 QTextEdit 的高度。
    视觉上绘制三条水平短线作为抽屉式抓握提示，悬停时颜色加深。
    """

    _COLOR_NORMAL = QColor(150, 150, 150, 170)
    _COLOR_HOVER = QColor(80, 80, 80, 220)

    def __init__(self, target: "ResizableTextEdit"):
        super().__init__(target)
        self._target = target
        self.setFixedSize(22, 12)
        self.setCursor(QCursor(Qt.CursorShape.SizeVerCursor))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setToolTip(self.tr("拖拽调整高度"))

        self._drag_active = False
        self._hover = False
        self._press_y = 0
        self._start_height = 0

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = self._COLOR_HOVER if (self._hover or self._drag_active) else self._COLOR_NORMAL
        pen = QPen(color, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        w = self.width()
        h = self.height()
        cy = h / 2
        # 三条水平短线：中间最长，表达"上下可拖拽"
        spacing = 3.0
        lines = [
            (w * 0.28, cy - spacing, w * 0.72, cy - spacing),
            (w * 0.22, cy,           w * 0.78, cy),
            (w * 0.28, cy + spacing, w * 0.72, cy + spacing),
        ]
        for x1, y1, x2, y2 in lines:
            p.drawLine(int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2)))
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_active = True
            self._press_y = int(event.globalPosition().y())
            self._start_height = self._target.height()
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self._drag_active:
            super().mouseMoveEvent(event)
            return
        delta = int(event.globalPosition().y()) - self._press_y
        base_min = self._target._base_min_height or 60
        new_h = max(base_min, self._start_height + delta)
        # 同步更新 minimumHeight 与实际高度，让布局稳定
        self._target.setMinimumHeight(new_h)
        self._target.resize(self._target.width(), new_h)
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._drag_active and event.button() == Qt.MouseButton.LeftButton:
            self._drag_active = False
            self.update()
            # 通知父控件用户已手动调整，停止自适应
            self._target._on_manual_resized()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ResizableTextEdit(QTextEdit):
    """带内容自适应 + 右下角拖拽把手的文本框"""

    # 自适应高度的上限（像素），超过此值出现滚动条
    MAX_AUTO_HEIGHT = 300

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        # 记录初始最小高度（由 _make_text_edit 设置）
        self._base_min_height = 0

        # 用户是否手动拖拽过（拖拽后停止自适应，尊重用户选择）
        self._user_resized = False

        # 自定义拖拽把手（替代会拉伸顶层窗口的 QSizeGrip）
        self._grip = _VResizeHandle(self)
        self._grip.raise_()
        self._grip_margin = 2

        # 内容变化时自动调整高度
        self.document().contentsChanged.connect(self._auto_resize)

    # ------------------------------------------------------------------
    # 内容自适应高度
    # ------------------------------------------------------------------
    def _auto_resize(self):
        if self._user_resized:
            return
        if self._base_min_height == 0:
            self._base_min_height = self.minimumHeight() or 60
        doc_height = int(self.document().size().height())
        margins = self.contentsMargins()
        total = doc_height + margins.top() + margins.bottom() + 8
        target = max(self._base_min_height, min(total, self.MAX_AUTO_HEIGHT))
        # 通过调整 minimumHeight 让布局自然撑开，不用 setFixedHeight
        self.setMinimumHeight(target)

    # ------------------------------------------------------------------
    # 拖拽把手回调：用户手动调整后，停止自适应
    # ------------------------------------------------------------------
    def _on_manual_resized(self):
        self._user_resized = True

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_grip()

    def _reposition_grip(self):
        w = self.viewport().width()
        h = self.viewport().height()
        gs = self._grip.size()
        x = w - gs.width() - self._grip_margin
        y = h - gs.height() - self._grip_margin
        self._grip.move(x, y)

    def showEvent(self, event):
        super().showEvent(event)
        self._reposition_grip()
        # 首次显示时触发一次自适应
        if not self._user_resized:
            self._auto_resize()

    def sizeHint(self) -> QSize:
        base = super().sizeHint()
        return QSize(base.width(), max(base.height(), self.minimumHeight()))

    # ------------------------------------------------------------------
    # 公开方法：重置自适应状态（如加载新配置时调用）
    # ------------------------------------------------------------------
    def reset_auto_resize(self):
        """重置用户手动调整标记，恢复内容自适应行为"""
        self._user_resized = False
        if self._base_min_height > 0:
            self.setMinimumHeight(self._base_min_height)
        self._auto_resize()
