# -*- coding: utf-8 -*-
"""
测试 fallback 模型兜底逻辑
覆盖：配置读取、触发条件、认证错误提前终止、Gemini/OpenAI 双模型
"""

import os
import pytest
from unittest.mock import patch, MagicMock, PropertyMock


# ---------------------------------------------------------------------------
# OpenAIModel fallback 测试
# ---------------------------------------------------------------------------
class TestOpenAIModelFallbackConfig:
    """测试 OpenAIModel 的 fallback 配置读取"""

    def test_fallback_from_config_dict(self):
        """当 config 中包含 fallback 配置时，应优先使用"""
        from src.models.openai_model import OpenAIModel

        config = {
            "api_key": "test-key",
            "base_url": "https://api.test.com",
            "model_name": "gpt-4o",
            "temperature": 0.7,
            "fallback_enabled": True,
            "fallback_api_key": "fb-key-123",
            "fallback_base_url": "https://fallback.api.com/v1",
            "fallback_model": "Qwen/Qwen2.5-7B-Instruct",
            "fallback_api_mode": "chat",
        }
        model = OpenAIModel(config)
        assert model.fallback_api_key == "fb-key-123"
        assert model.fallback_base_url == "https://fallback.api.com/v1"
        assert model.fallback_model_name == "Qwen/Qwen2.5-7B-Instruct"
        assert model.fallback_api_mode == "chat"

    def test_fallback_disabled_falls_back_to_env(self):
        """当 fallback_enabled=False 时，回退到环境变量"""
        from src.models.openai_model import OpenAIModel

        config = {
            "api_key": "test-key",
            "base_url": "https://api.test.com",
            "model_name": "gpt-4o",
            "temperature": 0.7,
            "fallback_enabled": False,
        }
        with patch.dict(os.environ, {
            "FALLBACK_API_KEY": "env-key",
            "FALLBACK_API_BASE": "https://env.api.com/v1",
            "FALLBACK_MODEL_ID": "env-model",
            "FALLBACK_API_MODE": "responses",
        }):
            model = OpenAIModel(config)
            assert model.fallback_api_key == "env-key"
            assert model.fallback_base_url == "https://env.api.com/v1"
            assert model.fallback_model_name == "env-model"
            assert model.fallback_api_mode == "responses"

    def test_no_hardcoded_model_name_matching(self):
        """不论主模型名称如何，fallback 模型都从配置读取，不做硬编码匹配"""
        from src.models.openai_model import OpenAIModel

        for model_name in ["gemini-2.5-flash", "gemini-2.5-pro", "gpt-4o", "custom-model"]:
            config = {
                "api_key": "test-key",
                "base_url": "https://api.test.com",
                "model_name": model_name,
                "temperature": 0.7,
                "fallback_enabled": True,
                "fallback_api_key": "fb-key",
                "fallback_base_url": "https://fb.com/v1",
                "fallback_model": "unified-fallback-model",
                "fallback_api_mode": "auto",
            }
            model = OpenAIModel(config)
            assert model.fallback_model_name == "unified-fallback-model", \
                f"模型 {model_name} 的 fallback 应该统一为 unified-fallback-model"
            assert model.fallback_api_mode == "auto"


