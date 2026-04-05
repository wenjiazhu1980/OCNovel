"""模型连接测试后台线程"""
from PySide6.QtCore import QThread, Signal


class ConnectionTesterWorker(QThread):
    """测试模型连接的后台线程"""

    # (provider_name, success, message)
    test_result = Signal(str, bool, str)

    def __init__(self, provider: str, config: dict, parent=None):
        """
        Args:
            provider: 提供商标识，如 "gemini", "openai_embedding", "openai_outline",
                      "openai_content", "fallback"
            config: 连接参数字典，包含 api_key, base_url, model_name 等
        """
        super().__init__(parent)
        self.provider = provider
        self.config = config

    def run(self):
        try:
            if self.provider == "gemini":
                self._test_gemini()
            elif self.provider == "claude":
                self._test_claude()
            else:
                # OpenAI 兼容接口（openai_*, fallback）
                self._test_openai_compatible()
        except Exception as e:
            self.test_result.emit(self.provider, False, f"连接失败: {e}")

    def _test_gemini(self):
        """测试 Gemini 官方 API 连接"""
        import google.generativeai as genai

        api_key = self.config.get("api_key", "").strip()
        if not api_key:
            self.test_result.emit(self.provider, False, "API Key 为空")
            return

        timeout = int(self.config.get("timeout", 30))

        try:
            genai.configure(api_key=api_key, transport="rest")

            # 尝试列出模型以验证连接
            models = list(genai.list_models())
            if models:
                self.test_result.emit(
                    self.provider, True,
                    f"连接成功，可用模型 {len(models)} 个"
                )
            else:
                self.test_result.emit(self.provider, True, "连接成功，但未获取到模型列表")
        except Exception as e:
            self.test_result.emit(self.provider, False, f"连接失败: {e}")

    def _test_claude(self):
        """测试 Claude (Anthropic) API 连接"""
        from anthropic import Anthropic

        api_key = self.config.get("api_key", "").strip()
        if not api_key:
            self.test_result.emit(self.provider, False, "API Key 为空")
            return

        timeout = int(self.config.get("timeout", 30))

        try:
            client = Anthropic(
                api_key=api_key,
                timeout=timeout,
                max_retries=0
            )

            # 发送简单的测试请求
            response = client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=10,
                messages=[{"role": "user", "content": "Hi"}]
            )

            if response.content:
                self.test_result.emit(
                    self.provider, True,
                    "连接成功，API 响应正常"
                )
            else:
                self.test_result.emit(self.provider, True, "连接成功，但响应为空")
        except Exception as e:
            self.test_result.emit(self.provider, False, f"连接失败: {e}")

    def _test_openai_compatible(self):
        """测试 OpenAI 兼容 API 连接"""
        import openai

        api_key = self.config.get("api_key", "").strip()
        base_url = self.config.get("base_url", "").strip()

        if not api_key:
            self.test_result.emit(self.provider, False, "API Key 为空")
            return
        if not base_url:
            self.test_result.emit(self.provider, False, "Base URL 为空")
            return

        timeout = int(self.config.get("timeout", 30))
        client = openai.OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )

        # 尝试列出模型以验证连接
        resp = client.models.list()
        model_count = len(list(resp))
        self.test_result.emit(
            self.provider, True,
            f"连接成功，可用模型 {model_count} 个"
        )
