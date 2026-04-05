"""翻译管理器：系统语言检测、翻译文件加载、语言偏好管理"""
import os
import locale
import logging
from PySide6.QtCore import QLocale, QSettings, QTranslator
from PySide6.QtWidgets import QApplication


# 支持的语言列表
SUPPORTED_LANGUAGES = {
    "zh_CN": "中文（简体）",
    "en_US": "English",
}


def get_system_language() -> str:
    """检测系统语言，返回 'zh_CN' 或 'en_US'

    优先使用 Qt 的 QLocale，备用 Python 的 locale 模块。
    """
    # 方法1：使用 QLocale（Qt 推荐）
    system_locale = QLocale.system().name()  # 例如 "zh_CN", "en_US", "ja_JP"

    # 方法2：使用 Python locale（备用）
    if not system_locale or system_locale == "C":
        try:
            system_locale, _ = locale.getdefaultlocale()
            if not system_locale:
                system_locale = "en_US"
        except Exception:
            system_locale = "en_US"

    # 判断是否为中文
    if system_locale.startswith("zh"):
        return "zh_CN"
    else:
        return "en_US"


def get_saved_language() -> str | None:
    """从 QSettings 读取保存的语言偏好

    Returns:
        保存的语言代码（如 'zh_CN'），如果未设置则返回 None
    """
    settings = QSettings("OCNovel", "OCNovel")
    language = settings.value("language", None)

    # 验证语言代码是否有效
    if language and language in SUPPORTED_LANGUAGES:
        return language
    return None


def save_language(language: str):
    """保存语言偏好到 QSettings

    Args:
        language: 语言代码（如 'zh_CN', 'en_US'）
    """
    if language not in SUPPORTED_LANGUAGES:
        logging.warning(f"不支持的语言代码: {language}")
        return

    settings = QSettings("OCNovel", "OCNovel")
    settings.setValue("language", language)
    settings.sync()
    logging.info(f"语言偏好已保存: {language}")


def get_translation_file_path(language: str) -> str:
    """获取翻译文件的绝对路径

    Args:
        language: 语言代码（如 'zh_CN', 'en_US'）

    Returns:
        翻译文件（.qm）的绝对路径
    """
    # 获取当前模块所在目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    qm_file = os.path.join(current_dir, f"{language}.qm")

    # 如果在 PyInstaller 打包环境中，使用 resource_path
    if not os.path.exists(qm_file):
        try:
            from src.gui.utils.resource_path import resource_path
            qm_file = resource_path(f"src/gui/i18n/{language}.qm")
        except Exception as e:
            logging.warning(f"无法获取翻译文件路径: {e}")

    return qm_file


def load_translation(app: QApplication, language: str) -> bool:
    """加载指定语言的翻译文件

    Args:
        app: QApplication 实例
        language: 语言代码（如 'zh_CN', 'en_US'）

    Returns:
        是否成功加载翻译文件
    """
    if language not in SUPPORTED_LANGUAGES:
        logging.warning(f"不支持的语言: {language}")
        return False

    # 中文是源语言，不需要加载翻译文件
    if language == "zh_CN":
        logging.info("使用中文界面（源语言）")
        return True

    # 获取翻译文件路径
    qm_file = get_translation_file_path(language)

    if not os.path.exists(qm_file):
        logging.warning(f"翻译文件不存在: {qm_file}")
        return False

    # 创建并安装翻译器
    translator = QTranslator(app)
    if translator.load(qm_file):
        app.installTranslator(translator)
        # 将 translator 保存为 app 的属性，防止被垃圾回收
        if not hasattr(app, '_translators'):
            app._translators = []
        app._translators.append(translator)
        logging.info(f"已加载翻译文件: {qm_file}")
        return True
    else:
        logging.error(f"加载翻译文件失败: {qm_file}")
        return False


def initialize_translation(app: QApplication) -> str:
    """初始化翻译系统，自动检测或加载保存的语言

    Args:
        app: QApplication 实例

    Returns:
        当前使用的语言代码
    """
    # 优先使用保存的语言偏好
    language = get_saved_language()

    # 如果没有保存的偏好，使用系统语言
    if not language:
        language = get_system_language()
        logging.info(f"检测到系统语言: {language}")
    else:
        logging.info(f"使用保存的语言偏好: {language}")

    # 加载翻译文件
    load_translation(app, language)

    return language


def get_current_language() -> str:
    """获取当前使用的语言

    Returns:
        当前语言代码，如果未设置则返回系统语言
    """
    language = get_saved_language()
    if not language:
        language = get_system_language()
    return language
