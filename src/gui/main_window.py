"""主窗口：QMainWindow + QTabWidget（3 个 Tab）+ 菜单栏 + 状态栏"""
import os
from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QWidget, QVBoxLayout, QStatusBar, QLabel,
    QMenuBar, QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt, QDir
from PySide6.QtGui import QFont, QAction

from .tabs.model_config_tab import ModelConfigTab
from .tabs.novel_params_tab import NovelParamsTab
from .tabs.progress_tab import ProgressTab
from .utils.resource_path import get_project_root
from .i18n.translator import save_language, get_current_language, SUPPORTED_LANGUAGES


class MainWindow(QMainWindow):
    """OCNovel 主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(self.tr("OCNovel - AI小说生成系统"))
        self.setMinimumSize(960, 680)
        self.resize(1100, 780)

        self._project_root = get_project_root()
        self._config_path = os.path.join(self._project_root, "config.json")
        self._env_path = os.path.join(self._project_root, ".env")
        self._language_actions = {}  # 语言菜单动作字典

        self._init_menu()
        self._init_ui()
        self._update_title()

    # ------------------------------------------------------------------
    # 菜单栏
    # ------------------------------------------------------------------
    def _init_menu(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu(self.tr("文件"))

        act_open_config = QAction(self.tr("打开配置文件…"), self)
        act_open_config.setShortcut("Ctrl+O")
        act_open_config.triggered.connect(self._open_config_file)
        file_menu.addAction(act_open_config)

        act_open_env = QAction(self.tr("打开 .env 文件…"), self)
        act_open_env.triggered.connect(self._open_env_file)
        file_menu.addAction(act_open_env)

        file_menu.addSeparator()

        act_open_dir = QAction(self.tr("打开配置目录"), self)
        act_open_dir.triggered.connect(self._open_config_dir)
        file_menu.addAction(act_open_dir)

        # 语言菜单
        language_menu = menu_bar.addMenu(self.tr("语言"))
        self._language_actions = {}
        current_language = get_current_language()

        for lang_code, lang_name in SUPPORTED_LANGUAGES.items():
            action = QAction(lang_name, self)
            action.setCheckable(True)
            action.setChecked(lang_code == current_language)
            action.triggered.connect(lambda checked, code=lang_code: self._change_language(code))
            language_menu.addAction(action)
            self._language_actions[lang_code] = action

    def _open_config_file(self):
        """选择自定义 config.json 路径"""
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("选择配置文件"), os.path.dirname(self._config_path),
            self.tr("JSON 文件 (*.json);;所有文件 (*)")
        )
        if path:
            self._config_path = path
            self._update_title()
            self.model_tab.set_config_path(path)
            self.novel_tab.set_config_path(path)
            self.progress_tab.set_config_path(path)
            # 自动加载
            self.model_tab.reload()
            self.novel_tab.reload()

    def _open_env_file(self):
        """选择自定义 .env 路径（macOS 默认隐藏点文件，需特殊处理）"""
        dlg = QFileDialog(self, self.tr("选择 .env 文件"), os.path.dirname(self._env_path))
        dlg.setNameFilters([self.tr("Env 文件 (*.env)"), self.tr("所有文件 (*)")])
        dlg.setFileMode(QFileDialog.FileMode.ExistingFile)
        # 显示隐藏文件（.env 以点开头）
        dlg.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dlg.setFilter(QDir.AllEntries | QDir.Hidden | QDir.NoDotAndDotDot)
        if not dlg.exec():
            return
        paths = dlg.selectedFiles()
        if not paths:
            return
        path = paths[0]
        self._env_path = path
        self._update_title()
        self.model_tab.set_env_path(path)
        self.progress_tab.set_env_path(path)
        self.model_tab.reload()

    def _open_config_dir(self):
        """在系统文件管理器中打开配置文件所在目录"""
        from src.gui.utils.platform_utils import open_directory
        config_dir = os.path.dirname(self._config_path)
        if not open_directory(config_dir):
            QMessageBox.warning(self, self.tr("目录不存在"), self.tr("目录不存在: {0}").format(config_dir))

    def _change_language(self, language: str):
        """切换界面语言"""
        current_language = get_current_language()
        if language == current_language:
            return

        # 保存语言偏好
        save_language(language)

        # 更新菜单勾选状态
        for lang_code, action in self._language_actions.items():
            action.setChecked(lang_code == language)

        # 提示需要重启
        QMessageBox.information(
            self,
            self.tr("语言已更改"),
            self.tr("语言设置已保存。\n请重启应用以应用新的语言设置。")
        )

    def _update_title(self):
        config_name = os.path.basename(self._config_path)
        config_dir = os.path.dirname(self._config_path)
        self.setWindowTitle(self.tr("OCNovel - {0}  [{1}]").format(config_name, config_dir))

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 12, 16, 0)
        layout.setSpacing(0)

        self.tabs = QTabWidget()
        tab_font = QFont()
        tab_font.setPointSize(13)
        self.tabs.tabBar().setFont(tab_font)

        # Tab1: 模型配置
        self.model_tab = ModelConfigTab(self._env_path, self._config_path)
        self.tabs.addTab(self.model_tab, self.tr("  模型配置  "))

        # Tab2: 小说参数
        self.novel_tab = NovelParamsTab(self._config_path, self._env_path)
        self.tabs.addTab(self.novel_tab, self.tr("  小说参数  "))

        # Tab3: 创作进度
        self.progress_tab = ProgressTab(self._config_path, self._env_path)
        self.tabs.addTab(self.progress_tab, self.tr("  创作进度  "))

        layout.addWidget(self.tabs)

        # 状态栏
        self._status_bar = QStatusBar()
        self._status_label = QLabel(self.tr("就绪"))
        self._status_bar.addWidget(self._status_label)
        self.setStatusBar(self._status_bar)

        # 流水线运行时锁定配置 Tab
        self.progress_tab.pipeline_running_changed.connect(self._on_pipeline_state)

    def _on_pipeline_state(self, running: bool):
        """流水线运行时禁用 Tab1/Tab2 的输入控件，但保留滚动"""
        self.model_tab.set_editing_enabled(not running)
        self.novel_tab.set_editing_enabled(not running)
        self._status_label.setText(self.tr("生成中…") if running else self.tr("就绪"))
