"""日志 Handler → Qt Signal 桥接"""
import logging
from PySide6.QtCore import QObject, Signal


class LogEmitter(QObject):
    """日志信号发射器"""
    log_message = Signal(str, str)  # (formatted_message, level_name)


class SignalLogHandler(logging.Handler):
    """将 Python logging 输出转发为 Qt Signal 的 Handler"""

    def __init__(self):
        super().__init__()
        self.emitter = LogEmitter()
        self.setFormatter(logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        ))

    def emit(self, record):
        try:
            msg = self.format(record)
            self.emitter.log_message.emit(msg, record.levelname)
        except Exception:
            self.handleError(record)
