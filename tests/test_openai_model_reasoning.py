# -*- coding: utf-8 -*-
"""
测试 OpenAIModel 推理模型兼容性
验证 temperature / top_p 参数对推理模型的自动清理逻辑
"""

import pytest
from src.models.openai_model import OpenAIModel


class TestReasoningModelCompatibility:
    """推理模型兼容性测试"""

    def test_is_sampling_restricted_o1_series(self):
        """测试 o1 系列推理模型检测"""
        assert OpenAIModel._is_sampling_restricted("o1") is True
        assert OpenAIModel._is_sampling_restricted("o1-mini") is True
        assert OpenAIModel._is_sampling_restricted("o1-preview") is True
        assert OpenAIModel._is_sampling_restricted("O1-MINI") is True  # 大小写不敏感

    def test_is_sampling_restricted_o3_series(self):
        """测试 o3 系列推理模型检测"""
        assert OpenAIModel._is_sampling_restricted("o3") is True
        assert OpenAIModel._is_sampling_restricted("o3-mini") is True
        assert OpenAIModel._is_sampling_restricted("o3-pro") is True

    def test_is_sampling_restricted_o4_series(self):
        """测试 o4 系列推理模型检测"""
        assert OpenAIModel._is_sampling_restricted("o4-mini") is True

    def test_is_sampling_restricted_gpt5_series(self):
        """测试 GPT-5 及以上推理模型检测"""
        assert OpenAIModel._is_sampling_restricted("gpt-5") is True
        assert OpenAIModel._is_sampling_restricted("gpt-5-mini") is True
        assert OpenAIModel._is_sampling_restricted("gpt-5.2") is True
        assert OpenAIModel._is_sampling_restricted("gpt-5.3-chat-latest") is True
        assert OpenAIModel._is_sampling_restricted("GPT-5") is True  # 大小写不敏感

    def test_is_sampling_restricted_traditional_models(self):
        """测试传统模型不被误判为推理模型"""
        assert OpenAIModel._is_sampling_restricted("gpt-4o") is False
        assert OpenAIModel._is_sampling_restricted("gpt-4.1") is False
        assert OpenAIModel._is_sampling_restricted("gpt-4-turbo") is False
        assert OpenAIModel._is_sampling_restricted("gpt-3.5-turbo") is False
        assert OpenAIModel._is_sampling_restricted("Qwen/Qwen2.5-7B-Instruct") is False
        assert OpenAIModel._is_sampling_restricted("deepseek-ai/DeepSeek-V3") is False
        assert OpenAIModel._is_sampling_restricted("gemini-2.5-flash") is False

    def test_sanitize_sampling_params_reasoning_model(self):
        """测试推理模型的采样参数清理"""
        config = {
            "api_key": "test-key",
            "base_url": "https://api.test.com",
            "model_name": "o3-mini",
            "temperature": 0.7
        }
        model = OpenAIModel(config)

        # 推理模型应该忽略传入的 temperature 和 top_p
        temp, top_p = model._sanitize_sampling_params("o3-mini", 1.0, 0.9)
        assert temp == 1.0
        assert top_p is None

        temp, top_p = model._sanitize_sampling_params("gpt-5", 0.5, 0.8)
        assert temp == 1.0
        assert top_p is None

    def test_sanitize_sampling_params_traditional_model(self):
        """测试传统模型的采样参数保持不变"""
        config = {
            "api_key": "test-key",
            "base_url": "https://api.test.com",
            "model_name": "gpt-4o",
            "temperature": 0.7
        }
        model = OpenAIModel(config)

        # 传统模型应该保留传入的参数
        temp, top_p = model._sanitize_sampling_params("gpt-4o", 1.0, 0.9)
        assert temp == 1.0
        assert top_p == 0.9

        temp, top_p = model._sanitize_sampling_params("Qwen/Qwen2.5-7B-Instruct", 0.5, 0.8)
        assert temp == 0.5
        assert top_p == 0.8

    def test_sanitize_sampling_params_none_top_p(self):
        """测试 top_p 为 None 的情况"""
        config = {
            "api_key": "test-key",
            "base_url": "https://api.test.com",
            "model_name": "gpt-4o",
            "temperature": 0.7
        }
        model = OpenAIModel(config)

        # top_p 为 None 应该保持 None
        temp, top_p = model._sanitize_sampling_params("gpt-4o", 0.7, None)
        assert temp == 0.7
        assert top_p is None

    def test_generate_with_kwargs_reasoning_model(self):
        """测试通过 kwargs 传递参数给推理模型（集成测试的模拟）"""
        config = {
            "api_key": "test-key",
            "base_url": "https://api.test.com",
            "model_name": "o3-mini",
            "temperature": 0.7
        }
        model = OpenAIModel(config)

        # 模拟 _generate_once 中的参数处理逻辑
        kwargs = {"temperature": 1.0, "top_p": 0.9}
        temperature = kwargs.get("temperature", 0.7)
        top_p = kwargs.get("top_p", None)
        temperature, top_p = model._sanitize_sampling_params(model.model_name, temperature, top_p)

        # 推理模型应该清理参数
        assert temperature == 1.0
        assert top_p is None

    def test_generate_with_kwargs_traditional_model(self):
        """测试通过 kwargs 传递参数给传统模型（集成测试的模拟）"""
        config = {
            "api_key": "test-key",
            "base_url": "https://api.test.com",
            "model_name": "gpt-4o",
            "temperature": 0.7
        }
        model = OpenAIModel(config)

        # 模拟 _generate_once 中的参数处理逻辑
        kwargs = {"temperature": 1.0, "top_p": 0.9}
        temperature = kwargs.get("temperature", 0.7)
        top_p = kwargs.get("top_p", None)
        temperature, top_p = model._sanitize_sampling_params(model.model_name, temperature, top_p)

        # 传统模型应该保留参数
        assert temperature == 1.0
        assert top_p == 0.9
