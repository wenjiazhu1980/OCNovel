"""日志查看器组件：基于 QPlainTextEdit 的彩色日志显示"""
from PySide6.QtWidgets import QPlainTextEdit
from PySide6.QtGui import QFont, QTextCharFormat, QColor, QTextCursor
from PySide6.QtCore import Qt

from ..theme import Theme

# 日志级别对应颜色（浅色主题适配）
_LEVEL_COLORS = {
    "ERROR": QColor(Theme.LOG_ERROR),
    "CRITICAL": QColor(Theme.LOG_ERROR),
    "WARNING": QColor(Theme.LOG_WARNING),
    "INFO": QColor(Theme.LOG_INFO),
    "DEBUG": QColor(Theme.LOG_DEBUG),
}

_MAX_LINES = 5000


class LogViewer(QPlainTextEdit):
    """只读、等宽字体、按级别着色的日志查看器"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        from src.gui.utils.fonts import FONT_MONO
        self.setFont(QFont(FONT_MONO, 11))
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setStyleSheet(
            "QPlainTextEdit {"
            f"  background-color: {Theme.BG_CARD};"
            f"  color: {Theme.TEXT_PRIMARY};"
            f"  border: 1px solid {Theme.BORDER};"
            "  border-radius: 8px;"
            "  padding: 8px;"
            "  selection-background-color: rgba(74, 144, 217, 0.2);"
            "}"
        )

    # ------------------------------------------------------------------
    def append_log(self, message: str, level: str = "INFO"):
        """追加一条日志，根据级别着色；超过上限时移除最早的行"""
        fmt = QTextCharFormat()
        fmt.setForeground(_LEVEL_COLORS.get(level.upper(), _LEVEL_COLORS["INFO"]))

        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)

        # 非首行先插入换行
        if self.document().characterCount() > 1:
            cursor.insertText("\n")

        cursor.setCharFormat(fmt)
        cursor.insertText(message)

        # 超出行数上限时裁剪头部
        if self.document().blockCount() > _MAX_LINES:
            trim_cursor = QTextCursor(self.document().begin())
            trim_cursor.movePosition(
                QTextCursor.Down,
                QTextCursor.KeepAnchor,
                self.document().blockCount() - _MAX_LINES,
            )
            trim_cursor.removeSelectedText()

        # 自动滚动到底部
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    # ------------------------------------------------------------------
    def clear_logs(self):
        """清空所有日志"""
        self.clear()
