"""QApplication 工厂：高 DPI、全局异常处理、浅色主题样式、国际化"""
import sys
import traceback
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from src.gui.utils.fonts import FONT_UI
from src.gui.i18n.translator import initialize_translation


def create_app(argv=None) -> QApplication:
    """创建并配置 QApplication 实例"""
    if argv is None:
        argv = sys.argv

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(argv)
    app.setApplicationName("OCNovel")
    app.setOrganizationName("OCNovel")
    app.setApplicationVersion("1.0.1")

    # 全局默认字体（跨平台自适应）
    font = QFont(FONT_UI, 13)
    font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(font)

    # 全局异常处理
    def _exception_hook(exc_type, exc_value, exc_tb):
        msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
        QMessageBox.critical(None, "未捕获的异常", msg)
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _exception_hook
    app.setStyleSheet(_STYLESHEET)

    # 初始化国际化翻译
    initialize_translation(app)

    return app


# ---------------------------------------------------------------------------
# 全局 QSS — 浅色主题，参照作家助手视觉风格
# ---------------------------------------------------------------------------
_STYLESHEET = """

/* ══ 基础 ══ */

QMainWindow, QWidget {
    background-color: #F5F6F8;
    color: #1D2129;
    font-size: 13px;
}

/* ══ Tab 栏 ══ */

QTabWidget::pane {
    border: 1px solid #E8E8E8;
    border-radius: 8px;
    background-color: #F5F6F8;
    top: -1px;
}

QTabBar::tab {
    padding: 10px 28px;
    margin-right: 2px;
    border: none;
    border-bottom: 3px solid transparent;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    min-width: 100px;
    color: #4E5969;
    background: transparent;
    font-weight: 500;
}

QTabBar::tab:selected {
    color: #4A90D9;
    border-bottom-color: #4A90D9;
    background: #FFFFFF;
    font-weight: 600;
}

QTabBar::tab:hover:!selected {
    color: #1D2129;
    background: rgba(74, 144, 217, 0.06);
}

/* ══ 卡片式 QGroupBox ══ */

QGroupBox {
    background-color: #FFFFFF;
    border: 1px solid #E8E8E8;
    border-radius: 10px;
    margin-top: 20px;
    padding: 32px 16px 16px 16px;
    font-weight: 600;
    color: #1D2129;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 16px;
    padding: 0 8px;
    color: #1D2129;
}

QGroupBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1.5px solid #D0D3D8;
}

QGroupBox::indicator:checked {
    background: #4A90D9;
    border-color: #4A90D9;
}

/* 嵌套 QGroupBox — 透明背景，避免双卡片 */
QGroupBox[cssClass="inner"] {
    background: transparent;
    border: 1px solid #EBEDF0;
    border-radius: 8px;
    margin-top: 18px;
    padding: 28px 12px 12px 12px;
}

/* ══ 输入控件 ══ */

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #FFFFFF;
    border: 1px solid #E8E8E8;
    border-radius: 6px;
    padding: 6px 10px;
    min-height: 28px;
    color: #1D2129;
    selection-background-color: rgba(74, 144, 217, 0.25);
}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #4A90D9;
}

QLineEdit:disabled, QTextEdit:disabled, QSpinBox:disabled,
QDoubleSpinBox:disabled, QComboBox:disabled {
    background-color: #F5F6F8;
    color: #A0A4AA;
}

QComboBox::drop-down {
    border: none;
    width: 28px;
}

QComboBox QAbstractItemView {
    background: #FFFFFF;
    border: 1px solid #E8E8E8;
    border-radius: 6px;
    selection-background-color: rgba(74, 144, 217, 0.12);
    selection-color: #4A90D9;
}

/* ══ 按钮 — 默认（次要） ══ */

QPushButton {
    background-color: #FFFFFF;
    border: 1px solid #E8E8E8;
    border-radius: 6px;
    padding: 7px 18px;
    min-height: 28px;
    color: #1D2129;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #F5F6F8;
    border-color: #D0D3D8;
}

QPushButton:pressed {
    background-color: #EBEDF0;
}

QPushButton:disabled {
    background-color: #F5F6F8;
    color: #A0A4AA;
    border-color: #E8E8E8;
}

/* 主要按钮（蓝色） */
QPushButton[cssClass="primary"] {
    background-color: #4A90D9;
    border: none;
    color: #FFFFFF;
    font-weight: 600;
}

QPushButton[cssClass="primary"]:hover {
    background-color: #3B7DD8;
}

QPushButton[cssClass="primary"]:pressed {
    background-color: #2E6BC4;
}

QPushButton[cssClass="primary"]:disabled {
    background-color: #EBEDF0;
    color: #A0A4AA;
}

/* 成功按钮（绿色） */
QPushButton[cssClass="success"] {
    background-color: #34C759;
    border: none;
    color: #FFFFFF;
    font-weight: 600;
}

QPushButton[cssClass="success"]:hover {
    background-color: #2DB84E;
}

QPushButton[cssClass="success"]:disabled {
    background-color: #EBEDF0;
    color: #A0A4AA;
}

/* 危险按钮（红色） */
QPushButton[cssClass="danger"] {
    background-color: #E74C3C;
    border: none;
    color: #FFFFFF;
    font-weight: 600;
}

QPushButton[cssClass="danger"]:hover {
    background-color: #D63B2F;
}

QPushButton[cssClass="danger"]:disabled {
    background-color: #EBEDF0;
    color: #A0A4AA;
}

/* ══ 复选框 ══ */

QCheckBox {
    spacing: 8px;
    color: #1D2129;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1.5px solid #D0D3D8;
    background: #FFFFFF;
}

QCheckBox::indicator:checked {
    background: #4A90D9;
    border-color: #4A90D9;
}

QCheckBox::indicator:hover {
    border-color: #4A90D9;
}

/* ══ 列表 ══ */

QListWidget {
    background-color: #FFFFFF;
    border: 1px solid #E8E8E8;
    border-radius: 8px;
    outline: none;
}

QListWidget::item {
    padding: 6px 10px;
    border-radius: 4px;
}

QListWidget::item:selected {
    background: rgba(74, 144, 217, 0.12);
    color: #4A90D9;
}

QListWidget::item:hover:!selected {
    background: #F5F6F8;
}

/* ══ 进度条 ══ */

QProgressBar {
    background-color: #EBEDF0;
    border: none;
    border-radius: 6px;
    text-align: center;
    min-height: 22px;
    font-weight: 600;
    color: #4E5969;
}

QProgressBar::chunk {
    border-radius: 6px;
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #4A90D9, stop:1 #5BA3E6
    );
}

/* ══ 滚动区域 ══ */

QScrollArea {
    border: none;
    background: transparent;
}

QScrollBar:vertical {
    width: 6px;
    background: transparent;
    margin: 4px 0;
}

QScrollBar::handle:vertical {
    background: #D0D3D8;
    border-radius: 3px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background: #A0A4AA;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    height: 6px;
    background: transparent;
    margin: 0 4px;
}

QScrollBar::handle:horizontal {
    background: #D0D3D8;
    border-radius: 3px;
    min-width: 30px;
}

QScrollBar::handle:horizontal:hover {
    background: #A0A4AA;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

/* ══ 分割器 ══ */

QSplitter::handle {
    background: #E8E8E8;
    width: 1px;
    margin: 4px 6px;
}

/* ══ 工具提示 ══ */

QToolTip {
    background: #FFFFFF;
    border: 1px solid #E8E8E8;
    border-radius: 6px;
    padding: 6px 10px;
    color: #1D2129;
}

/* ══ 状态栏 ══ */

QStatusBar {
    background: #FFFFFF;
    border-top: 1px solid #E8E8E8;
    color: #4E5969;
    padding: 4px 12px;
    font-size: 12px;
}

/* ══ 消息框 ══ */

QMessageBox {
    background: #FFFFFF;
}
"""
