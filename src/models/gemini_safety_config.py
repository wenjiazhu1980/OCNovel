"""Gemini 安全配置管理器"""

import logging
from typing import Dict, Any, List
from google.generativeai.types import HarmCategory, HarmBlockThreshold


class GeminiSafetyConfig:
    """Gemini 模型安全配置管理"""

    # 预定义的安全设置配置
    SAFETY_SETTINGS = {
        "creative": {
            # 创意内容（小说、故事等）- 较宽松的安全设置
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        },
        "default": {
            # 默认设置 - 中等安全级别
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
        },
        "strict": {
            # 严格设置 - 最高安全级别
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
        }
    }

    @classmethod
    def get_safety_settings_for_content_type(cls, content_type: str = "creative") -> Dict[HarmCategory, HarmBlockThreshold]:
        """
        根据内容类型获取安全设置

        Args:
            content_type: 内容类型，可选值: "creative", "default", "strict"

        Returns:
            安全设置字典
        """
        if content_type not in cls.SAFETY_SETTINGS:
            logging.warning(f"未知的内容类型: {content_type}，使用默认设置")
            content_type = "default"

        settings = cls.SAFETY_SETTINGS[content_type]
        logging.info(f"使用 {content_type} 内容类型的安全设置")
        return settings

    @classmethod
    def log_safety_ratings(cls, safety_ratings: List[Any]) -> None:
        """
        记录安全评级信息

        Args:
            safety_ratings: 安全评级列表
        """
        if not safety_ratings:
            return

        logging.info("安全评级:")
        for rating in safety_ratings:
            category = rating.category
            probability = rating.probability
            logging.info(f"  - {category}: {probability}")
