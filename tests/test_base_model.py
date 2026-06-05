# -*- coding: utf-8 -*-
"""
测试模型基类模块 - BaseModel
"""

import numpy as np
import pytest
from src.models.base_model import (
    BaseModel,
    DEFAULT_MAX_PROMPT_LENGTH,
    truncate_prompt_preserving_ends,
)


class ConcreteModel(BaseModel):
    """用于测试的具体实现"""

    def generate(self, prompt, max_tokens=None, **kwargs):
        return f"response to: {prompt[:20]}"

    def embed(self, text):
        return np.ones(128, dtype="float32")


class TestBaseModel:
    """BaseModel 测试"""

    def test_init(self):
        config = {"api_key": "test-key", "model_name": "test-model"}
        model = ConcreteModel(config)
        assert model.api_key == "test-key"
        assert model.model_name == "test-model"

    def test_init_defaults(self):
        model = ConcreteModel({})
        assert model.api_key == ""
        assert model.model_name == ""

    def test_validate_config_missing_api_key(self):
        model = ConcreteModel({"model_name": "test"})
        with pytest.raises(ValueError, match="API key"):
            model._validate_config()

    def test_validate_config_missing_model_name(self):
        model = ConcreteModel({"api_key": "key"})
        with pytest.raises(ValueError, match="Model name"):
            model._validate_config()

    def test_validate_config_success(self):
        model = ConcreteModel({"api_key": "key", "model_name": "model"})
        assert model._validate_config() is True

    def test_generate(self):
        model = ConcreteModel({"api_key": "k", "model_name": "m"})
        result = model.generate("hello world")
        assert "response to" in result

    def test_embed(self):
        model = ConcreteModel({"api_key": "k", "model_name": "m"})
        result = model.embed("test text")
        assert isinstance(result, np.ndarray)
        assert len(result) == 128

    def test_close(self):
        model = ConcreteModel({"api_key": "k", "model_name": "m"})
        model.close()  # 不应抛出异常

    def test_abstract_methods_enforced(self):
        """不能直接实例化 BaseModel"""
        with pytest.raises(TypeError):
            BaseModel({"api_key": "k", "model_name": "m"})


class TestTruncatePromptPreservingEnds:
    """保首尾智能截断：超长 prompt 保留头部指令与尾部输出格式，省略中间。"""

    def test_default_max_prompt_length_is_190000(self):
        assert DEFAULT_MAX_PROMPT_LENGTH == 190000

    def test_short_prompt_unchanged(self):
        p = "短内容不需要截断"
        assert truncate_prompt_preserving_ends(p, 1000) == p

    def test_exact_boundary_unchanged(self):
        p = "z" * 100
        assert truncate_prompt_preserving_ends(p, 100) == p

    def test_preserves_head_and_tail(self):
        head = "【系统指令】你是大纲编辑，必须遵守以下要求。"
        tail = "【输出格式】只输出 JSON，不要解释。"
        prompt = head + ("中间参考资料" * 5000) + tail
        out = truncate_prompt_preserving_ends(prompt, 2000)
        assert len(out) <= 2000
        # 旧实现 prompt[:max] 会丢掉 tail；保首尾应同时保住两端
        assert out.startswith("【系统指令】")
        assert out.endswith("不要解释。")
        assert "省略" in out

    def test_respects_max_length(self):
        out = truncate_prompt_preserving_ends("x" * 200000, DEFAULT_MAX_PROMPT_LENGTH)
        assert len(out) <= DEFAULT_MAX_PROMPT_LENGTH

    def test_tiny_max_falls_back_to_head(self):
        out = truncate_prompt_preserving_ends("y" * 1000, 20)
        assert len(out) <= 20