class TestOpenAIModelFallbackTrigger:
    """测试 OpenAIModel fallback 触发条件"""

    def _make_model(self):
        from src.models.openai_model import OpenAIModel
        config = {
            "api_key": "test-key",
            "base_url": "https://api.test.com",
            "model_name": "gpt-4o",
            "temperature": 0.7,
            "fallback_enabled": True,
            "fallback_api_key": "fb-key",
            "fallback_base_url": "https://fb.com/v1",
            "fallback_model": "fb-model",
            "fallback_api_mode": "chat",
        }
        return OpenAIModel(config)

    @pytest.mark.parametrize("error_msg", [
        "Error code: 401 - 该令牌状态不可用",
        "Error code: 403 - Forbidden",
        "Unauthorized access",
        "Error code: 429 - Rate limit exceeded",
        "Error code: 500 - Internal Server Error",
        "Error code: 502 - Bad Gateway",
        "Error code: 503 - Service Unavailable",
        "Connection timeout after 60s",
        "Server is overloaded",
    ])
    def test_should_trigger_fallback_on_errors(self, error_msg):
        """各类服务端/认证错误应触发 fallback"""
        model = self._make_model()

        fallback_content = "fallback 生成的内容"

        with patch.object(model, '_generate_with_compatible_api') as mock_api:
            # 第一次调用（主模型）抛出错误，第二次（fallback）返回内容
            mock_api.side_effect = [Exception(error_msg), fallback_content]
            with patch.object(model, '_create_fallback_client', return_value=MagicMock()):
                result = model._generate_once("test prompt")
                assert result == fallback_content

    def test_should_not_trigger_fallback_without_key(self):
        """没有 fallback_api_key 时不触发 fallback"""
        from src.models.openai_model import OpenAIModel
        config = {
            "api_key": "test-key",
            "base_url": "https://api.test.com",
            "model_name": "gpt-4o",
            "temperature": 0.7,
            "fallback_enabled": False,
        }
        with patch.dict(os.environ, {"FALLBACK_API_KEY": ""}, clear=False):
            model = OpenAIModel(config)

        with patch.object(model, '_generate_with_compatible_api',
                          side_effect=Exception("Error code: 500")):
            with pytest.raises(Exception, match="OpenAI generation error"):
                model._generate_once("test prompt")

    def test_fallback_api_mode_is_used(self):
        """测试 fallback_api_mode 在调用时被正确传递"""
        from src.models.openai_model import OpenAIModel
        config = {
            "api_key": "test-key",
            "base_url": "https://api.test.com",
            "model_name": "gpt-4o",
            "temperature": 0.7,
            "fallback_enabled": True,
            "fallback_api_key": "fb-key",
            "fallback_base_url": "https://fb.com/v1",
            "fallback_model": "fb-model",
            "fallback_api_mode": "responses",
        }
        model = OpenAIModel(config)

        with patch.object(model, '_generate_with_compatible_api') as mock_api:
            # 第一次调用（主模型）抛出错误，第二次（fallback）返回内容
            mock_api.side_effect = [Exception("Error code: 500"), "fallback content"]
            with patch.object(model, '_create_fallback_client', return_value=MagicMock()):
                result = model._generate_once("test prompt")
                assert result == "fallback content"

                # 验证第二次调用（fallback）使用了正确的 api_mode
                assert mock_api.call_count == 2
                fallback_call = mock_api.call_args_list[1]
                assert fallback_call[1]['api_mode'] == "responses"


