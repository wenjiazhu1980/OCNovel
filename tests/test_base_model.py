# -*- coding: utf-8 -*-
"""
测试模型基类模块 - BaseModel
"""

import pytest
import numpy as np
from src.models.base_model import BaseModel


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
