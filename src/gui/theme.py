"""OCNovel GUI 主题色常量 — 集中管理，便于未来暗色模式切换"""


class LightTheme:
    """浅色主题（参照作家助手视觉风格）"""

    # 背景
    BG_PRIMARY = "#F5F6F8"
    BG_CARD = "#FFFFFF"
    BG_SECONDARY = "#EBEDF0"

    # 边框
    BORDER = "#E8E8E8"
    BORDER_HOVER = "#D0D3D8"

    # 文字
    TEXT_PRIMARY = "#1D2129"
    TEXT_SECONDARY = "#4E5969"
    TEXT_PLACEHOLDER = "#A0A4AA"

    # 蓝色主色
    BLUE = "#4A90D9"
    BLUE_HOVER = "#3B7DD8"
    BLUE_PRESSED = "#2E6BC4"
    BLUE_LIGHT = "rgba(74, 144, 217, 0.12)"

    # 功能色
    GREEN = "#34C759"
    GREEN_HOVER = "#2DB84E"
    RED = "#E74C3C"
    RED_HOVER = "#D63B2F"
    WARNING = "#E37400"

    # 日志级别色（浅色背景适配）
    LOG_ERROR = "#D93025"
    LOG_WARNING = "#E37400"
    LOG_INFO = "#1D2129"
    LOG_DEBUG = "#8C8C8C"

    # 章节状态色
    STATUS_PENDING = "#A0A4AA"
    STATUS_RUNNING = "#E37400"
    STATUS_COMPLETED = "#34C759"
    STATUS_FAILED = "#D93025"


# 当前激活主题
Theme = LightTheme
