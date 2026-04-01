"""Tab3 - 创作进度：启动/停止流水线、章节列表、日志查看"""
import os
import json
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QCheckBox, QLineEdit, QSplitter, QProgressBar, QMessageBox,
)
from PySide6.QtCore import Qt, Signal

from src.gui.widgets.log_viewer import LogViewer
from src.gui.widgets.chapter_list import ChapterListWidget
from src.gui.workers.pipeline_worker import PipelineWorker
from src.gui.utils.log_handler import SignalLogHandler
from src.gui.utils.config_io import load_config


class ProgressTab(QWidget):
    """创作进度 Tab：控制流水线运行并展示实时状态"""

    # 流水线运行状态变更信号（主窗口用于锁定其他 Tab）
    pipeline_running_changed = Signal(bool)

    def __init__(self, config_path: str, env_path: str, parent=None):
        super().__init__(parent)
        self._config_path = config_path
        self._env_path = env_path
        self._worker: PipelineWorker | None = None

        self._init_ui()
        self._connect_ui()

    def set_config_path(self, path: str):
        self._config_path = path

    def set_env_path(self, path: str):
        self._env_path = path

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # ---- 顶部控制栏 ----
        top_bar = QHBoxLayout()

        self.btn_start = QPushButton("▶  启动")
        self.btn_start.setFixedWidth(110)
        self.btn_start.setProperty("cssClass", "success")

        self.btn_stop = QPushButton("■  停止")
        self.btn_stop.setFixedWidth(110)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setProperty("cssClass", "danger")

        self.chk_force_outline = QCheckBox("强制重生成大纲")
        self.edit_extra_prompt = QLineEdit()
        self.edit_extra_prompt.setPlaceholderText("额外提示词（可选）")

        top_bar.addWidget(self.btn_start)
        top_bar.addWidget(self.btn_stop)
        top_bar.addWidget(self.chk_force_outline)
        top_bar.addWidget(self.edit_extra_prompt, stretch=1)

        self.btn_open_output = QPushButton("打开输出目录")
        self.btn_open_output.clicked.connect(self._open_output_dir)
        top_bar.addWidget(self.btn_open_output)

        self.btn_refresh = QPushButton("↻  刷新章节")
        self.btn_refresh.setFixedWidth(120)
        self.btn_refresh.setToolTip("从磁盘重新加载章节状态")
        top_bar.addWidget(self.btn_refresh)

        self.btn_regen = QPushButton("🔄  重新生成选中章节")
        self.btn_regen.setFixedWidth(180)
        self.btn_regen.setEnabled(False)
        self.btn_regen.setToolTip("在章节列表中选中要重新生成的章节，然后点击此按钮")
        top_bar.addWidget(self.btn_regen)

        root.addLayout(top_bar)

        # ---- 中部：章节列表 + 日志 ----
        splitter = QSplitter(Qt.Horizontal)

        self.chapter_list = ChapterListWidget()
        self.chapter_list.setMinimumWidth(160)
        splitter.addWidget(self.chapter_list)

        self.log_viewer = LogViewer()
        splitter.addWidget(self.log_viewer)

        # 左侧占 25%，右侧占 75%
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        root.addWidget(splitter, stretch=1)

        # ---- 底部进度条 ----
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v / %m 章  (%p%)")
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(26)
        root.addWidget(self.progress_bar)

    # ------------------------------------------------------------------
    # 信号连接
    # ------------------------------------------------------------------

    def _connect_ui(self):
        self.btn_start.clicked.connect(self._on_start)
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_refresh.clicked.connect(self.load_chapters)
        self.btn_regen.clicked.connect(self._on_regen)
        self.chapter_list.itemSelectionChanged.connect(self._on_selection_changed)

    # ------------------------------------------------------------------
    # 章节目录加载
    # ------------------------------------------------------------------

    def load_chapters(self):
        """从配置和 summary.json 加载章节目录及状态

        可由外部调用（如 Tab 切换时自动触发）或用户手动刷新。
        流水线运行中不执行加载，避免覆盖实时状态。
        """
        if self._worker is not None:
            return

        cfg = load_config(self._config_path)
        target_chapters = (cfg.get("novel_config") or {}).get("target_chapters", 0)
        if target_chapters <= 0:
            return

        # 初始化章节列表
        self.chapter_list.init_chapters(target_chapters)

        # 从 summary.json 读取已完成章节
        output_dir = cfg.get("output_config", {}).get("output_dir", "data/output")
        if not os.path.isabs(output_dir):
            output_dir = os.path.join(os.path.dirname(self._config_path), output_dir)
        summary_file = os.path.join(output_dir, "summary.json")
        completed_count = 0
        if os.path.exists(summary_file):
            try:
                with open(summary_file, "r", encoding="utf-8") as f:
                    summary_data = json.load(f)
                for key in summary_data:
                    if key.isdigit():
                        ch = int(key)
                        if 1 <= ch <= target_chapters:
                            self.chapter_list.set_chapter_status(ch, "completed")
                            completed_count += 1
            except Exception as e:
                logging.warning(f"读取 summary.json 失败: {e}")

        self.progress_bar.setMaximum(target_chapters)
        self.progress_bar.setValue(completed_count)

    def showEvent(self, event):
        """Tab 可见时自动加载章节目录"""
        super().showEvent(event)
        self.load_chapters()

    # ------------------------------------------------------------------
    # 槽函数
    # ------------------------------------------------------------------

    def _on_start(self):
        """启动流水线（全量续写模式）"""
        self._start_pipeline(target_chapters_list=None)

    def _start_pipeline(self, target_chapters_list: list[int] | None = None):
        """启动流水线的通用入口

        Args:
            target_chapters_list: 指定要生成的章节列表，None 表示全量续写模式
        """
        # 读取配置获取目标章节数
        cfg = load_config(self._config_path)
        target_chapters = (cfg.get("novel_config") or {}).get("target_chapters", 0)
        if target_chapters <= 0:
            QMessageBox.warning(
                self, "配置错误",
                "请先在「小说参数」中设置有效的目标章节数 (target_chapters)。",
            )
            return

        # 初始化章节列表和进度条
        self.chapter_list.init_chapters(target_chapters)
        self.log_viewer.clear_logs()

        # 从 summary.json 读取已完成章节并标记
        output_dir = cfg.get("output_config", {}).get("output_dir", "data/output")
        if not os.path.isabs(output_dir):
            output_dir = os.path.join(os.path.dirname(self._config_path), output_dir)
        summary_file = os.path.join(output_dir, "summary.json")
        completed_count = 0
        if os.path.exists(summary_file):
            try:
                with open(summary_file, "r", encoding="utf-8") as f:
                    summary_data = json.load(f)
                for key in summary_data:
                    if key.isdigit():
                        ch = int(key)
                        if 1 <= ch <= target_chapters:
                            # 重新生成模式下，被选中的章节标记为 pending 而非 completed
                            if target_chapters_list and ch in target_chapters_list:
                                self.chapter_list.set_chapter_status(ch, "pending")
                            else:
                                self.chapter_list.set_chapter_status(ch, "completed")
                                completed_count += 1
                if completed_count > 0 and not target_chapters_list:
                    self.log_viewer.append_log(
                        f"检测到 {completed_count} 章已完成，将从断点续写。", "INFO"
                    )
            except Exception as e:
                logging.warning(f"读取 summary.json 失败: {e}")

        if target_chapters_list:
            chapter_str = ", ".join(str(ch) for ch in target_chapters_list)
            self.log_viewer.append_log(
                f"重新生成模式：将生成第 {chapter_str} 章", "INFO"
            )
            self.progress_bar.setMaximum(len(target_chapters_list))
            self.progress_bar.setValue(0)
        else:
            self.progress_bar.setMaximum(target_chapters)
            self.progress_bar.setValue(completed_count)

        # 创建 Worker
        self._worker = PipelineWorker(
            config_path=self._config_path,
            env_path=self._env_path,
            force_outline=self.chk_force_outline.isChecked(),
            extra_prompt=self.edit_extra_prompt.text().strip(),
            target_chapters_list=target_chapters_list,
        )

        # 连接 Worker 信号
        self._worker.chapter_started.connect(self._on_chapter_started)
        self._worker.chapter_completed.connect(self._on_chapter_completed)
        self._worker.chapter_failed.connect(self._on_chapter_failed)
        self._worker.progress_updated.connect(self._on_progress_updated)
        self._worker.pipeline_finished.connect(self._on_pipeline_finished)
        self._worker.log_message.connect(self.log_viewer.append_log)

        # 切换按钮状态
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_regen.setEnabled(False)
        self.btn_refresh.setEnabled(False)
        self.pipeline_running_changed.emit(True)

        self._worker.start()

    def _on_stop(self):
        """请求停止流水线"""
        if self._worker is not None:
            self._worker.stop()
        self.btn_stop.setEnabled(False)
        self.log_viewer.append_log("已发送停止信号，等待当前章节完成后停止…", "WARNING")

    def _on_selection_changed(self):
        """章节列表选择变化时，更新重新生成按钮状态"""
        selected = self.chapter_list.get_selected_chapter_numbers()
        # 流水线运行中或无选中时禁用
        is_running = self._worker is not None
        self.btn_regen.setEnabled(len(selected) > 0 and not is_running)
        if selected:
            self.btn_regen.setText(f"🔄  重新生成 {len(selected)} 章")
        else:
            self.btn_regen.setText("🔄  重新生成选中章节")

    def _on_regen(self):
        """重新生成选中的章节"""
        selected = self.chapter_list.get_selected_chapter_numbers()
        if not selected:
            QMessageBox.information(self, "提示", "请先在章节列表中选中要重新生成的章节。")
            return

        chapter_str = ", ".join(str(ch) for ch in selected)
        reply = QMessageBox.question(
            self, "确认重新生成",
            f"确定要重新生成以下 {len(selected)} 章吗？\n第 {chapter_str} 章\n\n"
            "已有的章节内容将被覆盖。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._start_pipeline(target_chapters_list=selected)

    # ------------------------------------------------------------------
    # Worker 信号处理
    # ------------------------------------------------------------------

    def _on_chapter_started(self, chapter_num: int):
        self.chapter_list.set_chapter_status(chapter_num, "running")

    def _on_chapter_completed(self, chapter_num: int, title: str):
        self.chapter_list.set_chapter_status(chapter_num, "completed")

    def _on_chapter_failed(self, chapter_num: int, error_msg: str):
        self.chapter_list.set_chapter_status(chapter_num, "failed")
        self.log_viewer.append_log(
            f"第 {chapter_num} 章失败: {error_msg}", "ERROR"
        )

    def _on_progress_updated(self, current: int, total: int):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

    def _on_pipeline_finished(self, success: bool):
        """流水线结束（成功或失败）"""
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_regen.setEnabled(False)
        self.btn_refresh.setEnabled(True)
        self.pipeline_running_changed.emit(False)

        completed = self.chapter_list.get_completed_count()
        if success:
            self.log_viewer.append_log(
                f"流水线完成，共生成 {completed} 章。", "INFO"
            )
        else:
            self.log_viewer.append_log(
                f"流水线未完整完成，已生成 {completed} 章。", "WARNING"
            )

        # 清理 Worker 引用
        self._worker = None

    def _open_output_dir(self):
        """在 Finder 中打开输出目录"""
        import subprocess
        cfg = load_config(self._config_path)
        output_dir = (cfg.get("output_config") or {}).get("output_dir", "")
        if not output_dir:
            output_dir = os.path.join(os.path.dirname(self._config_path), "data", "output")
        # 相对路径基于配置文件目录
        if not os.path.isabs(output_dir):
            output_dir = os.path.join(os.path.dirname(self._config_path), output_dir)
        if os.path.isdir(output_dir):
            subprocess.Popen(["open", output_dir])
        else:
            QMessageBox.warning(self, "目录不存在", f"输出目录不存在:\n{output_dir}")
