"""Tab1: 模型配置面板"""
import os
from functools import partial
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QLineEdit, QComboBox, QCheckBox, QLabel,
    QPushButton, QScrollArea, QMessageBox,
)

from ..utils.config_io import load_env, save_env, load_config, save_config
from ..workers.connection_tester import ConnectionTesterWorker

# 提供商选项（已移除火山引擎，统一使用大纲/内容模型配置）
PROVIDERS = ["gemini", "openai"]


class ModelConfigTab(QWidget):
    """模型配置 Tab"""

    def __init__(self, env_path: str, config_path: str, parent=None):
        super().__init__(parent)
        self._env_path = env_path
        self._config_path = config_path
        self._fields: dict[str, QWidget] = {}  # env_key -> widget
        self._testers: list[ConnectionTesterWorker] = []

        self._init_ui()
        self._load(silent=True)

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
            '免费获取 API Key：'
            '<a href="https://cloud.siliconflow.cn/i/VFtAog0M">注册硅基流动账号</a>'
            '（注册即送额度，支持 Qwen / DeepSeek 等开源模型）'
        )
        tip.setOpenExternalLinks(True)
        tip.setWordWrap(True)
        self._layout.addWidget(tip)

        self._build_gemini_group()
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
        btn_load = QPushButton("加载配置")
        btn_save = QPushButton("保存配置")
        btn_save.setProperty("cssClass", "primary")
        btn_load.clicked.connect(self._load)
        btn_save.clicked.connect(self._save)
        btn_bar.addWidget(btn_load)
        btn_bar.addWidget(btn_save)
        outer.addLayout(btn_bar)

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

    def _make_group(self, title: str, provider_key: str | None = None):
        """创建 QGroupBox + QFormLayout，可选附带测试按钮"""
        group = QGroupBox(title)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        group.setLayout(form)
        self._layout.addWidget(group)
        return group, form

    def _add_test_button(self, form: QFormLayout, provider_key: str):
        """在表单末尾添加测试连接按钮"""
        btn = QPushButton("测试连接")
        btn.setFixedWidth(120)
        btn.setProperty("cssClass", "primary")
        btn.clicked.connect(partial(self._on_test, provider_key))
        form.addRow("", btn)
        return btn

    def _build_gemini_group(self):
        _, form = self._make_group("Gemini (仅支持 Google 官方 API)")
        self._add_field(form, "API Key", "GEMINI_API_KEY", echo_password=True)
        self._add_field(form, "大纲模型 ID", "GEMINI_OUTLINE_MODEL",
                        placeholder="gemini-2.5-pro")
        self._add_field(form, "内容模型 ID", "GEMINI_CONTENT_MODEL",
                        placeholder="gemini-2.5-flash")
        self._add_field(form, "超时 (秒)", "GEMINI_TIMEOUT", placeholder="300")
        self._add_field(form, "最大重试", "GEMINI_MAX_RETRIES", placeholder="3")
        self._add_field(form, "重试延迟 (秒)", "GEMINI_RETRY_DELAY", placeholder="90")
        self._add_test_button(form, "gemini")

    def _build_openai_embedding_group(self):
        _, form = self._make_group("OpenAI Embedding")
        self._add_field(form, "API Key", "OPENAI_EMBEDDING_API_KEY", echo_password=True)
        self._add_field(form, "Base URL", "OPENAI_EMBEDDING_API_BASE",
                        placeholder="https://api.siliconflow.cn/v1")
        self._add_field(form, "模型名称", "OPENAI_EMBEDDING_MODEL")
        self._add_field(form, "超时 (秒)", "OPENAI_EMBEDDING_TIMEOUT", placeholder="60")
        self._add_test_button(form, "openai_embedding")

    def _build_reranker_group(self):
        _, form = self._make_group("Reranker（复用 Embedding 的 API Key / Base URL）")
        self._add_field(form, "模型名称", "OPENAI_RERANKER_MODEL",
                        placeholder="Qwen/Qwen3-Reranker-0.6B")
        cb = QCheckBox("启用 FP16")
        cb.setChecked(True)
        form.addRow("精度", cb)
        self._fields["OPENAI_RERANKER_USE_FP16"] = cb

    def _build_outline_model_group(self):
        _, form = self._make_group("大纲模型")
        self._add_field(form, "API Key", "OPENAI_OUTLINE_API_KEY", echo_password=True)
        self._add_field(form, "Base URL", "OPENAI_OUTLINE_API_BASE",
                        placeholder="https://api.siliconflow.cn/v1")
        self._add_field(form, "API 模式", "OPENAI_OUTLINE_API_MODE",
                        placeholder="auto (自动) / chat (Chat Completions) / responses (Responses API)")
        self._add_field(form, "模型名称", "OPENAI_OUTLINE_MODEL",
                        placeholder="Qwen/Qwen2.5-7B-Instruct")
        self._add_field(form, "超时 (秒)", "OPENAI_OUTLINE_TIMEOUT", placeholder="120")
        # 推理（Reasoning）设置
        cb = QCheckBox("启用推理（Thinking/Reasoning）")
        form.addRow("", cb)
        self._fields["OPENAI_OUTLINE_REASONING_ENABLED"] = cb
        self._add_test_button(form, "openai_outline")

    def _build_content_model_group(self):
        _, form = self._make_group("内容模型")
        self._add_field(form, "API Key", "OPENAI_CONTENT_API_KEY", echo_password=True)
        self._add_field(form, "Base URL", "OPENAI_CONTENT_API_BASE",
                        placeholder="https://api.siliconflow.cn/v1")
        self._add_field(form, "API 模式", "OPENAI_CONTENT_API_MODE",
                        placeholder="auto (自动) / chat (Chat Completions) / responses (Responses API)")
        self._add_field(form, "模型名称", "OPENAI_CONTENT_MODEL",
                        placeholder="Qwen/Qwen2.5-7B-Instruct")
        self._add_field(form, "超时 (秒)", "OPENAI_CONTENT_TIMEOUT", placeholder="180")
        # 推理（Reasoning）设置
        cb = QCheckBox("启用推理（Thinking/Reasoning）")
        form.addRow("", cb)
        self._fields["OPENAI_CONTENT_REASONING_ENABLED"] = cb
        self._add_test_button(form, "openai_content")

    def _build_fallback_group(self):
        _, form = self._make_group("备用模型 (Fallback)")
        self._add_field(form, "API Key", "FALLBACK_API_KEY", echo_password=True)
        self._add_field(form, "Base URL", "FALLBACK_API_BASE",
                        placeholder="https://api.siliconflow.cn/v1")
        self._add_field(form, "模型 ID", "FALLBACK_MODEL_ID",
                        placeholder="Qwen/Qwen2.5-7B-Instruct")
        self._add_test_button(form, "fallback")

    def _build_model_selection_group(self):
        group = QGroupBox("模型选择")
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        group.setLayout(form)

        self._outline_provider = QComboBox()
        self._outline_provider.addItems(PROVIDERS)
        form.addRow("大纲生成提供商", self._outline_provider)

        self._content_provider = QComboBox()
        self._content_provider.addItems(PROVIDERS)
        form.addRow("内容生成提供商", self._content_provider)

        self._layout.addWidget(group)

    # ── 路径切换 + 重新加载 ────────────────────────────

    def set_config_path(self, path: str):
        self._config_path = path

    def set_env_path(self, path: str):
        self._env_path = path

    def reload(self):
        self._load()

    # ── 加载 / 保存 ─────────────────────────────────────

    def _load(self, silent: bool = False):
        """从 .env 和 config.json 加载配置到界面"""
        if not os.path.exists(self._env_path):
            if not silent:
                QMessageBox.warning(self, "文件不存在",
                                    f".env 文件不存在:\n{self._env_path}\n\n请通过菜单「文件 → 打开 .env 文件」选择正确路径。")
            return
        env = load_env(self._env_path)

        for key, widget in self._fields.items():
            if isinstance(widget, QCheckBox):
                widget.setChecked(env.get(key, "true").lower() == "true")
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

    def _save(self):
        """将界面配置写入 .env 和 config.json"""
        env = load_env(self._env_path)

        for key, widget in self._fields.items():
            if isinstance(widget, QCheckBox):
                env[key] = "true" if widget.isChecked() else "false"
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
        save_config(self._config_path, cfg)

        QMessageBox.information(self, "保存成功", "模型配置已保存。")

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
            QMessageBox.information(self, f"{provider} 测试", message)
        else:
            QMessageBox.warning(self, f"{provider} 测试", message)

    # ── 编辑锁定（保留滚动） ────────────────────────────

    def set_editing_enabled(self, enabled: bool):
        """启用/禁用所有输入控件，但不影响滚动"""
        for widget in self._fields.values():
            widget.setEnabled(enabled)
        self._outline_provider.setEnabled(enabled)
        self._content_provider.setEnabled(enabled)
