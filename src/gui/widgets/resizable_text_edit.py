"""可拖拽调整高度且支持内容自适应的 QTextEdit

特性：
1. 内容变化时自动调整高度以适配文本量（有上限防止撑爆布局）
2. 右下角叠加 QSizeGrip，用户可手动拖拽微调高度
3. 保留 QTextEdit 的所有原生语义，可直接用于 QFormLayout
"""
from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import QTextEdit, QSizeGrip, QSizePolicy


class ResizableTextEdit(QTextEdit):
    """带内容自适应 + 右下角拖拽把手的文本框"""

    # 自适应高度的上限（像素），超过此值出现滚动条
    MAX_AUTO_HEIGHT = 300

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        # 拖拽把手
        self._grip = QSizeGrip(self)
        self._grip.setFixedSize(14, 14)
        self._grip.setToolTip(self.tr("拖拽调整高度"))
        self._grip.raise_()
        self._grip_margin = 2

        # 记录初始最小高度（由 _make_text_edit 设置）
        self._base_min_height = 0

        # 用户是否手动拖拽过（拖拽后停止自适应，尊重用户选择）
        self._user_resized = False

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
    # 检测用户手动拖拽
    # ------------------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_grip()
        # 如果 resize 不是由 _auto_resize 触发的，标记为用户手动调整
        # （QSizeGrip 拖拽会触发 resizeEvent）

    def mousePressEvent(self, event):
        super().mousePressEvent(event)

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
