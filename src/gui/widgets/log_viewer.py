"""日志查看器组件：基于 QPlainTextEdit 的彩色日志显示"""
from PySide6.QtWidgets import QPlainTextEdit
from PySide6.QtGui import QFont, QTextCharFormat, QColor, QTextCursor
from PySide6.QtCore import Qt, QTimer

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

        # 日志缓冲区 + 节流定时器，避免高频追加导致界面抖动
        self._log_buffer: list[tuple[str, str]] = []
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(50)  # 50ms 合并一次
        self._flush_timer.setSingleShot(True)
        self._flush_timer.timeout.connect(self._flush_buffer)

    # ------------------------------------------------------------------
    def append_log(self, message: str, level: str = "INFO"):
        """追加一条日志到缓冲区，由定时器批量刷新"""
        self._log_buffer.append((message, level))
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    # ------------------------------------------------------------------
    def _flush_buffer(self):
        """批量写入缓冲区中的日志，只触发一次滚动"""
        if not self._log_buffer:
            return

        # 取出并清空缓冲区
        batch = self._log_buffer
        self._log_buffer = []

        # 检查是否在底部
        v_scrollbar = self.verticalScrollBar()
        was_at_bottom = v_scrollbar.value() >= v_scrollbar.maximum() - 10

        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)

        # 暂停界面更新，批量写入
        self.setUpdatesEnabled(False)
        try:
            for message, level in batch:
                fmt = QTextCharFormat()
                fmt.setForeground(_LEVEL_COLORS.get(level.upper(), _LEVEL_COLORS["INFO"]))

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
        finally:
            self.setUpdatesEnabled(True)

        # 仅当之前在底部时才自动滚动
        if was_at_bottom:
            h_scrollbar = self.horizontalScrollBar()
            h_pos = h_scrollbar.value()

            self.setTextCursor(cursor)
            self.ensureCursorVisible()

            h_scrollbar.setValue(h_pos)

    # ------------------------------------------------------------------
    def clear_logs(self):
        """清空所有日志"""
        self._log_buffer.clear()
        self.clear()
