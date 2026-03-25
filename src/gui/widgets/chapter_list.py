"""章节列表组件：显示各章节生成状态"""
from PySide6.QtWidgets import QListWidget, QListWidgetItem
from PySide6.QtGui import QColor, QFont
from PySide6.QtCore import Qt, QSize

from ..theme import Theme

# 状态 → (图标字符, 前景色)
_STATUS_MAP = {
    "pending":   ("○", QColor(Theme.STATUS_PENDING)),
    "running":   ("◎", QColor(Theme.STATUS_RUNNING)),
    "completed": ("✓", QColor(Theme.STATUS_COMPLETED)),
    "failed":    ("✗", QColor(Theme.STATUS_FAILED)),
}


class ChapterListWidget(QListWidget):
    """带状态图标的章节列表"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(QFont("PingFang SC", 13))
        self.setAlternatingRowColors(True)
        self.setSpacing(2)
        self._total = 0

    # ------------------------------------------------------------------
    def init_chapters(self, total: int):
        """初始化 N 个待处理章节条目"""
        self.clear()
        self._total = total
        for i in range(1, total + 1):
            self._add_chapter_item(i, "pending")

    # ------------------------------------------------------------------
    def set_chapter_status(self, chapter_num: int, status: str):
        """更新指定章节的状态图标和颜色"""
        idx = chapter_num - 1
        if idx < 0 or idx >= self.count():
            return
        icon, color = _STATUS_MAP.get(status, _STATUS_MAP["pending"])
        item = self.item(idx)
        item.setText(f"  {icon}  第 {chapter_num} 章")
        item.setForeground(color)
        # 正在运行的章节自动滚动可见
        if status == "running":
            self.scrollToItem(item)

    # ------------------------------------------------------------------
    def get_completed_count(self) -> int:
        """返回已完成章节数"""
        count = 0
        icon_completed = _STATUS_MAP["completed"][0]
        for i in range(self.count()):
            if icon_completed in (self.item(i).text() or ""):
                count += 1
        return count

    # ------------------------------------------------------------------
    def _add_chapter_item(self, chapter_num: int, status: str):
        icon, color = _STATUS_MAP.get(status, _STATUS_MAP["pending"])
        item = QListWidgetItem(f"  {icon}  第 {chapter_num} 章")
        item.setForeground(color)
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        item.setSizeHint(QSize(0, 36))
        self.addItem(item)
