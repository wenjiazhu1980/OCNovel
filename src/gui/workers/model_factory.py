"""模型工厂 - 各 Worker 共用的模型创建逻辑"""
from PySide6.QtCore import QCoreApplication


def create_model(model_config: dict, context: str = "Worker"):
    """根据配置创建 AI 模型实例

    Args:
        model_config: 模型配置字典，必须包含 "type" 键
        context: 翻译上下文名称，用于错误消息国际化
    """
    model_type = model_config["type"]
    if model_type == "gemini":
        from src.models.gemini_model import GeminiModel
        return GeminiModel(model_config)
    elif model_type in ("openai",):
        from src.models.openai_model import OpenAIModel
        return OpenAIModel(model_config)
    elif model_type == "claude":
        from src.models.claude_model import ClaudeModel
        return ClaudeModel(model_config)
    else:
        raise ValueError(
            QCoreApplication.translate(
                context, "不支持的模型类型: {0}"
            ).format(model_type)
        )
