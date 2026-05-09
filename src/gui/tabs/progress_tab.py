"""Tab3 - 创作进度：启动/停止流水线、章节列表、日志查看"""
import os
import json
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QCheckBox, QLineEdit, QSplitter, QProgressBar, QMessageBox,
    QLabel, QSpinBox,
)
from PySide6.QtCore import Qt, Signal, QEvent

from src.gui.widgets.log_viewer import LogViewer
from src.gui.widgets.chapter_list import ChapterListWidget
from src.gui.workers.pipeline_worker import PipelineWorker
from src.gui.workers.marketing_worker import MarketingWorker
from src.gui.workers.merge_worker import MergeWorker
from src.gui.workers.outline_worker import OutlineWorker
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
        self._marketing_worker: MarketingWorker | None = None
        self._merge_worker: MergeWorker | None = None
        self._outline_worker: OutlineWorker | None = None
        # [5.4] i18n 注册表
        from ..utils.i18n_helper import RetranslateRegistry
        self._i18n_registry = RetranslateRegistry(self.tr)

        self._init_ui()
        self._connect_ui()
        self._auto_register_translatable_widgets()

    def _auto_register_translatable_widgets(self) -> None:
        """[5.4] 扫描 QGroupBox 与 QPushButton,自动登记到 i18n 注册表

        排除带图标前缀的运行时按钮(▶/⏹/🔄),它们由 _retranslate_buttons 专管。
        """
        try:
            from PySide6.QtWidgets import QGroupBox, QPushButton
            for gb in self.findChildren(QGroupBox):
                title = gb.title()
                if title:
                    self._i18n_registry.register_title(gb, title)
            for btn in self.findChildren(QPushButton):
                text = btn.text()
                if text and not text.startswith(("▶", "⏹", "🔄")):
                    self._i18n_registry.register_text(btn, text)
        except Exception:
            pass

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
        # 第一行:启动/停止/强制重生成大纲/额外提示词
        top_bar_1 = QHBoxLayout()

        self.btn_start = QPushButton(self.tr("▶  启动"))
        self.btn_start.setMinimumWidth(110)  # 改为最小宽度,允许自动扩展
        self.btn_start.setProperty("cssClass", "success")
        self.btn_start.setToolTip(self.tr(
            "启动完整流水线（大纲 → 内容 → 定稿）\n"
            "按全书 target_chapters 全量续写，仅受「强制重生成大纲」与「额外提示词」影响\n"
            "「大纲范围」控件仅对「仅生成大纲」按钮生效，启动流水线时被忽略"
        ))

        self.btn_stop = QPushButton(self.tr("■  停止"))
        self.btn_stop.setMinimumWidth(110)  # 改为最小宽度,允许自动扩展
        self.btn_stop.setEnabled(False)
        self.btn_stop.setProperty("cssClass", "danger")

        self.btn_outline_only = QPushButton(self.tr("📝  仅生成大纲"))
        self.btn_outline_only.setMinimumWidth(140)
        self.btn_outline_only.setToolTip(self.tr(
            "仅生成大纲而不生成章节内容，可先预览大纲效果\n"
            "受「大纲范围」「强制重生成大纲」「额外提示词」三项约束"
        ))
        self.btn_outline_only.setProperty("cssClass", "info")

        # 大纲章节范围输入（0 = 自动推断；仅作用于「仅生成大纲」）
        self.spin_outline_start = QSpinBox()
        self.spin_outline_start.setRange(0, 9999)
        self.spin_outline_start.setValue(0)
        self.spin_outline_start.setSpecialValueText(self.tr("自动"))
        self.spin_outline_start.setToolTip(self.tr(
            "大纲起始章节（0 = 自动推断）\n"
            "仅作用于「仅生成大纲」按钮；启动流水线时被忽略"
        ))
        self.spin_outline_start.setFixedWidth(72)

        self.spin_outline_end = QSpinBox()
        self.spin_outline_end.setRange(0, 9999)
        self.spin_outline_end.setValue(0)
        self.spin_outline_end.setSpecialValueText(self.tr("自动"))
        self.spin_outline_end.setToolTip(self.tr(
            "大纲结束章节（0 = 自动推断）\n"
            "仅作用于「仅生成大纲」按钮；启动流水线时被忽略"
        ))
        self.spin_outline_end.setFixedWidth(72)

        lbl_outline_range = QLabel(self.tr("大纲范围（仅大纲）:"))
        lbl_outline_tilde = QLabel("~")

        self.chk_force_outline = QCheckBox(self.tr("强制重生成大纲"))
        self.edit_extra_prompt = QLineEdit()
        self.edit_extra_prompt.setPlaceholderText(self.tr("额外提示词（可选）"))

        top_bar_1.addWidget(self.btn_start)
        top_bar_1.addWidget(self.btn_stop)
        top_bar_1.addWidget(self.btn_outline_only)
        top_bar_1.addWidget(lbl_outline_range)
        top_bar_1.addWidget(self.spin_outline_start)
        top_bar_1.addWidget(lbl_outline_tilde)
        top_bar_1.addWidget(self.spin_outline_end)
        top_bar_1.addWidget(self.chk_force_outline)
        top_bar_1.addWidget(self.edit_extra_prompt, stretch=1)

        root.addLayout(top_bar_1)

        # 第二行:打开输出目录/刷新章节/重新生成选中章节/合并所有章节/生成营销内容
        top_bar_2 = QHBoxLayout()

        self.btn_open_output = QPushButton(self.tr("打开输出目录"))
        self.btn_open_output.clicked.connect(self._open_output_dir)
        top_bar_2.addWidget(self.btn_open_output)

        self.btn_refresh = QPushButton(self.tr("↻  刷新章节"))
        self.btn_refresh.setMinimumWidth(120)  # 改为最小宽度,允许自动扩展
        self.btn_refresh.setToolTip(self.tr("从磁盘重新加载章节状态"))
        top_bar_2.addWidget(self.btn_refresh)

        self.btn_regen = QPushButton(self.tr("🔄  重新生成选中章节"))
        self.btn_regen.setMinimumWidth(180)  # 改为最小宽度,允许自动扩展
        self.btn_regen.setEnabled(False)
        self.btn_regen.setToolTip(self.tr("在章节列表中选中要重新生成的章节，然后点击此按钮"))
        top_bar_2.addWidget(self.btn_regen)

        self.btn_merge = QPushButton(self.tr("📚  合并所有章节"))
        self.btn_merge.setMinimumWidth(150)  # 改为最小宽度,允许自动扩展
        self.btn_merge.setToolTip(self.tr("将所有已完成的章节合并为一个完整文件"))
        self.btn_merge.setProperty("cssClass", "success")
        top_bar_2.addWidget(self.btn_merge)

        self.btn_marketing = QPushButton(self.tr("📢  生成营销内容"))
        self.btn_marketing.setMinimumWidth(150)  # 改为最小宽度,允许自动扩展
        self.btn_marketing.setToolTip(self.tr("根据已完成的章节生成营销文案、标题和封面提示词"))
        self.btn_marketing.setProperty("cssClass", "info")
        top_bar_2.addWidget(self.btn_marketing)

        top_bar_2.addStretch()  # 添加弹性空间,让按钮靠左对齐

        root.addLayout(top_bar_2)

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
        self.progress_bar.setFormat(self.tr("%v / %m 章  (%p%)"))
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(26)
        root.addWidget(self.progress_bar)

    # ------------------------------------------------------------------
    # 信号连接
    # ------------------------------------------------------------------

    def _connect_ui(self):
        self.btn_start.clicked.connect(self._on_start)
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_outline_only.clicked.connect(self._on_generate_outline)
        self.btn_refresh.clicked.connect(self.load_chapters)
        self.btn_regen.clicked.connect(self._on_regen)
        self.btn_merge.clicked.connect(self._on_merge)
        self.btn_marketing.clicked.connect(self._on_generate_marketing)
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
        if os.path.exists(summary_file):
            try:
                with open(summary_file, "r", encoding="utf-8") as f:
                    summary_data = json.load(f)
                for key in summary_data:
                    if key.isdigit():
                        ch = int(key)
                        if 1 <= ch <= target_chapters:
                            self.chapter_list.set_chapter_status(ch, "completed")
            except Exception as e:
                logging.warning(f"读取 summary.json 失败: {e}")

        # 从章节列表获取实际完成数量
        completed_count = self.chapter_list.get_completed_count()
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
        """启动流水线（全量续写模式）

        仅受「强制重生成大纲」与「额外提示词」影响；「大纲范围」控件被忽略。
        """
        # 若用户在大纲范围控件填了非 0 值，明确告知其在启动流水线时不生效
        custom_start = self.spin_outline_start.value()
        custom_end = self.spin_outline_end.value()
        if custom_start > 0 or custom_end > 0:
            self.log_viewer.append_log(
                self.tr(
                    "提示：「大纲范围」({0}~{1}) 仅作用于「仅生成大纲」按钮，"
                    "启动流水线时已忽略；将按全书 target_chapters 全量续写。"
                ).format(
                    custom_start if custom_start > 0 else self.tr("自动"),
                    custom_end if custom_end > 0 else self.tr("自动"),
                ),
                "INFO",
            )
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
                self, self.tr("配置错误"),
                self.tr("请先在「小说参数」中设置有效的目标章节数 (target_chapters)。"),
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
                        self.tr("检测到 {0} 章已完成，将从断点续写。").format(completed_count), "INFO"
                    )
            except Exception as e:
                logging.warning(f"读取 summary.json 失败: {e}")

        if target_chapters_list:
            chapter_str = ", ".join(str(ch) for ch in target_chapters_list)
            self.log_viewer.append_log(
                self.tr("重新生成模式：将生成第 {0} 章").format(chapter_str), "INFO"
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
        self._worker.chapter_warning.connect(self._on_chapter_warning)
        self._worker.chapter_failed.connect(self._on_chapter_failed)
        self._worker.progress_updated.connect(self._on_progress_updated)
        self._worker.pipeline_finished.connect(self._on_pipeline_finished)
        self._worker.log_message.connect(self.log_viewer.append_log)
        self._attach_thread_lifecycle("_worker")

        # 切换按钮状态
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_outline_only.setEnabled(False)
        self.btn_regen.setEnabled(False)
        self.btn_refresh.setEnabled(False)
        self.btn_merge.setEnabled(False)
        self.btn_marketing.setEnabled(False)
        self.pipeline_running_changed.emit(True)

        self._worker.start()

    def _on_stop(self):
        """请求停止所有长任务（流水线 / 大纲 / 合并 / 营销）"""
        stopped_any = False
        for w in (self._worker, self._outline_worker, self._merge_worker, self._marketing_worker):
            if w is None:
                continue
            stop_fn = getattr(w, "stop", None)
            if callable(stop_fn):
                try:
                    stop_fn()
                    stopped_any = True
                except Exception as e:
                    logging.warning(f"停止 worker 失败: {e}")
        if stopped_any:
            self.btn_stop.setEnabled(False)
            self.log_viewer.append_log(self.tr("已发送停止信号，等待当前操作完成后停止…"), "WARNING")

    def has_running_task(self) -> bool:
        """是否有任一长任务正在运行"""
        return any(w is not None for w in (
            self._worker, self._outline_worker,
            self._merge_worker, self._marketing_worker,
        ))

    def shutdown_workers(self, wait_ms: int = 8000):
        """请求停止并等待所有后台 worker 完成（主窗口关闭时调用）"""
        for w in (self._worker, self._outline_worker, self._merge_worker, self._marketing_worker):
            if w is None:
                continue
            try:
                stop_fn = getattr(w, "stop", None)
                if callable(stop_fn):
                    stop_fn()
                if w.isRunning():
                    w.wait(wait_ms)
            except RuntimeError:
                # QThread 已被销毁
                pass

    def _attach_thread_lifecycle(self, attr_name: str) -> None:
        """绑定 QThread 内置 finished 信号到引用清理。

        关键：自定义 *_finished 信号是在 run() 内部 emit 的，槽里若直接置
        self._worker = None，可能在 run() 还未真正返回时丢掉最后一个 Python
        强引用，触发 'QThread: Destroyed while thread is still running' →
        zsh: abort。改用 QThread.finished（Qt 在 run() 完整返回后才发射）来
        清空属性，避免提前析构 C++ 线程对象。
        """
        worker = getattr(self, attr_name, None)
        if worker is None:
            return

        def _on_thread_finished():
            # 仅当属性仍指向同一个 worker 时才清空（防止用户已启动新任务后
            # 旧线程的 finished 把新 worker 一并清掉）。
            if getattr(self, attr_name, None) is worker:
                setattr(self, attr_name, None)

        worker.finished.connect(_on_thread_finished)

    def _on_selection_changed(self):
        """章节列表选择变化时，更新重新生成按钮状态"""
        selected = self.chapter_list.get_selected_chapter_numbers()
        # 流水线运行中或无选中时禁用
        is_running = self._worker is not None
        self.btn_regen.setEnabled(len(selected) > 0 and not is_running)
        if selected:
            self.btn_regen.setText(self.tr("🔄  重新生成 {0} 章").format(len(selected)))
        else:
            self.btn_regen.setText(self.tr("🔄  重新生成选中章节"))

    def _on_regen(self):
        """重新生成选中的章节"""
        selected = self.chapter_list.get_selected_chapter_numbers()
        if not selected:
            QMessageBox.information(self, self.tr("提示"), self.tr("请先在章节列表中选中要重新生成的章节。"))
            return

        chapter_str = ", ".join(str(ch) for ch in selected)
        reply = QMessageBox.question(
            self, self.tr("确认重新生成"),
            self.tr("确定要重新生成以下 {0} 章吗？\n第 {1} 章\n\n已有的章节内容将被覆盖。").format(len(selected), chapter_str),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._start_pipeline(target_chapters_list=selected)

    def _on_generate_outline(self):
        """仅生成大纲"""
        if self.has_running_task():
            QMessageBox.warning(
                self, self.tr("提示"),
                self.tr("有任务正在运行中，请等待完成后再生成大纲。"),
            )
            return

        cfg = load_config(self._config_path)
        target_chapters = (cfg.get("novel_config") or {}).get("target_chapters", 0)
        if target_chapters <= 0:
            QMessageBox.warning(
                self, self.tr("配置错误"),
                self.tr("请先在「小说参数」中设置有效的目标章节数 (target_chapters)。"),
            )
            return

        self.log_viewer.clear_logs()

        self._outline_worker = OutlineWorker(
            config_path=self._config_path,
            env_path=self._env_path,
            force_outline=self.chk_force_outline.isChecked(),
            extra_prompt=self.edit_extra_prompt.text().strip(),
            start_chapter=self.spin_outline_start.value(),
            end_chapter=self.spin_outline_end.value(),
        )

        self._outline_worker.outline_finished.connect(self._on_outline_finished)
        self._outline_worker.log_message.connect(self.log_viewer.append_log)
        self._attach_thread_lifecycle("_outline_worker")

        self.btn_outline_only.setEnabled(False)
        self.btn_outline_only.setText(self.tr("⏳  大纲生成中..."))
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.pipeline_running_changed.emit(True)

        self.log_viewer.append_log(self.tr("开始生成大纲..."), "INFO")
        self._outline_worker.start()

    def _on_outline_finished(self, success: bool, message: str):
        """大纲生成完成"""
        self.btn_outline_only.setEnabled(True)
        self.btn_outline_only.setText(self.tr("📝  仅生成大纲"))
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.pipeline_running_changed.emit(False)

        if success:
            QMessageBox.information(self, self.tr("大纲生成完成"), message)
        else:
            QMessageBox.critical(
                self, self.tr("大纲生成失败"),
                self.tr("大纲生成失败：\n{0}").format(message),
            )

        # 引用清理由 QThread.finished 触发，见 _attach_thread_lifecycle。

    def _on_generate_marketing(self):
        """生成营销内容"""
        # 统一互斥：任一长任务运行中都不允许启动新任务
        if self.has_running_task():
            QMessageBox.warning(
                self, self.tr("提示"),
                self.tr("有任务正在运行中，请等待完成后再生成营销内容。")
            )
            return

        # 检查是否有已完成的章节
        cfg = load_config(self._config_path)
        output_dir = cfg.get("output_config", {}).get("output_dir", "data/output")
        if not os.path.isabs(output_dir):
            output_dir = os.path.join(os.path.dirname(self._config_path), output_dir)
        summary_file = os.path.join(output_dir, "summary.json")

        if not os.path.exists(summary_file):
            QMessageBox.warning(
                self, self.tr("提示"),
                self.tr("未找到章节摘要文件，请先生成至少一章内容。")
            )
            return

        # 确认生成
        reply = QMessageBox.question(
            self, self.tr("确认生成营销内容"),
            self.tr("将根据已完成的章节生成营销文案、标题和封面提示词。\n\n这可能需要几分钟时间，确定要继续吗？"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        # 创建 Worker
        marketing_output_dir = os.path.join(
            os.path.dirname(self._config_path), "data", "marketing"
        )
        self._marketing_worker = MarketingWorker(
            config_path=self._config_path,
            env_path=self._env_path,
            output_dir=marketing_output_dir,
        )

        # 连接信号
        self._marketing_worker.generation_finished.connect(self._on_marketing_finished)
        self._marketing_worker.log_message.connect(self.log_viewer.append_log)
        self._attach_thread_lifecycle("_marketing_worker")

        # 禁用按钮 + 广播全局 busy 状态（锁定其它 tab）
        self.btn_marketing.setEnabled(False)
        self.btn_marketing.setText(self.tr("⏳  生成中..."))
        self.btn_merge.setEnabled(False)
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.pipeline_running_changed.emit(True)

        self.log_viewer.append_log(self.tr("开始生成营销内容..."), "INFO")
        self._marketing_worker.start()

    def _on_merge(self):
        """合并所有章节"""
        # 统一互斥：任一长任务运行中都不允许启动新任务
        if self.has_running_task():
            QMessageBox.warning(
                self, self.tr("提示"),
                self.tr("有任务正在运行中，请等待完成后再合并章节。")
            )
            return

        # 检查是否有已完成的章节
        cfg = load_config(self._config_path)
        output_dir = cfg.get("output_config", {}).get("output_dir", "data/output")
        if not os.path.isabs(output_dir):
            output_dir = os.path.join(os.path.dirname(self._config_path), output_dir)
        summary_file = os.path.join(output_dir, "summary.json")

        if not os.path.exists(summary_file):
            QMessageBox.warning(
                self, self.tr("提示"),
                self.tr("未找到章节摘要文件，请先生成至少一章内容。")
            )
            return

        # 确认合并
        reply = QMessageBox.question(
            self, self.tr("确认合并章节"),
            self.tr("将所有已完成的章节合并为一个完整文件。\n\n确定要继续吗？"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        # 创建 Worker
        self._merge_worker = MergeWorker(
            config_path=self._config_path,
            env_path=self._env_path,
        )

        # 连接信号
        self._merge_worker.merge_finished.connect(self._on_merge_finished)
        self._merge_worker.log_message.connect(self.log_viewer.append_log)
        self._attach_thread_lifecycle("_merge_worker")

        # 禁用按钮 + 广播全局 busy 状态（锁定其它 tab）
        self.btn_merge.setEnabled(False)
        self.btn_merge.setText(self.tr("⏳  合并中..."))
        self.btn_marketing.setEnabled(False)
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.pipeline_running_changed.emit(True)

        self.log_viewer.append_log(self.tr("开始合并所有章节..."), "INFO")
        self._merge_worker.start()

    # ------------------------------------------------------------------
    # Worker 信号处理
    # ------------------------------------------------------------------

    def _on_chapter_started(self, chapter_num: int):
        self.chapter_list.set_chapter_status(chapter_num, "running")

    def _on_chapter_completed(self, chapter_num: int, title: str):
        self.chapter_list.set_chapter_status(chapter_num, "completed")

    def _on_chapter_warning(self, chapter_num: int, warning_msg: str):
        self.chapter_list.set_chapter_status(chapter_num, "warning")
        self.log_viewer.append_log(
            self.tr("第 {0} 章降级接受: {1}").format(chapter_num, warning_msg), "WARNING"
        )

    def _on_chapter_failed(self, chapter_num: int, error_msg: str):
        self.chapter_list.set_chapter_status(chapter_num, "failed")
        self.log_viewer.append_log(
            self.tr("第 {0} 章失败: {1}").format(chapter_num, error_msg), "ERROR"
        )

    def _on_progress_updated(self, current: int, total: int):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

    def _on_pipeline_finished(self, success: bool):
        """流水线结束（成功或失败）"""
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_outline_only.setEnabled(True)
        self.btn_regen.setEnabled(False)
        self.btn_refresh.setEnabled(True)
        self.btn_merge.setEnabled(True)
        self.btn_marketing.setEnabled(True)
        self.pipeline_running_changed.emit(False)

        completed = self.chapter_list.get_completed_count()
        if success:
            self.log_viewer.append_log(
                self.tr("流水线完成，共生成 {0} 章。").format(completed), "INFO"
            )
        else:
            self.log_viewer.append_log(
                self.tr("流水线未完整完成，已生成 {0} 章。").format(completed), "WARNING"
            )

        # 引用清理改由 QThread.finished 触发（见 _attach_thread_lifecycle），
        # 这里不再立即置 None，避免在 run() 尚未返回时丢掉最后一个 Python 强引用。

    def _on_marketing_finished(self, success: bool, message: str):
        """营销内容生成完成"""
        self.btn_marketing.setEnabled(True)
        self.btn_marketing.setText(self.tr("📢  生成营销内容"))
        self.btn_merge.setEnabled(True)
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.pipeline_running_changed.emit(False)

        if success:
            QMessageBox.information(
                self, self.tr("生成成功"),
                message
            )
            self.log_viewer.append_log(self.tr("营销内容生成成功！"), "INFO")
        else:
            QMessageBox.critical(
                self, self.tr("生成失败"),
                self.tr("营销内容生成失败：\n{0}").format(message)
            )
            self.log_viewer.append_log(self.tr("营销内容生成失败: {0}").format(message), "ERROR")

        # 引用清理由 QThread.finished 触发，见 _attach_thread_lifecycle。
        # 旧逻辑：self._marketing_worker = None  ← 在 run() 尚未返回时丢引用会触发
        # "QThread: Destroyed while thread is still running" → zsh: abort。

    def _on_merge_finished(self, success: bool, message: str):
        """章节合并完成"""
        self.btn_merge.setEnabled(True)
        self.btn_merge.setText(self.tr("📚  合并所有章节"))
        self.btn_marketing.setEnabled(True)
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.pipeline_running_changed.emit(False)

        if success:
            QMessageBox.information(
                self, self.tr("合并成功"),
                self.tr("章节已成功合并到:\n{0}").format(message)
            )
            self.log_viewer.append_log(self.tr("章节合并成功: {0}").format(message), "INFO")
        else:
            QMessageBox.critical(
                self, self.tr("合并失败"),
                self.tr("章节合并失败:\n{0}").format(message)
            )
            self.log_viewer.append_log(self.tr("章节合并失败: {0}").format(message), "ERROR")

        # 引用清理由 QThread.finished 触发，见 _attach_thread_lifecycle。

    def _open_output_dir(self):
        """在系统文件管理器中打开输出目录"""
        from src.gui.utils.platform_utils import open_directory
        cfg = load_config(self._config_path)
        output_dir = (cfg.get("output_config") or {}).get("output_dir", "")
        if not output_dir:
            output_dir = os.path.join(os.path.dirname(self._config_path), "data", "output")
        # 相对路径基于配置文件目录
        if not os.path.isabs(output_dir):
            output_dir = os.path.join(os.path.dirname(self._config_path), output_dir)
        if not open_directory(output_dir):
            QMessageBox.warning(self, self.tr("目录不存在"), self.tr("输出目录不存在:\n{0}").format(output_dir))

    def changeEvent(self, event):
        """语言切换时更新按钮文本"""
        if event.type() == QEvent.Type.LanguageChange:
            # [5.4] 先回放 i18n 注册表(覆盖 QGroupBox 与普通 QPushButton)
            try:
                self._i18n_registry.retranslate_all()
            except Exception:
                pass
            # 状态相关按钮(含图标前缀)单独刷新
            self._retranslate_buttons()
        super().changeEvent(event)

    def _retranslate_buttons(self):
        """重新设置按钮文本（根据当前运行状态）"""
        is_running = self._worker is not None and self._worker.isRunning()
        if is_running:
            self.btn_start.setText(self.tr("⏹  停止"))
        else:
            self.btn_start.setText(self.tr("▶  启动"))
        self.btn_regen.setText(self.tr("🔄  重新生成选中章节"))
        self.btn_open_output.setText(self.tr("打开输出目录"))
