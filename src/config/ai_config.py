import os
from typing import Dict, Any
from dotenv import load_dotenv

class AIConfig:
    """AI模型配置管理类"""

    def __init__(self):
        # 环境变量应由 Config 类统一加载，这里仅作兜底
        load_dotenv(override=False)

        # 安全的类型转换辅助函数
        def _safe_float(value: str, default: float) -> float:
            """安全地将字符串转换为 float，空字符串返回默认值"""
            if not value or not value.strip():
                return default
            try:
                return float(value)
            except (ValueError, TypeError):
                return default

        def _safe_int(value: str, default: int) -> int:
            """安全地将字符串转换为 int，空字符串返回默认值"""
            if not value or not value.strip():
                return default
            try:
                return int(value)
            except (ValueError, TypeError):
                return default

        # OpenAI 配置（提前定义）
        self.openai_config = {
            "retry_delay": _safe_float(os.getenv("OPENAI_RETRY_DELAY", "10"), 10.0),  # 默认 10 秒
            "models": {
                "embedding": {
                    "name": os.getenv("OPENAI_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B"),
                    "dimension": 1024,
                    "api_key": os.getenv("OPENAI_EMBEDDING_API_KEY", ""),
                    "base_url": os.getenv("OPENAI_EMBEDDING_API_BASE", "https://api.siliconflow.cn/v1"),
                    "api_mode": os.getenv("OPENAI_EMBEDDING_API_MODE", os.getenv("OPENAI_API_MODE", "auto")).lower(),
                    "timeout": _safe_int(os.getenv("OPENAI_EMBEDDING_TIMEOUT", "60"), 60)
                },
                "outline": {
                    "name": os.getenv("OPENAI_OUTLINE_MODEL", "Qwen/Qwen2.5-7B-Instruct"),
                    "temperature": 1.0,
                    "api_key": os.getenv("OPENAI_OUTLINE_API_KEY", ""),
                    "base_url": os.getenv("OPENAI_OUTLINE_API_BASE", "https://api.siliconflow.cn/v1"),
                    "api_mode": os.getenv("OPENAI_OUTLINE_API_MODE", os.getenv("OPENAI_API_MODE", "auto")).lower(),
                    "timeout": _safe_int(os.getenv("OPENAI_OUTLINE_TIMEOUT", "300"), 300),
                    "reasoning_enabled": os.getenv("OPENAI_OUTLINE_REASONING_ENABLED", "false").lower() == "true",
                },
                "content": {
                    "name": os.getenv("OPENAI_CONTENT_MODEL", "Qwen/Qwen2.5-7B-Instruct"),
                    "temperature": 1.0,
                    "api_key": os.getenv("OPENAI_CONTENT_API_KEY", ""),
                    "base_url": os.getenv("OPENAI_CONTENT_API_BASE", "https://api.siliconflow.cn/v1"),
                    "api_mode": os.getenv("OPENAI_CONTENT_API_MODE", os.getenv("OPENAI_API_MODE", "auto")).lower(),
                    "timeout": _safe_int(os.getenv("OPENAI_CONTENT_TIMEOUT", "180"), 180),
                    "reasoning_enabled": os.getenv("OPENAI_CONTENT_REASONING_ENABLED", "false").lower() == "true",
                },
                "reranker": {
                    "name": os.getenv("OPENAI_RERANKER_MODEL", "Qwen/Qwen3-Reranker-0.6B"),
                    "api_key": os.getenv("OPENAI_EMBEDDING_API_KEY", ""),
                    "base_url": os.getenv("OPENAI_EMBEDDING_API_BASE", "https://api.siliconflow.cn/v1"),
                    "api_mode": os.getenv("OPENAI_RERANKER_API_MODE", os.getenv("OPENAI_API_MODE", "auto")).lower(),
                    "use_fp16": os.getenv("OPENAI_RERANKER_USE_FP16", "True") == "True",
                    "timeout": _safe_int(os.getenv("OPENAI_EMBEDDING_TIMEOUT", "60"), 60)
                }
            }
        }
        # Claude 配置（Anthropic 官方 API）
        self.claude_config = {
            "api_key": os.getenv("CLAUDE_API_KEY", ""),
            "retry_delay": _safe_float(os.getenv("CLAUDE_RETRY_DELAY", "10"), 10.0),  # 默认 10 秒
            "timeout": _safe_int(os.getenv("CLAUDE_TIMEOUT", "120"), 120),  # 默认 120 秒
            # 备用模型配置
            "fallback": {
                "enabled": os.getenv("CLAUDE_FALLBACK_ENABLED", "True") == "True",
                "api_key": os.getenv("FALLBACK_API_KEY", ""),
                "base_url": os.getenv("CLAUDE_FALLBACK_BASE_URL", os.getenv("FALLBACK_API_BASE", "https://api.siliconflow.cn/v1")),
                "timeout": _safe_int(os.getenv("CLAUDE_FALLBACK_TIMEOUT", "120"), 120),
                "model": os.getenv("CLAUDE_FALLBACK_MODEL", os.getenv("FALLBACK_MODEL_ID", "Qwen/Qwen2.5-7B-Instruct"))
            },
            "models": {
                "outline": {
                    "name": os.getenv("CLAUDE_OUTLINE_MODEL", "claude-3-5-sonnet-20241022"),
                    "temperature": 1.0
                },
                "content": {
                    "name": os.getenv("CLAUDE_CONTENT_MODEL", "claude-3-5-sonnet-20241022"),
                    "temperature": 1.0
                }
            }
        }
        # Gemini 配置（仅支持 Google 官方 API）
        self.gemini_config = {
            "api_key": os.getenv("GEMINI_API_KEY", ""),
            "retry_delay": _safe_float(os.getenv("GEMINI_RETRY_DELAY", "30"), 30.0),  # 默认 30 秒
            "max_retries": _safe_int(os.getenv("GEMINI_MAX_RETRIES", "5"), 5),  # 默认 5 次
            "max_input_length": _safe_int(os.getenv("GEMINI_MAX_INPUT_LENGTH", "500000"), 500000),  # 默认 500000 字符
            "timeout": _safe_int(os.getenv("GEMINI_TIMEOUT", "60"), 60),  # 默认 60 秒
            # 备用模型配置
            "fallback": {
                "enabled": os.getenv("GEMINI_FALLBACK_ENABLED", "True") == "True",  # 默认启用备用模型
                "api_key": os.getenv("FALLBACK_API_KEY", ""),  # 使用独立的备用API密钥
                "base_url": os.getenv("GEMINI_FALLBACK_BASE_URL", os.getenv("FALLBACK_API_BASE", "https://api.siliconflow.cn/v1")),
                "timeout": _safe_int(os.getenv("GEMINI_FALLBACK_TIMEOUT", "120"), 120),  # 备用API使用更长的超时时间
                "models": {
                    # 备用默认也切换到免费开源模型，避免高成本模型兜底
                    "flash": "Qwen/Qwen2.5-7B-Instruct",
                    "pro": "Qwen/Qwen2.5-7B-Instruct",
                    "default": "Qwen/Qwen2.5-7B-Instruct"
                }
            },
            "models": {
                "outline": {
                    "name": os.getenv("GEMINI_OUTLINE_MODEL", "gemini-2.5-pro"),
                    "temperature": 1.0
                },
                "content": {
                    "name": os.getenv("GEMINI_CONTENT_MODEL", "gemini-2.5-flash"),
                    "temperature": 1.0
                }
            }
        }
        # 验证配置
        self._validate_config()
    
    def _validate_config(self):
        """验证配置是否有效（按需验证，仅检查关键配置的格式正确性）"""
        # 记录各 provider 的配置状态，但不强制所有 provider 都必须配置
        configured_providers = []

        # 检查 Claude 配置
        if self.claude_config["api_key"]:
            configured_providers.append("claude")

        # 检查 Gemini 配置
        if self.gemini_config["api_key"]:
            configured_providers.append("gemini")

        # 检查 OpenAI 配置（至少需要 embedding 的 API key）
        has_any_openai = False
        for model_type, model_config in self.openai_config["models"].items():
            if model_config["api_key"]:
                has_any_openai = True
            if model_config["api_key"] and not model_config["base_url"]:
                raise ValueError(f"OPENAI_{model_type.upper()}_API_KEY 已设置但缺少 API_BASE 配置")
        if has_any_openai:
            configured_providers.append("openai")

        # 至少需要一个 provider 被正确配置
        if not configured_providers:
            raise ValueError(
                "未检测到任何已配置的AI模型提供商。请至少设置以下之一：\n"
                "  - CLAUDE_API_KEY（Claude模型）\n"
                "  - GEMINI_API_KEY（Gemini模型）\n"
                "  - OPENAI_EMBEDDING_API_KEY（OpenAI兼容模型）"
            )

        import logging
        logging.info(f"Detected configured AI providers: {', '.join(configured_providers)}")
    
    def get_claude_config(self, model_type: str = "content") -> Dict[str, Any]:
        """获取 Claude 模型配置（Anthropic 官方 API）"""
        if model_type not in self.claude_config["models"]:
            raise ValueError(f"不支持的 Claude 模型类型: {model_type}")

        config = {
            "type": "claude",
            "api_key": self.claude_config["api_key"],
            "model_name": self.claude_config["models"][model_type]["name"],
            "temperature": self.claude_config["models"][model_type]["temperature"],
            "retry_delay": self.claude_config["retry_delay"],
            "timeout": self.claude_config["timeout"]
        }

        # 添加备用模型配置
        if self.claude_config["fallback"]["enabled"]:
            fallback = self.claude_config["fallback"]
            config.update({
                "fallback_enabled": True,
                "fallback_api_key": fallback["api_key"],
                "fallback_base_url": fallback["base_url"],
                "fallback_timeout": fallback["timeout"],
                "fallback_model": fallback["model"],
            })
        else:
            config["fallback_enabled"] = False

        return config

    def get_gemini_config(self, model_type: str = "content") -> Dict[str, Any]:
        """获取 Gemini 模型配置（仅支持 Google 官方 API）"""
        if model_type not in self.gemini_config["models"]:
            raise ValueError(f"不支持的 Gemini 模型类型: {model_type}")

        config = {
            "type": "gemini",
            "api_key": self.gemini_config["api_key"],
            "model_name": self.gemini_config["models"][model_type]["name"],
            "temperature": self.gemini_config["models"][model_type]["temperature"],
            "retry_delay": self.gemini_config["retry_delay"],
            "max_retries": self.gemini_config["max_retries"],
            "max_input_length": self.gemini_config["max_input_length"],
            "timeout": self.gemini_config["timeout"]
        }

        # 添加备用模型配置
        if self.gemini_config["fallback"]["enabled"]:
            fallback = self.gemini_config["fallback"]
            config.update({
                "fallback_enabled": True,
                "fallback_api_key": fallback["api_key"],
                "fallback_base_url": fallback["base_url"],
                "fallback_timeout": fallback["timeout"],
                "fallback_model": fallback["models"].get("default", "Qwen/Qwen2.5-7B-Instruct"),
            })
        else:
            config["fallback_enabled"] = False

        return config

    def get_openai_config(self, model_type: str = "embedding") -> Dict[str, Any]:
        """获取 OpenAI 模型配置"""
        if model_type not in self.openai_config["models"]:
            raise ValueError(f"不支持的 OpenAI 模型类型: {model_type}")
        model_config = self.openai_config["models"][model_type]
        # 针对reranker类型，返回专用字段
        if model_type == "reranker":
            return {
                "type": "openai",
                "api_key": model_config["api_key"],
                "base_url": model_config["base_url"],
                "model_name": model_config["name"],
                "api_mode": model_config.get("api_mode", "auto"),
                "use_fp16": model_config.get("use_fp16", True),
                "retry_delay": self.openai_config["retry_delay"],
                "timeout": model_config.get("timeout", 60)
            }
        config = {
            "type": "openai",
            "api_key": model_config["api_key"],
            "base_url": model_config["base_url"],
            "model_name": model_config["name"],
            "api_mode": model_config.get("api_mode", "auto"),
            "temperature": model_config.get("temperature", 1.0),
            "dimension": model_config.get("dimension", 1024),
            "retry_delay": self.openai_config["retry_delay"],
            "timeout": model_config.get("timeout", 60),
            "reasoning_enabled": model_config.get("reasoning_enabled", False),
        }

        # 添加备用模型配置（使用独立的 FALLBACK_* 环境变量）
        fallback_enabled = os.getenv("OPENAI_FALLBACK_ENABLED", "True") == "True"
        if fallback_enabled and os.getenv("FALLBACK_API_KEY"):
            fallback_timeout_str = os.getenv("OPENAI_FALLBACK_TIMEOUT", "120")
            try:
                fallback_timeout = int(fallback_timeout_str) if fallback_timeout_str.strip() else 120
            except (ValueError, AttributeError):
                fallback_timeout = 120

            config.update({
                "fallback_enabled": True,
                "fallback_api_key": os.getenv("FALLBACK_API_KEY", ""),
                "fallback_base_url": os.getenv("FALLBACK_API_BASE", "https://api.siliconflow.cn/v1"),
                "fallback_timeout": fallback_timeout,
                "fallback_model": os.getenv("FALLBACK_MODEL_ID", "Qwen/Qwen2.5-7B-Instruct"),
                "fallback_api_mode": os.getenv("FALLBACK_API_MODE", "auto").lower(),
            })
        else:
            config["fallback_enabled"] = False

        return config
    
    def get_model_config(self, model_type: str) -> Dict[str, Any]:
        """获取指定类型的模型配置"""
        if model_type.startswith("claude"):
            return self.get_claude_config(model_type.split("_")[1])
        elif model_type.startswith("gemini"):
            return self.get_gemini_config(model_type.split("_")[1])
        elif model_type.startswith("openai"):
            return self.get_openai_config(model_type.split("_")[1])
        else:
            raise ValueError(f"不支持的模型类型: {model_type}")

    def get_model_config_by_purpose(self, model_purpose: str) -> Dict[str, Any]:
        """根据用途获取模型配置"""
        # 这个方法需要外部传入config和ai_config实例
        # 暂时保留但标记为需要重构
        raise NotImplementedError("此方法需要重构，请使用get_gemini_config或get_openai_config方法")
