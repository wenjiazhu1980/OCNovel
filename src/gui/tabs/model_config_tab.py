"""Tab1: 模型配置面板"""
import os
from functools import partial
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QLineEdit, QComboBox, QCheckBox, QLabel,
    QPushButton, QScrollArea, QMessageBox, QDoubleSpinBox,
)
from PySide6.QtCore import QEvent

from ..utils.config_io import load_env, save_env, load_config, save_config
from ..workers.connection_tester import ConnectionTesterWorker

# 提供商选项（已移除火山引擎，统一使用大纲/内容模型配置）
PROVIDERS = ["gemini", "openai", "claude"]
# API 模式选项
API_MODES = ["auto", "chat", "responses"]


class ModelConfigTab(QWidget):
    """模型配置 Tab"""

    def __init__(self, env_path: str, config_path: str, parent=None):
        super().__init__(parent)
        self._env_path = env_path
        self._config_path = config_path
        self._fields: dict[str, QWidget] = {}  # env_key -> widget
        self._testers: list[ConnectionTesterWorker] = []
        # 需要在"生成中"状态下一并禁用的关键按钮（加载 / 保存 / 各测试按钮）
        self._lockable_buttons: list[QPushButton] = []
        self._group_boxes: list[QGroupBox] = []
        # [5.4] i18n 注册表
        from ..utils.i18n_helper import RetranslateRegistry
        self._i18n_registry = RetranslateRegistry(self.tr)

        self._init_ui()
        self._auto_register_translatable_widgets()
        self._load(silent=True)

    def _auto_register_translatable_widgets(self) -> None:
        """[5.4] 扫描 QGroupBox 与 QPushButton,自动登记到 i18n 注册表"""
        try:
            from PySide6.QtWidgets import QGroupBox, QPushButton
            for gb in self.findChildren(QGroupBox):
                title = gb.title()
                if title:
                    self._i18n_registry.register_title(gb, title)
            for btn in self.findChildren(QPushButton):
                text = btn.text()
                if text:
                    self._i18n_registry.register_text(btn, text)
        except Exception:
            pass

    # ── UI 构建 ──────────────────────────────────────────

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        container = QWidget()
        self._layout = QVBoxLayout(container)
        self._layout.setSpacing(16)
        self._layout.setContentsMargins(16, 16, 16, 16)

        # 硅基流动注册提示
        tip = QLabel(
            self.tr('免费获取 API Key：'
            '<a href="https://cloud.siliconflow.cn">注册硅基流动账号</a>'
            '（注册即送额度，支持 Qwen / DeepSeek 等开源模型）')
        )
        tip.setOpenExternalLinks(True)
        tip.setWordWrap(True)
        self._layout.addWidget(tip)

        self._build_gemini_group()
        self._build_claude_group()
        self._build_openai_embedding_group()
        self._build_reranker_group()
        self._build_outline_model_group()
        self._build_content_model_group()
        self._build_fallback_group()
        self._build_model_selection_group()

        self._layout.addStretch()
        scroll.setWidget(container)
        outer.addWidget(scroll)

        # 底部按钮栏
        btn_bar = QHBoxLayout()
        btn_bar.setContentsMargins(16, 10, 16, 12)
        btn_bar.addStretch()
        self._btn_load = QPushButton(self.tr("加载配置"))
        self._btn_save = QPushButton(self.tr("保存配置"))
        self._btn_save.setProperty("cssClass", "primary")
        self._btn_load.clicked.connect(self._load)
        self._btn_save.clicked.connect(self._save)
        btn_bar.addWidget(self._btn_load)
        btn_bar.addWidget(self._btn_save)
        outer.addLayout(btn_bar)
        # 加入统一锁定列表
        self._lockable_buttons.extend([self._btn_load, self._btn_save])

    # ── 各提供商分组 ────────────────────────────────────

    def _add_field(self, form: QFormLayout, label: str, env_key: str,
                   *, echo_password: bool = False, placeholder: str = ""):
        """向表单添加一行 QLineEdit 并注册到 _fields"""
        edit = QLineEdit()
        if echo_password:
            edit.setEchoMode(QLineEdit.EchoMode.Password)
        if placeholder:
            edit.setPlaceholderText(placeholder)
        form.addRow(label, edit)
        self._fields[env_key] = edit
        return edit

    def _add_combo_field(self, form: QFormLayout, label: str, env_key: str,
                         items: list[str]):
        """向表单添加一行 QComboBox 并注册到 _fields"""
        combo = QComboBox()
        combo.addItems(items)
        form.addRow(label, combo)
        self._fields[env_key] = combo
        return combo

    def _make_group(self, title: str, provider_key: str | None = None):
        """创建 QGroupBox + QFormLayout，可选附带测试按钮"""
        group = QGroupBox(title)
        self._group_boxes.append(group)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        group.setLayout(form)
        self._layout.addWidget(group)
        return group, form

    def _add_test_button(self, form: QFormLayout, provider_key: str):
        """在表单末尾添加测试连接按钮"""
        btn = QPushButton(self.tr("测试连接"))
        btn.setMinimumWidth(120)  # 设置最小宽度而非固定宽度,允许按钮根据文本自动扩展
        btn.setProperty("cssClass", "primary")
        btn.clicked.connect(partial(self._on_test, provider_key))
        form.addRow("", btn)
        # 加入统一锁定列表，生成过程中应禁止发起测试请求
        self._lockable_buttons.append(btn)
        return btn

    def _build_gemini_group(self):
        _, form = self._make_group(self.tr("Gemini (仅支持 Google 官方 API)"))
        self._add_field(form, self.tr("API Key"), "GEMINI_API_KEY", echo_password=True)
        self._add_field(form, self.tr("大纲模型 ID"), "GEMINI_OUTLINE_MODEL",
                        placeholder="gemini-2.5-pro")
        self._add_field(form, self.tr("内容模型 ID"), "GEMINI_CONTENT_MODEL",
                        placeholder="gemini-2.5-flash")
        self._add_field(form, self.tr("超时 (秒)"), "GEMINI_TIMEOUT", placeholder="300")
        self._add_field(form, self.tr("最大重试"), "GEMINI_MAX_RETRIES", placeholder="3")
        self._add_field(form, self.tr("重试延迟 (秒)"), "GEMINI_RETRY_DELAY", placeholder="90")
        self._add_test_button(form, "gemini")

    def _build_claude_group(self):
        _, form = self._make_group(self.tr("Claude (Anthropic 官方 API)"))
        self._add_field(form, self.tr("API Key"), "CLAUDE_API_KEY", echo_password=True)
        self._add_field(form, self.tr("大纲模型 ID"), "CLAUDE_OUTLINE_MODEL",
                        placeholder="claude-3-5-sonnet-20241022")
        self._add_field(form, self.tr("内容模型 ID"), "CLAUDE_CONTENT_MODEL",
                        placeholder="claude-3-5-sonnet-20241022")
        self._add_field(form, self.tr("超时 (秒)"), "CLAUDE_TIMEOUT", placeholder="120")
        self._add_field(form, self.tr("重试延迟 (秒)"), "CLAUDE_RETRY_DELAY", placeholder="10")
        self._add_test_button(form, "claude")

    def _build_openai_embedding_group(self):
        _, form = self._make_group(self.tr("OpenAI Embedding"))
        self._add_field(form, self.tr("API Key"), "OPENAI_EMBEDDING_API_KEY", echo_password=True)
        self._add_field(form, self.tr("Base URL"), "OPENAI_EMBEDDING_API_BASE",
                        placeholder="https://api.siliconflow.cn/v1")
        self._add_field(form, self.tr("模型名称"), "OPENAI_EMBEDDING_MODEL")
        self._add_field(form, self.tr("超时 (秒)"), "OPENAI_EMBEDDING_TIMEOUT", placeholder="60")
        self._add_test_button(form, "openai_embedding")

    def _build_reranker_group(self):
        _, form = self._make_group(self.tr("Reranker（复用 Embedding 的 API Key / Base URL）"))
        self._add_field(form, self.tr("模型名称"), "OPENAI_RERANKER_MODEL",
                        placeholder="Qwen/Qwen3-Reranker-0.6B")
        cb = QCheckBox(self.tr("启用 FP16"))
        cb.setChecked(True)
        form.addRow(self.tr("精度"), cb)
        self._fields["OPENAI_RERANKER_USE_FP16"] = cb

    def _make_temperature_spin(self, default: float = 1.0) -> QDoubleSpinBox:
        """创建温度输入控件（范围 0.0-2.0，步长 0.05）"""
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 2.0)
        spin.setSingleStep(0.05)
        spin.setDecimals(2)
        spin.setValue(default)
        spin.setToolTip(self.tr(
            "采样温度。0 = 完全确定性（适合结构化输出/JSON），1 = 标准创造性，>1 = 高随机。\n"
            "大纲建议 0.3-0.7（结构稳定），内容建议 0.7-1.0（保留文笔多样性）。"
        ))
        return spin

    def _build_outline_model_group(self):
        _, form = self._make_group(self.tr("大纲模型"))
        self._add_field(form, self.tr("API Key"), "OPENAI_OUTLINE_API_KEY", echo_password=True)
        self._add_field(form, self.tr("Base URL"), "OPENAI_OUTLINE_API_BASE",
                        placeholder="https://api.siliconflow.cn/v1")
        self._add_combo_field(form, self.tr("API 模式"), "OPENAI_OUTLINE_API_MODE",
                              API_MODES)
        self._add_field(form, self.tr("模型名称"), "OPENAI_OUTLINE_MODEL",
                        placeholder="Qwen/Qwen2.5-7B-Instruct")
        self._add_field(form, self.tr("超时 (秒)"), "OPENAI_OUTLINE_TIMEOUT", placeholder="120")
        # 温度（写入 config.json 的 model_config.outline_model.temperature）
        self._outline_temperature = self._make_temperature_spin(default=0.5)
        form.addRow(self.tr("温度 (Temperature)"), self._outline_temperature)
        # 推理（Reasoning）设置
        cb = QCheckBox(self.tr("启用推理（Thinking/Reasoning）"))
        form.addRow("", cb)
        self._fields["OPENAI_OUTLINE_REASONING_ENABLED"] = cb
        self._add_test_button(form, "openai_outline")

    def _build_content_model_group(self):
        _, form = self._make_group(self.tr("内容模型"))
        self._add_field(form, self.tr("API Key"), "OPENAI_CONTENT_API_KEY", echo_password=True)
        self._add_field(form, self.tr("Base URL"), "OPENAI_CONTENT_API_BASE",
                        placeholder="https://api.siliconflow.cn/v1")
        self._add_combo_field(form, self.tr("API 模式"), "OPENAI_CONTENT_API_MODE",
                              API_MODES)
        self._add_field(form, self.tr("模型名称"), "OPENAI_CONTENT_MODEL",
                        placeholder="Qwen/Qwen2.5-7B-Instruct")
        self._add_field(form, self.tr("超时 (秒)"), "OPENAI_CONTENT_TIMEOUT", placeholder="180")
        # 温度（写入 config.json 的 model_config.content_model.temperature）
        self._content_temperature = self._make_temperature_spin(default=0.85)
        form.addRow(self.tr("温度 (Temperature)"), self._content_temperature)
        # 推理（Reasoning）设置
        cb = QCheckBox(self.tr("启用推理（Thinking/Reasoning）"))
        form.addRow("", cb)
        self._fields["OPENAI_CONTENT_REASONING_ENABLED"] = cb
        self._add_test_button(form, "openai_content")

    def _build_fallback_group(self):
        _, form = self._make_group(self.tr("备用模型 (Fallback)"))
        self._add_field(form, self.tr("API Key"), "FALLBACK_API_KEY", echo_password=True)
        self._add_field(form, self.tr("Base URL"), "FALLBACK_API_BASE",
                        placeholder="https://api.siliconflow.cn/v1")
        self._add_field(form, self.tr("模型 ID"), "FALLBACK_MODEL_ID",
                        placeholder="Qwen/Qwen2.5-7B-Instruct")
        self._add_combo_field(form, self.tr("API 模式"), "FALLBACK_API_MODE",
                              API_MODES)
        self._add_test_button(form, "fallback")

    def _build_model_selection_group(self):
        group = QGroupBox(self.tr("模型选择"))
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        group.setLayout(form)

        self._outline_provider = QComboBox()
        self._outline_provider.addItems(PROVIDERS)
        form.addRow(self.tr("大纲生成提供商"), self._outline_provider)

        self._content_provider = QComboBox()
        self._content_provider.addItems(PROVIDERS)
        form.addRow(self.tr("内容生成提供商"), self._content_provider)

        self._layout.addWidget(group)

    # ── 路径切换 + 重新加载 ────────────────────────────

    def _derive_env_path(self) -> str:
        """根据当前 config_path 目录自动派生 .env 路径。"""
        return os.path.join(os.path.dirname(self._config_path), ".env")

    def set_config_path(self, path: str):
        self._config_path = path
        # 自动同步 .env 路径到当前 config 所在目录
        self._env_path = self._derive_env_path()

    def set_env_path(self, path: str):
        self._env_path = path

    def reload(self):
        self._load()

    # ── 加载 / 保存 ─────────────────────────────────────

    def _load(self, silent: bool = False):
        """从配置目录下的 .env 和 config.json 加载配置到界面"""
        # 始终以当前 config_path 所在目录下的 .env 为准
        self._env_path = self._derive_env_path()
        if not os.path.exists(self._env_path):
            if not silent:
                QMessageBox.warning(
                    self, self.tr("文件不存在"),
                    self.tr(".env 文件不存在:\n{0}\n\n请在该目录下创建 .env 文件，或先点击「保存配置」自动生成。").format(self._env_path),
                )
            return
        env = load_env(self._env_path)

        for key, widget in self._fields.items():
            if isinstance(widget, QCheckBox):
                widget.setChecked(env.get(key, "true").lower() == "true")
            elif isinstance(widget, QComboBox):
                val = env.get(key, "").strip().lower()
                idx = widget.findText(val)
                widget.setCurrentIndex(idx if idx >= 0 else 0)
            elif isinstance(widget, QLineEdit):
                widget.setText(env.get(key, ""))

        # 模型选择
        cfg = load_config(self._config_path)
        ms = cfg.get("generation_config", {}).get("model_selection", {})
        outline_prov = ms.get("outline", {}).get("provider", "openai")
        content_prov = ms.get("content", {}).get("provider", "openai")
        idx = self._outline_provider.findText(outline_prov)
        if idx >= 0:
            self._outline_provider.setCurrentIndex(idx)
        idx = self._content_provider.findText(content_prov)
        if idx >= 0:
            self._content_provider.setCurrentIndex(idx)

        # 温度（从 model_config 覆盖块读取，缺失时保留控件默认值）
        mc = cfg.get("model_config", {}) or {}
        outline_temp = mc.get("outline_model", {}).get("temperature")
        if isinstance(outline_temp, (int, float)):
            self._outline_temperature.setValue(float(outline_temp))
        content_temp = mc.get("content_model", {}).get("temperature")
        if isinstance(content_temp, (int, float)):
            self._content_temperature.setValue(float(content_temp))

    def _save(self):
        """将界面配置写入配置目录下的 .env 和 config.json"""
        # 始终以当前 config_path 所在目录下的 .env 为准（即使文件尚不存在也允许创建）
        self._env_path = self._derive_env_path()
        env = load_env(self._env_path) if os.path.exists(self._env_path) else {}

        for key, widget in self._fields.items():
            if isinstance(widget, QCheckBox):
                env[key] = "true" if widget.isChecked() else "false"
            elif isinstance(widget, QComboBox):
                env[key] = widget.currentText()
            elif isinstance(widget, QLineEdit):
                env[key] = widget.text().strip()

        save_env(self._env_path, env)

        # 更新 config.json 中的 model_selection
        cfg = load_config(self._config_path)
        gen = cfg.setdefault("generation_config", {})
        ms = gen.setdefault("model_selection", {})
        ms["outline"] = {
            "provider": self._outline_provider.currentText(),
            "model_type": "outline",
        }
        ms["content"] = {
            "provider": self._content_provider.currentText(),
            "model_type": "content",
        }
        # 写入温度覆盖到 model_config（深合并由 Config 加载层处理）
        mc = cfg.setdefault("model_config", {})
        outline_mc = mc.setdefault("outline_model", {})
        outline_mc["temperature"] = round(self._outline_temperature.value(), 4)
        content_mc = mc.setdefault("content_model", {})
        content_mc["temperature"] = round(self._content_temperature.value(), 4)
        save_config(self._config_path, cfg)

        QMessageBox.information(self, self.tr("保存成功"), self.tr("模型配置已保存。"))

    # ── 连接测试 ─────────────────────────────────────────

    def _build_test_config(self, provider: str) -> dict:
        """根据 provider 从当前界面字段组装测试参数"""
        def _val(key: str) -> str:
            w = self._fields.get(key)
            if isinstance(w, QLineEdit):
                return w.text().strip()
            return ""

        if provider == "gemini":
            return {
                "api_key": _val("GEMINI_API_KEY"),
                "timeout": _val("GEMINI_TIMEOUT") or "30",
            }
        if provider == "claude":
            return {
                "api_key": _val("CLAUDE_API_KEY"),
                "timeout": _val("CLAUDE_TIMEOUT") or "30",
            }
        if provider == "openai_embedding":
            return {
                "api_key": _val("OPENAI_EMBEDDING_API_KEY"),
                "base_url": _val("OPENAI_EMBEDDING_API_BASE"),
                "timeout": _val("OPENAI_EMBEDDING_TIMEOUT") or "30",
            }
        if provider == "openai_outline":
            return {
                "api_key": _val("OPENAI_OUTLINE_API_KEY"),
                "base_url": _val("OPENAI_OUTLINE_API_BASE"),
                "timeout": _val("OPENAI_OUTLINE_TIMEOUT") or "30",
            }
        if provider == "openai_content":
            return {
                "api_key": _val("OPENAI_CONTENT_API_KEY"),
                "base_url": _val("OPENAI_CONTENT_API_BASE"),
                "timeout": _val("OPENAI_CONTENT_TIMEOUT") or "30",
            }
        if provider == "fallback":
            return {
                "api_key": _val("FALLBACK_API_KEY"),
                "base_url": _val("FALLBACK_API_BASE"),
                "timeout": "30",
            }
        return {}

    def _on_test(self, provider: str):
        """启动连接测试线程"""
        config = self._build_test_config(provider)
        worker = ConnectionTesterWorker(provider, config, parent=self)
        worker.test_result.connect(self._on_test_result)
        worker.finished.connect(lambda: self._testers.remove(worker))
        self._testers.append(worker)
        worker.start()

    def _on_test_result(self, provider: str, success: bool, message: str):
        """处理测试结果"""
        if success:
            QMessageBox.information(self, self.tr("{0} 测试").format(provider), message)
        else:
            QMessageBox.warning(self, self.tr("{0} 测试").format(provider), message)

    # ── 编辑锁定（保留滚动） ────────────────────────────

    def set_editing_enabled(self, enabled: bool):
        """启用/禁用所有输入控件与关键按钮，但不影响滚动"""
        for widget in self._fields.values():
            widget.setEnabled(enabled)
        self._outline_provider.setEnabled(enabled)
        self._content_provider.setEnabled(enabled)
        # 温度控件
        self._outline_temperature.setEnabled(enabled)
        self._content_temperature.setEnabled(enabled)
        # 锁定加载 / 保存 / 各测试按钮，避免生成过程中改乱磁盘态
        for btn in self._lockable_buttons:
            btn.setEnabled(enabled)

    # ── 关闭清理 ─────────────────────────────────────────

    def shutdown_workers(self, wait_ms: int | None = None):
        """停止并等待所有测试线程结束（主窗口关闭时调用）

        Args:
            wait_ms: 显式等待上限（毫秒）；为 None 时根据各 tester 的 timeout
                     配置自适应为 (timeout + 2) * 1000，避免 3s 强退导致
                     QThread destroyed while running。
        """
        for tester in list(self._testers):
            try:
                # 先发送协作取消信号（供未来分段调用感知）
                stop_fn = getattr(tester, "stop", None)
                if callable(stop_fn):
                    stop_fn()
                if tester.isRunning():
                    if wait_ms is None:
                        try:
                            t = int(tester.config.get("timeout", 30))
                        except (TypeError, ValueError):
                            t = 30
                        effective = (t + 2) * 1000
                    else:
                        effective = wait_ms
                    tester.wait(effective)
            except RuntimeError:
                # QThread 已被销毁，跳过
                pass
        self._testers.clear()

    def changeEvent(self, event):
        """语言切换时更新按钮和分组标题"""
        if event.type() == QEvent.Type.LanguageChange:
            # [5.4] 优先回放 i18n 注册表(覆盖所有 QGroupBox 与 QPushButton)
            try:
                self._i18n_registry.retranslate_all()
            except Exception:
                pass
            # 保留原显式刷新作为关键按钮兜底
            self._btn_load.setText(self.tr("加载配置"))
            self._btn_save.setText(self.tr("保存配置"))
        super().changeEvent(event)