class TestOpenAIModelEarlyTermination:
    """测试认证错误时 generate() 提前终止重试"""

    def test_auth_error_stops_retry_immediately(self):
        """401 错误应立即终止重试循环，不做5次重试"""
        from src.models.openai_model import OpenAIModel
        config = {
            "api_key": "test-key",
            "base_url": "https://api.test.com",
            "model_name": "gpt-4o",
            "temperature": 0.7,
            "fallback_enabled": True,
            "fallback_api_key": "fb-key",
            "fallback_base_url": "https://fb.com/v1",
            "fallback_model": "fb-model",
            "fallback_api_mode": "auto",
        }
        model = OpenAIModel(config)

        call_count = 0

        def mock_generate_once(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise Exception("Error code: 401 - 该令牌状态不可用")

        with patch.object(model, '_generate_once', side_effect=mock_generate_once):
            with pytest.raises(Exception, match="401"):
                model.generate("test prompt")

        # 应该只调用1次就终止，不是5次
        assert call_count == 1

    def test_server_error_retries_multiple_times(self):
        """500 错误应正常重试多次"""
        from src.models.openai_model import OpenAIModel
        config = {
            "api_key": "test-key",
            "base_url": "https://api.test.com",
            "model_name": "gpt-4o",
            "temperature": 0.7,
        }
        model = OpenAIModel(config)

        call_count = 0

        def mock_generate_once(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise Exception("Error code: 500 - Internal Server Error")

        with patch.object(model, '_generate_once', side_effect=mock_generate_once):
            with pytest.raises(Exception, match="500"):
                model.generate("test prompt")

        # 应该重试5次
        assert call_count == 5


# ---------------------------------------------------------------------------
# GeminiModel fallback 测试
# ---------------------------------------------------------------------------
class TestGeminiModelFallbackConfig:
    """测试 GeminiModel 的 fallback 配置读取"""

    def _make_gemini_model(self, extra_config=None):
        """创建一个 mock 的 GeminiModel，绕过 genai 初始化"""
        config = {
            "type": "gemini",
            "api_key": "test-gemini-key",
            "model_name": "gemini-2.5-flash",
            "temperature": 0.7,
            "retry_delay": 1,
            "max_retries": 3,
            "max_input_length": 500000,
            "timeout": 60,
            "fallback_enabled": True,
            "fallback_api_key": "fb-key",
            "fallback_base_url": "https://fb.com/v1",
            "fallback_model": "Qwen/Qwen2.5-7B-Instruct",
        }
        if extra_config:
            config.update(extra_config)

        with patch('google.generativeai.configure'), \
             patch('google.generativeai.GenerativeModel'), \
             patch('src.models.gemini_model.GeminiModel._validate_config'):
            from src.models.gemini_model import GeminiModel
            model = GeminiModel(config)
        return model

    def test_fallback_uses_config_model(self):
        """fallback 模型名应从 config['fallback_model'] 读取"""
        model = self._make_gemini_model()
        assert model.fallback_model_name == "Qwen/Qwen2.5-7B-Instruct"
        assert model.fallback_api_key == "fb-key"
        assert model.fallback_base_url == "https://fb.com/v1"

    def test_no_model_name_matching(self):
        """不论 flash/pro，fallback 都用同一个配置模型"""
        for model_name in ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-3-flash-preview"]:
            model = self._make_gemini_model({"model_name": model_name})
            assert model.fallback_model_name == "Qwen/Qwen2.5-7B-Instruct"

    def test_fallback_disabled(self):
        """fallback_enabled=False 时禁用备用模型"""
        model = self._make_gemini_model({"fallback_enabled": False})
        assert model.fallback_api_key == ""
        assert model.fallback_model_name == ""


class TestGeminiModelFallbackTrigger:
    """测试 GeminiModel 认证错误提前终止 + fallback 触发"""

    def _make_gemini_model(self):
        config = {
            "type": "gemini",
            "api_key": "test-gemini-key",
            "model_name": "gemini-2.5-flash",
            "temperature": 0.7,
            "retry_delay": 0,  # 不等待
            "max_retries": 5,
            "max_input_length": 500000,
            "timeout": 60,
            "fallback_enabled": True,
            "fallback_api_key": "fb-key",
            "fallback_base_url": "https://fb.com/v1",
            "fallback_timeout": 120,
            "fallback_model": "fb-model",
        }

        with patch('google.generativeai.configure'), \
             patch('google.generativeai.GenerativeModel'), \
             patch('src.models.gemini_model.GeminiModel._validate_config'):
            from src.models.gemini_model import GeminiModel
            model = GeminiModel(config)
        return model

    def test_auth_error_breaks_retry_and_triggers_fallback(self):
        """401 错误应立即终止重试并触发 fallback"""
        model = self._make_gemini_model()

        gemini_call_count = 0

        def mock_generate_content(*args, **kwargs):
            nonlocal gemini_call_count
            gemini_call_count += 1
            raise Exception("Error code: 401 - Unauthorized")

        model.model.generate_content = mock_generate_content

        with patch.object(model, '_generate_with_compatible_api', return_value="fallback content"):
            with patch('src.models.gemini_model.OpenAI', create=True) as mock_openai_cls:
                mock_openai_cls.return_value = MagicMock()
                result = model.generate("test prompt")

        # Gemini 只调用1次就跳出
        assert gemini_call_count == 1
        assert result == "fallback content"

    def test_server_error_retries_then_fallback(self):
        """500 错误应重试 max_retries 次后再 fallback"""
        model = self._make_gemini_model()

        gemini_call_count = 0

        def mock_generate_content(*args, **kwargs):
            nonlocal gemini_call_count
            gemini_call_count += 1
            raise Exception("Error code: 500 - Internal Server Error")

        model.model.generate_content = mock_generate_content

        with patch.object(model, '_generate_with_compatible_api', return_value="fallback content"):
            with patch('src.models.gemini_model.OpenAI', create=True) as mock_openai_cls:
                mock_openai_cls.return_value = MagicMock()
                result = model.generate("test prompt")

        # 应该重试5次后才 fallback
        assert gemini_call_count == 5
        assert result == "fallback content"

    def test_all_models_fail_raises(self):
        """主模型和 fallback 都失败时应抛出异常"""
        model = self._make_gemini_model()

        model.model.generate_content = MagicMock(
            side_effect=Exception("Error code: 401 - Unauthorized")
        )

        with patch.object(model, '_generate_with_compatible_api',
                          side_effect=Exception("fallback also failed")):
            with patch('src.models.gemini_model.OpenAI', create=True) as mock_openai_cls:
                mock_openai_cls.return_value = MagicMock()
                with pytest.raises(Exception, match="All models failed"):
                    model.generate("test prompt")


# ---------------------------------------------------------------------------
# AIConfig fallback 配置传递测试
# ---------------------------------------------------------------------------
class TestAIConfigFallbackPropagation:
    """测试 AIConfig 将 fallback 配置正确传递给 OpenAI/Gemini 模型"""

    def test_get_openai_config_includes_fallback(self):
        """get_openai_config 应包含 fallback 配置"""
        with patch.dict(os.environ, {
            "GEMINI_API_KEY": "gk",
            "GEMINI_FALLBACK_ENABLED": "True",
            "FALLBACK_API_KEY": "fb-key",
            "OPENAI_OUTLINE_API_KEY": "ok",
            "OPENAI_OUTLINE_API_BASE": "https://api.test.com",
        }, clear=False):
            from src.config.ai_config import AIConfig
            ai_config = AIConfig()
            config = ai_config.get_openai_config("outline")

            assert config["fallback_enabled"] is True
            assert config["fallback_api_key"] == "fb-key"
            assert "fallback_model" in config

    def test_get_gemini_config_includes_fallback_model(self):
        """get_gemini_config 应包含 fallback_model 字段"""
        with patch.dict(os.environ, {
            "GEMINI_API_KEY": "gk",
            "GEMINI_FALLBACK_ENABLED": "True",
            "FALLBACK_API_KEY": "fb-key",
        }, clear=False):
            from src.config.ai_config import AIConfig
            ai_config = AIConfig()
            config = ai_config.get_gemini_config("content")

            assert config["fallback_enabled"] is True
            assert "fallback_model" in config
            # 不应再有 fallback_models（旧字段）
            assert "fallback_models" not in config

    def test_fallback_disabled_propagation(self):
        """fallback 禁用时，config 中 fallback_enabled=False"""
        with patch.dict(os.environ, {
            "GEMINI_API_KEY": "gk",
            "GEMINI_FALLBACK_ENABLED": "False",
            "OPENAI_FALLBACK_ENABLED": "False",
            "OPENAI_OUTLINE_API_KEY": "ok",
            "OPENAI_OUTLINE_API_BASE": "https://api.test.com",
        }, clear=False):
            from src.config.ai_config import AIConfig
            ai_config = AIConfig()

            gemini_config = ai_config.get_gemini_config("content")
            assert gemini_config["fallback_enabled"] is False

            openai_config = ai_config.get_openai_config("outline")
            assert openai_config["fallback_enabled"] is False
