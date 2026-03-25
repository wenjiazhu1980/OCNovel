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


class MainWindow(QMainWindow):
    """OCNovel 主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("OCNovel - AI小说生成系统")
        self.setMinimumSize(960, 680)
        self.resize(1100, 780)

        self._project_root = get_project_root()
        self._config_path = os.path.join(self._project_root, "config.json")
        self._env_path = os.path.join(self._project_root, ".env")

        self._init_menu()
        self._init_ui()
        self._update_title()

    # ------------------------------------------------------------------
    # 菜单栏
    # ------------------------------------------------------------------
    def _init_menu(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("文件")

        act_open_config = QAction("打开配置文件…", self)
        act_open_config.setShortcut("Ctrl+O")
        act_open_config.triggered.connect(self._open_config_file)
        file_menu.addAction(act_open_config)

        act_open_env = QAction("打开 .env 文件…", self)
        act_open_env.triggered.connect(self._open_env_file)
        file_menu.addAction(act_open_env)

        file_menu.addSeparator()

        act_open_dir = QAction("打开配置目录", self)
        act_open_dir.triggered.connect(self._open_config_dir)
        file_menu.addAction(act_open_dir)

    def _open_config_file(self):
        """选择自定义 config.json 路径"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择配置文件", os.path.dirname(self._config_path),
            "JSON 文件 (*.json);;所有文件 (*)"
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
        dlg = QFileDialog(self, "选择 .env 文件", os.path.dirname(self._env_path))
        dlg.setNameFilters(["Env 文件 (*.env)", "所有文件 (*)"])
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
        """在 Finder 中打开配置文件所在目录"""
        import subprocess
        config_dir = os.path.dirname(self._config_path)
        if os.path.isdir(config_dir):
            subprocess.Popen(["open", config_dir])
        else:
            QMessageBox.warning(self, "目录不存在", f"目录不存在: {config_dir}")

    def _update_title(self):
        config_name = os.path.basename(self._config_path)
        config_dir = os.path.dirname(self._config_path)
        self.setWindowTitle(f"OCNovel - {config_name}  [{config_dir}]")

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
        self.tabs.addTab(self.model_tab, "  模型配置  ")

        # Tab2: 小说参数
        self.novel_tab = NovelParamsTab(self._config_path, self._env_path)
        self.tabs.addTab(self.novel_tab, "  小说参数  ")

        # Tab3: 创作进度
        self.progress_tab = ProgressTab(self._config_path, self._env_path)
        self.tabs.addTab(self.progress_tab, "  创作进度  ")

        layout.addWidget(self.tabs)

        # 状态栏
        self._status_bar = QStatusBar()
        self._status_label = QLabel("就绪")
        self._status_bar.addWidget(self._status_label)
        self.setStatusBar(self._status_bar)

        # 流水线运行时锁定配置 Tab
        self.progress_tab.pipeline_running_changed.connect(self._on_pipeline_state)

    def _on_pipeline_state(self, running: bool):
        """流水线运行时禁用 Tab1/Tab2 的输入控件，但保留滚动"""
        self.model_tab.set_editing_enabled(not running)
        self.novel_tab.set_editing_enabled(not running)
        self._status_label.setText("生成中…" if running else "就绪")
