"""Tab3 - 创作进度：启动/停止流水线、章节列表、日志查看"""
import os
import json
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QCheckBox, QLineEdit, QSplitter, QProgressBar, QMessageBox,
    QLabel, QSpinBox, QGroupBox, QGridLayout, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QEvent

from src.gui.widgets.log_viewer import LogViewer
from src.gui.widgets.chapter_list import ChapterListWidget
from src.gui.workers.pipeline_worker import PipelineWorker
from src.gui.workers.marketing_worker import MarketingWorker
from src.gui.workers.merge_worker import MergeWorker
from src.gui.workers.outline_worker import OutlineWorker
from src.gui.workers.outline_audit_worker import OutlineAuditWorker
from src.gui.workers.outline_revision_worker import OutlineRevisionWorker
from src.gui.workers.novel_audit_worker import NovelAuditWorker
from src.gui.workers.content_revision_worker import ContentRevisionWorker
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
        self._outline_audit_worker: OutlineAuditWorker | None = None
        self._outline_revision_worker: OutlineRevisionWorker | None = None
        self._novel_audit_worker: NovelAuditWorker | None = None
        self._content_revision_worker: ContentRevisionWorker | None = None
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
        action_gap = 10
        compact_control_height = 30

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 6, 12, 6)
        root.setSpacing(4)

        # ---- 顶部控制区：按功能分组，避免按钮与范围控件互相挤压 ----
        controls = QVBoxLayout()
        controls.setSpacing(0)
        controls.setContentsMargins(0, 0, 0, 0)
        self._action_bar_layouts = []
        self._control_group_boxes = []

        def make_group(title: str) -> tuple[QGroupBox, QGridLayout]:
            group = QGroupBox(self.tr(title))
            group.setProperty("cssClass", "compact")
            group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            layout = QGridLayout(group)
            layout.setContentsMargins(8, 0, 8, 2)
            layout.setHorizontalSpacing(action_gap)
            layout.setVerticalSpacing(3)
            self._control_group_boxes.append(group)
            self._action_bar_layouts.append(layout)
            return group, layout

        def tune_button(button: QPushButton, min_width: int) -> None:
            button.setMinimumWidth(min_width)
            button.setFixedHeight(compact_control_height)
            button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)

        def tune_spin(spin_box: QSpinBox) -> None:
            spin_box.setFixedSize(68, compact_control_height)

        def make_label(text: str) -> QLabel:
            label = QLabel(self.tr(text))
            label.setStyleSheet("background: transparent;")
            label.setFixedHeight(compact_control_height)
            label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            return label

        self.btn_start = QPushButton(self.tr("▶  启动"))
        tune_button(self.btn_start, 108)
        self.btn_start.setProperty("cssClass", "success")
        self.btn_start.setToolTip(self.tr(
            "启动完整流水线（大纲 → 内容 → 定稿）\n"
            "按全书 target_chapters 全量续写，仅受「强制重生成大纲」与「额外提示词」影响\n"
            "「大纲范围」控件仅对「仅生成大纲」按钮生效，启动流水线时被忽略"
        ))

        self.btn_stop = QPushButton(self.tr("■  停止"))
        tune_button(self.btn_stop, 108)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setProperty("cssClass", "danger")

        self.chk_force_outline = QCheckBox(self.tr("强制重生成大纲"))
        self.chk_force_outline.setFixedHeight(compact_control_height)
        self.edit_extra_prompt = QLineEdit()
        self.edit_extra_prompt.setPlaceholderText(self.tr("额外提示词（可选）"))
        self.edit_extra_prompt.setMinimumWidth(260)
        self.edit_extra_prompt.setFixedHeight(compact_control_height)
        self.edit_extra_prompt.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        generation_group, generation_layout = make_group("生成控制")
        generation_layout.addWidget(self.btn_start, 0, 0)
        generation_layout.addWidget(self.btn_stop, 0, 1)
        generation_layout.addWidget(self.chk_force_outline, 0, 2)
        generation_layout.addWidget(make_label("额外提示词:"), 0, 3)
        generation_layout.addWidget(self.edit_extra_prompt, 0, 4)
        generation_layout.setColumnStretch(4, 1)
        controls.addWidget(generation_group)

        self.btn_outline_only = QPushButton(self.tr("📝  仅生成大纲"))
        tune_button(self.btn_outline_only, 138)
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
        tune_spin(self.spin_outline_start)

        self.spin_outline_end = QSpinBox()
        self.spin_outline_end.setRange(0, 9999)
        self.spin_outline_end.setValue(0)
        self.spin_outline_end.setSpecialValueText(self.tr("自动"))
        self.spin_outline_end.setToolTip(self.tr(
            "大纲结束章节（0 = 自动推断）\n"
            "仅作用于「仅生成大纲」按钮；启动流水线时被忽略"
        ))
        tune_spin(self.spin_outline_end)

        lbl_outline_range = make_label("大纲范围（仅大纲）:")
        lbl_outline_tilde = make_label("~")

        outline_options = QWidget()
        outline_options.setStyleSheet("background: transparent;")
        outline_options_row = QHBoxLayout(outline_options)
        outline_options_row.setContentsMargins(0, 0, 0, 0)
        outline_options_row.setSpacing(action_gap)
        outline_options_row.addWidget(self.btn_outline_only)
        outline_options_row.addWidget(lbl_outline_range)
        outline_options_row.addWidget(self.spin_outline_start)
        outline_options_row.addWidget(lbl_outline_tilde)
        outline_options_row.addWidget(self.spin_outline_end)
        outline_options_row.addStretch()
        generation_layout.addWidget(outline_options, 1, 0, 1, 5)

        self.btn_open_output = QPushButton(self.tr("打开输出目录"))
        self.btn_open_output.clicked.connect(self._open_output_dir)
        tune_button(self.btn_open_output, 120)

        self.btn_refresh = QPushButton(self.tr("↻  刷新章节"))
        tune_button(self.btn_refresh, 120)
        self.btn_refresh.setToolTip(self.tr("从磁盘重新加载章节状态"))

        self.btn_regen = QPushButton(self.tr("🔄  重新生成选中章节"))
        tune_button(self.btn_regen, 160)
        self.btn_regen.setEnabled(False)
        self.btn_regen.setToolTip(self.tr("在章节列表中选中要重新生成的章节，然后点击此按钮"))

        self.btn_merge = QPushButton(self.tr("📚  合并所有章节"))
        tune_button(self.btn_merge, 140)
        self.btn_merge.setToolTip(self.tr("将所有已完成的章节合并为一个完整文件"))
        self.btn_merge.setProperty("cssClass", "success")
        self.btn_merge.setStyleSheet(
            """
            QPushButton {
                background-color: #34C759;
                border: none;
                color: #FFFFFF;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #2DB84E;
            }
            QPushButton:disabled {
                background-color: #EBEDF0;
                color: #A0A4AA;
            }
            """
        )

        self.btn_marketing = QPushButton(self.tr("📢  生成营销内容"))
        tune_button(self.btn_marketing, 140)
        self.btn_marketing.setToolTip(self.tr("根据已完成的章节生成营销文案、标题和封面提示词"))
        self.btn_marketing.setProperty("cssClass", "info")

        chapter_group, chapter_layout = make_group("章节与产物")
        chapter_layout.addWidget(self.btn_open_output, 0, 0)
        chapter_layout.addWidget(self.btn_refresh, 0, 1)
        chapter_layout.addWidget(self.btn_regen, 0, 2)
        chapter_layout.addWidget(self.btn_merge, 1, 0)
        chapter_layout.addWidget(self.btn_marketing, 1, 1)
        chapter_layout.setColumnStretch(3, 1)

        self.btn_outline_audit = QPushButton(self.tr("🔍  大纲审计复核"))
        tune_button(self.btn_outline_audit, 150)
        self.btn_outline_audit.setToolTip(self.tr(
            "读取当前 outline.json，运行全局审计与 LLM 任务闭环复核，并写出 outline_audit_report.json"
        ))
        self.btn_outline_audit.setProperty("cssClass", "info")

        self.btn_novel_audit = QPushButton(self.tr("🔎  章节内容审计"))
        tune_button(self.btn_novel_audit, 150)
        self.btn_novel_audit.setToolTip(self.tr(
            "读取当前章节正文与 outline.json，审核正文大纲一致性和相邻章节衔接，并写出 content_audit_report.json"
        ))
        self.btn_novel_audit.setProperty("cssClass", "info")

        self.btn_novel_audit_selected = QPushButton(self.tr("🔎  审计选中章节"))
        tune_button(self.btn_novel_audit_selected, 150)
        self.btn_novel_audit_selected.setEnabled(False)
        self.btn_novel_audit_selected.setToolTip(self.tr(
            "仅审计章节列表中当前选中的章节，并检查上一章到选中章的入场衔接"
        ))
        self.btn_novel_audit_selected.setProperty("cssClass", "info")

        self.btn_content_revision = QPushButton(self.tr("🛠  修订内容"))
        tune_button(self.btn_content_revision, 130)
        self.btn_content_revision.setToolTip(self.tr(
            "优先读取 content_audit_report_scope.json，否则读取 content_audit_report.json，"
            "调用 content_model 对 fatal C1/C2 章节正文做必要修订，并自动备份原章节"
        ))
        self.btn_content_revision.setProperty("cssClass", "warning")

        self.btn_outline_revision = QPushButton(self.tr("🛠  修订大纲"))
        tune_button(self.btn_outline_revision, 130)
        self.btn_outline_revision.setToolTip(self.tr(
            "读取 outline_audit_report.json，调用 outline_model 对 outline.json 做必要修订，并自动备份原文件"
        ))
        self.btn_outline_revision.setProperty("cssClass", "warning")

        lbl_audit_range = make_label("小说审计范围:")
        self.spin_audit_start = QSpinBox()
        self.spin_audit_start.setRange(0, 9999)
        self.spin_audit_start.setValue(0)
        self.spin_audit_start.setSpecialValueText(self.tr("整部"))
        self.spin_audit_start.setToolTip(self.tr("审计起始章节（0 = 整部小说；指定范围时起止都需大于 0）"))
        tune_spin(self.spin_audit_start)

        lbl_audit_tilde = make_label("~")
        self.spin_audit_end = QSpinBox()
        self.spin_audit_end.setRange(0, 9999)
        self.spin_audit_end.setValue(0)
        self.spin_audit_end.setSpecialValueText(self.tr("整部"))
        self.spin_audit_end.setToolTip(self.tr("审计结束章节（0 = 整部小说；指定范围时起止都需大于 0）"))
        tune_spin(self.spin_audit_end)

        lbl_audit_batch = make_label("批大小:")
        self.spin_audit_batch_size = QSpinBox()
        self.spin_audit_batch_size.setRange(0, 50)
        self.spin_audit_batch_size.setValue(0)
        self.spin_audit_batch_size.setSpecialValueText(self.tr("默认"))
        self.spin_audit_batch_size.setToolTip(self.tr(
            "LLM 单次处理的章节/转场数量（0 = 使用配置默认；1 = 不分批）"
        ))
        tune_spin(self.spin_audit_batch_size)

        audit_group, audit_layout = make_group("审计与修订")
        audit_layout.addWidget(self.btn_outline_audit, 0, 0)
        audit_layout.addWidget(self.btn_outline_revision, 0, 1)
        audit_layout.addWidget(self.btn_novel_audit, 1, 0)
        audit_layout.addWidget(self.btn_novel_audit_selected, 1, 1)
        audit_layout.addWidget(self.btn_content_revision, 1, 2)

        audit_options = QWidget()
        audit_options.setStyleSheet("background: transparent;")
        audit_options_row = QHBoxLayout(audit_options)
        audit_options_row.setContentsMargins(0, 0, 0, 0)
        audit_options_row.setSpacing(action_gap)
        audit_options_row.addWidget(lbl_audit_range)
        audit_options_row.addWidget(self.spin_audit_start)
        audit_options_row.addWidget(lbl_audit_tilde)
        audit_options_row.addWidget(self.spin_audit_end)
        audit_options_row.addSpacing(8)
        audit_options_row.addWidget(lbl_audit_batch)
        audit_options_row.addWidget(self.spin_audit_batch_size)
        audit_options_row.addStretch()
        audit_layout.addWidget(audit_options, 2, 0, 1, 3)
        audit_layout.setColumnStretch(3, 1)

        grouped_actions = QWidget()
        grouped_actions.setStyleSheet("background: transparent;")
        grouped_actions_layout = QHBoxLayout(grouped_actions)
        grouped_actions_layout.setContentsMargins(0, 0, 0, 0)
        grouped_actions_layout.setSpacing(6)
        grouped_actions_layout.addWidget(chapter_group, 1)
        grouped_actions_layout.addWidget(audit_group, 1)
        controls.addWidget(grouped_actions)

        root.addLayout(controls)

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
        self.btn_outline_audit.clicked.connect(self._on_run_outline_audit)
        self.btn_novel_audit.clicked.connect(self._on_run_novel_audit)
        self.btn_novel_audit_selected.clicked.connect(
            lambda _checked=False: self._on_run_novel_audit(selected_only=True)
        )
        self.btn_content_revision.clicked.connect(self._on_revise_content_from_audit)
        self.btn_outline_revision.clicked.connect(self._on_revise_outline_from_audit)
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
        # 统一互斥：任一长任务运行中都不允许再启动流水线
        if self.has_running_task():
            QMessageBox.warning(
                self, self.tr("提示"),
                self.tr("有任务正在运行中，请等待完成后再启动新任务。"),
            )
            return

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
        self._set_actions_busy(True)

        self._worker.start()

    def _on_stop(self):
        """请求停止所有长任务（流水线 / 大纲 / 合并 / 营销 / 审计）"""
        stopped_any = False
        for w in (
            self._worker, self._outline_worker, self._merge_worker,
            self._marketing_worker, self._outline_audit_worker,
            self._outline_revision_worker, self._novel_audit_worker,
            self._content_revision_worker,
        ):
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
            self._outline_audit_worker, self._outline_revision_worker,
            self._novel_audit_worker, self._content_revision_worker,
        ))

    def shutdown_workers(self, wait_ms: int = 8000):
        """请求停止并等待所有后台 worker 完成（主窗口关闭时调用）"""
        for w in (
            self._worker, self._outline_worker, self._merge_worker,
            self._marketing_worker, self._outline_audit_worker,
            self._outline_revision_worker, self._novel_audit_worker,
            self._content_revision_worker,
        ):
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

    def _set_actions_busy(self, busy: bool) -> None:
        """统一切换长任务运行期间的动作按钮可用状态并广播 busy 信号。

        所有任务的启动/结束必须经由此方法切换按钮，禁止逐处手写
        setEnabled 清单——手写清单已多次漏项（如流水线结束后「修订内容」
        未恢复、大纲生成期间「重新生成」未禁用导致可并发启动流水线）。
        """
        for button in (
            self.btn_start, self.btn_outline_only, self.btn_refresh,
            self.btn_merge, self.btn_marketing, self.btn_outline_audit,
            self.btn_novel_audit, self.btn_content_revision,
            self.btn_outline_revision,
        ):
            button.setEnabled(not busy)
        has_selection = len(self.chapter_list.get_selected_chapter_numbers()) > 0
        self.btn_regen.setEnabled(not busy and has_selection)
        self.btn_novel_audit_selected.setEnabled(not busy and has_selection)
        self.btn_stop.setEnabled(busy)
        self.pipeline_running_changed.emit(busy)

    def _on_selection_changed(self):
        """章节列表选择变化时，更新重新生成按钮状态"""
        selected = self.chapter_list.get_selected_chapter_numbers()
        # 流水线运行中或无选中时禁用
        is_running = self.has_running_task()
        self.btn_regen.setEnabled(len(selected) > 0 and not is_running)
        self.btn_novel_audit_selected.setEnabled(len(selected) > 0 and not is_running)
        if selected:
            self.btn_regen.setText(self.tr("🔄  重新生成 {0} 章").format(len(selected)))
            self.btn_novel_audit_selected.setText(self.tr("🔎  审计 {0} 章").format(len(selected)))
        else:
            self.btn_regen.setText(self.tr("🔄  重新生成选中章节"))
            self.btn_novel_audit_selected.setText(self.tr("🔎  审计选中章节"))

    def _on_regen(self):
        """重新生成选中的章节"""
        # 统一互斥：其他流程（如大纲生成/合并）运行中禁止并发启动流水线
        if self.has_running_task():
            QMessageBox.warning(
                self, self.tr("提示"),
                self.tr("有任务正在运行中，请等待完成后再启动新任务。"),
            )
            return

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

        self.btn_outline_only.setText(self.tr("⏳  大纲生成中..."))
        self._set_actions_busy(True)

        self.log_viewer.append_log(self.tr("开始生成大纲..."), "INFO")
        self._outline_worker.start()

    def _on_outline_finished(self, success: bool, message: str):
        """大纲生成完成"""
        self.btn_outline_only.setText(self.tr("📝  仅生成大纲"))
        self._set_actions_busy(False)

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
        self.btn_marketing.setText(self.tr("⏳  生成中..."))
        self._set_actions_busy(True)

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
        self.btn_merge.setText(self.tr("⏳  合并中..."))
        self._set_actions_busy(True)

        self.log_viewer.append_log(self.tr("开始合并所有章节..."), "INFO")
        self._merge_worker.start()

    def _on_run_outline_audit(self):
        """手动运行大纲审计复核"""
        if self.has_running_task():
            QMessageBox.warning(
                self, self.tr("提示"),
                self.tr("有任务正在运行中，请等待完成后再进行大纲审计复核。"),
            )
            return

        cfg = load_config(self._config_path)
        output_dir = cfg.get("output_config", {}).get("output_dir", "data/output")
        if not os.path.isabs(output_dir):
            output_dir = os.path.join(os.path.dirname(self._config_path), output_dir)
        outline_file = os.path.join(output_dir, "outline.json")

        if not os.path.exists(outline_file):
            QMessageBox.warning(
                self, self.tr("提示"),
                self.tr("未找到 outline.json，请先生成大纲。"),
            )
            return

        reply = QMessageBox.question(
            self, self.tr("确认大纲审计复核"),
            self.tr(
                "将读取当前 outline.json，运行全局审计并调用 outline_model 进行 LLM 任务闭环复核。\n\n"
                "这可能需要较长时间并消耗模型额度，确定要继续吗？"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        self._outline_audit_worker = OutlineAuditWorker(
            config_path=self._config_path,
            env_path=self._env_path,
        )
        self._outline_audit_worker.audit_finished.connect(self._on_outline_audit_finished)
        self._outline_audit_worker.log_message.connect(self.log_viewer.append_log)
        self._attach_thread_lifecycle("_outline_audit_worker")

        self.btn_outline_audit.setText(self.tr("⏳  审计中..."))
        self._set_actions_busy(True)

        self.log_viewer.append_log(self.tr("开始大纲审计复核..."), "INFO")
        self._outline_audit_worker.start()

    def _on_revise_content_from_audit(self):
        """根据章节内容审计报告修订章节正文。"""
        if self.has_running_task():
            QMessageBox.warning(
                self, self.tr("提示"),
                self.tr("有任务正在运行中，请等待完成后再修订章节内容。"),
            )
            return

        cfg = load_config(self._config_path)
        output_dir = cfg.get("output_config", {}).get("output_dir", "data/output")
        if not os.path.isabs(output_dir):
            output_dir = os.path.join(os.path.dirname(self._config_path), output_dir)
        outline_file = os.path.join(output_dir, "outline.json")
        scoped_report = os.path.join(output_dir, "content_audit_report_scope.json")
        full_report = os.path.join(output_dir, "content_audit_report.json")
        audit_report_file = scoped_report if os.path.exists(scoped_report) else full_report

        if not os.path.exists(outline_file):
            QMessageBox.warning(
                self, self.tr("提示"),
                self.tr("未找到 outline.json，请先生成大纲。"),
            )
            return
        if not os.path.exists(audit_report_file):
            QMessageBox.warning(
                self, self.tr("提示"),
                self.tr("未找到 content_audit_report*.json，请先运行章节内容审计。"),
            )
            return

        report_name = os.path.basename(audit_report_file)
        reply = QMessageBox.question(
            self, self.tr("确认修订内容"),
            self.tr(
                "将读取 {0}，并调用 content_model 对 fatal C1/C2 审计结果做必要正文修订。\n\n"
                "操作会写回章节 .txt，并自动生成备份文件。这可能消耗模型额度，确定要继续吗？"
            ).format(report_name),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        self._content_revision_worker = ContentRevisionWorker(
            config_path=self._config_path,
            env_path=self._env_path,
        )
        self._content_revision_worker.content_revision_finished.connect(self._on_content_revision_finished)
        self._content_revision_worker.log_message.connect(self.log_viewer.append_log)
        self._attach_thread_lifecycle("_content_revision_worker")

        self.btn_content_revision.setText(self.tr("⏳  修订中..."))
        self._set_actions_busy(True)

        self.log_viewer.append_log(self.tr("开始根据内容审计报告修订章节正文..."), "INFO")
        self._content_revision_worker.start()

    def _on_revise_outline_from_audit(self):
        """根据审计报告修订大纲"""
        if self.has_running_task():
            QMessageBox.warning(
                self, self.tr("提示"),
                self.tr("有任务正在运行中，请等待完成后再修订大纲。"),
            )
            return

        cfg = load_config(self._config_path)
        output_dir = cfg.get("output_config", {}).get("output_dir", "data/output")
        if not os.path.isabs(output_dir):
            output_dir = os.path.join(os.path.dirname(self._config_path), output_dir)
        outline_file = os.path.join(output_dir, "outline.json")
        audit_report_file = os.path.join(output_dir, "outline_audit_report.json")

        if not os.path.exists(outline_file):
            QMessageBox.warning(
                self, self.tr("提示"),
                self.tr("未找到 outline.json，请先生成大纲。"),
            )
            return
        if not os.path.exists(audit_report_file):
            QMessageBox.warning(
                self, self.tr("提示"),
                self.tr("未找到 outline_audit_report.json，请先运行大纲审计复核。"),
            )
            return

        reply = QMessageBox.question(
            self, self.tr("确认修订大纲"),
            self.tr(
                "将读取 outline_audit_report.json，并调用 outline_model 对 fatal 审计结果做必要修订。\n\n"
                "操作会写回 outline.json，并自动生成备份文件。这可能消耗模型额度，确定要继续吗？"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        self._outline_revision_worker = OutlineRevisionWorker(
            config_path=self._config_path,
            env_path=self._env_path,
        )
        self._outline_revision_worker.revision_finished.connect(self._on_outline_revision_finished)
        self._outline_revision_worker.log_message.connect(self.log_viewer.append_log)
        self._attach_thread_lifecycle("_outline_revision_worker")

        self.btn_outline_revision.setText(self.tr("⏳  修订中..."))
        self._set_actions_busy(True)

        self.log_viewer.append_log(self.tr("开始根据审计报告修订大纲..."), "INFO")
        self._outline_revision_worker.start()

    def _resolve_novel_audit_chapters(self, selected_only: bool) -> list[int] | None:
        """根据选中项或范围控件解析本次小说内容审计章节。"""
        if selected_only:
            selected = self.chapter_list.get_selected_chapter_numbers()
            return selected or []
        start = self.spin_audit_start.value()
        end = self.spin_audit_end.value()
        if start <= 0 and end <= 0:
            return None
        if start <= 0 or end <= 0:
            return []
        if start > end:
            start, end = end, start
        return list(range(start, end + 1))

    def _resolve_novel_audit_batch_size(self, cfg: dict) -> int | None:
        """解析小说内容审计批大小，0 表示使用配置默认值。"""
        value = self.spin_audit_batch_size.value()
        if value > 0:
            return value
        configured = (cfg.get("generation_config") or {}).get("content_audit_batch_size")
        try:
            configured_value = int(configured)
        except (TypeError, ValueError):
            return None
        return configured_value if configured_value > 0 else None

    def _on_run_novel_audit(self, selected_only: bool = False):
        """手动运行小说章节内容审计。"""
        if self.has_running_task():
            QMessageBox.warning(
                self, self.tr("提示"),
                self.tr("有任务正在运行中，请等待完成后再进行整部小说审计。"),
            )
            return

        cfg = load_config(self._config_path)
        output_dir = cfg.get("output_config", {}).get("output_dir", "data/output")
        if not os.path.isabs(output_dir):
            output_dir = os.path.join(os.path.dirname(self._config_path), output_dir)
        outline_file = os.path.join(output_dir, "outline.json")

        if not os.path.exists(outline_file):
            QMessageBox.warning(
                self, self.tr("提示"),
                self.tr("未找到 outline.json，请先生成大纲。"),
            )
            return
        if not os.path.isdir(output_dir):
            QMessageBox.warning(
                self, self.tr("提示"),
                self.tr("未找到输出目录，请先生成章节内容。"),
            )
            return

        content_exists = False
        for filename in os.listdir(output_dir):
            if not filename.endswith(".txt"):
                continue
            if "_摘要" in filename or "_imitated" in filename or "_original" in filename:
                continue
            if filename.startswith("第") and "章_" in filename:
                content_exists = True
                break
        if not content_exists:
            QMessageBox.warning(
                self, self.tr("提示"),
                self.tr("未找到章节正文文件，请先生成至少一章内容。"),
            )
            return

        chapter_numbers = self._resolve_novel_audit_chapters(selected_only)
        if chapter_numbers == []:
            if selected_only:
                message = self.tr("请先在章节列表中选中要审计的章节。")
            else:
                message = self.tr("请同时填写小说审计范围的起始和结束章节，或都设为 0 审计整部小说。")
            QMessageBox.information(self, self.tr("提示"), message)
            return
        batch_size = self._resolve_novel_audit_batch_size(cfg)
        scope_text = self.tr("整部小说") if chapter_numbers is None else self.tr("指定 {0} 章").format(len(chapter_numbers))
        batch_text = self.tr("配置默认") if batch_size is None else str(batch_size)

        reply = QMessageBox.question(
            self, self.tr("确认小说内容审计"),
            self.tr(
                "将读取当前章节正文与 outline.json，调用 content_model 审核正文大纲一致性和相邻章节衔接。\n\n"
                "审计范围：{0}\n批大小：{1}\n\n这可能需要较长时间并消耗模型额度，确定要继续吗？"
            ).format(scope_text, batch_text),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        self._novel_audit_worker = NovelAuditWorker(
            config_path=self._config_path,
            env_path=self._env_path,
            chapter_numbers=chapter_numbers,
            batch_size=batch_size,
        )
        self._novel_audit_worker.novel_audit_finished.connect(self._on_novel_audit_finished)
        self._novel_audit_worker.log_message.connect(self.log_viewer.append_log)
        self._attach_thread_lifecycle("_novel_audit_worker")

        self.btn_novel_audit.setText(self.tr("⏳  小说审计中..."))
        self._set_actions_busy(True)

        if chapter_numbers is None:
            self.log_viewer.append_log(self.tr("开始整部小说审计..."), "INFO")
        else:
            self.log_viewer.append_log(self.tr("开始指定章节小说审计，共 {0} 章...").format(len(chapter_numbers)), "INFO")
        self._novel_audit_worker.start()

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
        self._set_actions_busy(False)

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
        self.btn_marketing.setText(self.tr("📢  生成营销内容"))
        self._set_actions_busy(False)

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

    def _on_merge_finished(self, success: bool, paths: list):
        """章节合并完成。paths:成功时为产物路径列表,失败时为错误消息列表。"""
        self.btn_merge.setText(self.tr("📚  合并所有章节"))
        self._set_actions_busy(False)

        if success:
            if len(paths) == 1:
                summary = self.tr("章节已成功合并到:\n{0}").format(paths[0])
            else:
                dir_path = os.path.dirname(paths[0]) if paths else ""
                file_lines = "\n".join(os.path.basename(p) for p in paths)
                summary = self.tr("已分卷输出 {0} 个文件到目录:\n{1}\n\n文件清单:\n{2}").format(
                    len(paths), dir_path, file_lines
                )
            QMessageBox.information(self, self.tr("合并成功"), summary)
            self.log_viewer.append_log(self.tr("章节合并成功,产物 {0} 个文件").format(len(paths)), "INFO")
        else:
            err = paths[0] if paths else self.tr("未知错误")
            QMessageBox.critical(
                self, self.tr("合并失败"),
                self.tr("章节合并失败:\n{0}").format(err)
            )
            self.log_viewer.append_log(self.tr("章节合并失败: {0}").format(err), "ERROR")

        # 引用清理由 QThread.finished 触发，见 _attach_thread_lifecycle。

    def _on_outline_audit_finished(self, success: bool, message: str):
        """大纲审计复核完成"""
        self.btn_outline_audit.setText(self.tr("🔍  大纲审计复核"))
        self._set_actions_busy(False)

        if success:
            QMessageBox.information(self, self.tr("大纲审计完成"), message)
            self.log_viewer.append_log(self.tr("大纲审计复核完成。"), "INFO")
        else:
            QMessageBox.critical(
                self, self.tr("大纲审计失败"),
                self.tr("大纲审计复核失败：\n{0}").format(message),
            )
            self.log_viewer.append_log(self.tr("大纲审计复核失败: {0}").format(message), "ERROR")

        # 引用清理由 QThread.finished 触发，见 _attach_thread_lifecycle。

    def _on_outline_revision_finished(self, success: bool, message: str):
        """大纲修订完成"""
        self.btn_outline_revision.setText(self.tr("🛠  修订大纲"))
        self._set_actions_busy(False)

        if success:
            QMessageBox.information(self, self.tr("大纲修订完成"), message)
            self.log_viewer.append_log(self.tr("大纲修订完成。"), "INFO")
        else:
            QMessageBox.critical(
                self, self.tr("大纲修订失败"),
                self.tr("大纲修订失败：\n{0}").format(message),
            )
            self.log_viewer.append_log(self.tr("大纲修订失败: {0}").format(message), "ERROR")

        # 引用清理由 QThread.finished 触发，见 _attach_thread_lifecycle。

    def _on_content_revision_finished(self, success: bool, message: str):
        """章节内容修订完成。"""
        self.btn_content_revision.setText(self.tr("🛠  修订内容"))
        self._set_actions_busy(False)

        if success:
            QMessageBox.information(self, self.tr("内容修订完成"), message)
            self.log_viewer.append_log(self.tr("章节内容修订完成。"), "INFO")
            self.load_chapters()
        else:
            QMessageBox.critical(
                self, self.tr("内容修订失败"),
                self.tr("章节内容修订失败：\n{0}").format(message),
            )
            self.log_viewer.append_log(self.tr("章节内容修订失败: {0}").format(message), "ERROR")

        # 引用清理由 QThread.finished 触发，见 _attach_thread_lifecycle。

    def _on_novel_audit_finished(self, success: bool, message: str):
        """整部小说内容审计完成。"""
        self.btn_novel_audit.setText(self.tr("🔎  章节内容审计"))
        self._set_actions_busy(False)

        if success:
            QMessageBox.information(self, self.tr("整部小说审计完成"), message)
            self.log_viewer.append_log(self.tr("整部小说审计完成。"), "INFO")
        else:
            QMessageBox.critical(
                self, self.tr("整部小说审计失败"),
                self.tr("整部小说审计失败：\n{0}").format(message),
            )
            self.log_viewer.append_log(self.tr("整部小说审计失败: {0}").format(message), "ERROR")

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
        self.btn_start.setText(self.tr("▶  启动"))
        self.btn_regen.setText(self.tr("🔄  重新生成选中章节"))
        self.btn_open_output.setText(self.tr("打开输出目录"))
        if self._outline_audit_worker is not None and self._outline_audit_worker.isRunning():
            self.btn_outline_audit.setText(self.tr("⏳  审计中..."))
        else:
            self.btn_outline_audit.setText(self.tr("🔍  大纲审计复核"))
        if self._novel_audit_worker is not None and self._novel_audit_worker.isRunning():
            self.btn_novel_audit.setText(self.tr("⏳  小说审计中..."))
        else:
            self.btn_novel_audit.setText(self.tr("🔎  章节内容审计"))
        if self._content_revision_worker is not None and self._content_revision_worker.isRunning():
            self.btn_content_revision.setText(self.tr("⏳  修订中..."))
        else:
            self.btn_content_revision.setText(self.tr("🛠  修订内容"))
        if self._outline_revision_worker is not None and self._outline_revision_worker.isRunning():
            self.btn_outline_revision.setText(self.tr("⏳  修订中..."))
        else:
            self.btn_outline_revision.setText(self.tr("🛠  修订大纲"))
