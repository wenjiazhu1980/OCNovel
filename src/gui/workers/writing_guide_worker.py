"""后台线程：调用 AI 模型自动生成写作指南"""
import json
import logging
from PySide6.QtCore import QThread, Signal

from src.gui.utils.config_io import load_env

logger = logging.getLogger(__name__)

# 写作指南生成提示词模板
_PROMPT = """你是一个富有创造力的小说设定助手。
根据以下故事创意和基本信息，生成详细的写作指南。

【故事创意】
{story_idea}

【基本信息】
标题: {title}
类型: {novel_type}
主题: {theme}
风格: {style}

请以故事创意为核心，展开完整的世界观、人物、剧情和风格设定。
严格按照以下 JSON 结构输出，所有字段都必须用中文填写，内容要具体、有创意、与故事创意紧密相关。
只返回纯 JSON，不要添加任何解释或 markdown 标记。

{{
  "world_building": {{
    "magic_system": "力量体系/核心设定的详细描述",
    "social_system": "社会体系/势力格局的详细描述",
    "background": "故事背景/世界观的详细描述"
  }},
  "character_guide": {{
    "protagonist": {{
      "background": "主角的身世背景",
      "initial_personality": "主角的初始性格特征",
      "growth_path": "主角的成长路线"
    }},
    "supporting_roles": [
      {{"role_type": "角色类型", "personality": "性格描述", "relationship": "与主角的关系"}}
    ],
    "antagonists": [
      {{"role_type": "反派类型", "personality": "性格描述", "conflict_point": "冲突点"}}
    ]
  }},
  "plot_structure": {{
    "act_one": {{
      "setup": "第一幕开场设定",
      "inciting_incident": "激励事件",
      "first_plot_point": "第一个转折点"
    }},
    "act_two": {{
      "rising_action": "上升动作",
      "midpoint": "中点转折",
      "complications": "复杂化",
      "darkest_moment": "至暗时刻",
      "second_plot_point": "第二个转折点"
    }},
    "act_three": {{
      "climax": "高潮",
      "resolution": "解决",
      "denouement": "结局"
    }}
  }},
  "style_guide": {{
    "tone": "整体基调描述",
    "pacing": "节奏描述"
  }}
}}"""


class WritingGuideWorker(QThread):
    """调用大纲模型生成写作指南"""

    # (success, result_dict_or_error_msg)
    finished_result = Signal(bool, object)

    def __init__(self, env_path: str, story_idea: str, title: str,
                 novel_type: str, theme: str, style: str, parent=None):
        super().__init__(parent)
        self._env_path = env_path
        self._story_idea = story_idea
        self._title = title
        self._novel_type = novel_type
        self._theme = theme
        self._style = style

    def run(self):
        try:
            import openai

            # 读取大纲模型配置
            env = load_env(self._env_path)
            api_key = env.get("OPENAI_OUTLINE_API_KEY", "")
            base_url = env.get("OPENAI_OUTLINE_API_BASE", "")
            model_name = env.get("OPENAI_OUTLINE_MODEL", "")

            if not api_key or not base_url or not model_name:
                self.finished_result.emit(False, "大纲模型未配置（需要 API Key、Base URL、模型名称）")
                return

            # 构建提示词
            prompt = _PROMPT.format(
                story_idea=self._story_idea,
                title=self._title,
                novel_type=self._novel_type,
                theme=self._theme,
                style=self._style,
            )

            # 调用 API
            client = openai.OpenAI(api_key=api_key, base_url=base_url)
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=1.0,
                timeout=120,
            )

            text = response.choices[0].message.content.strip()

            # 去除可能的 markdown 代码块标记
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3].rstrip()

            result = json.loads(text)
            if not isinstance(result, dict):
                self.finished_result.emit(False, "模型返回的不是有效的 JSON 对象")
                return

            self.finished_result.emit(True, result)

        except json.JSONDecodeError as e:
            self.finished_result.emit(False, f"JSON 解析失败: {e}")
        except Exception as e:
            logger.error(f"生成写作指南失败: {e}", exc_info=True)
            self.finished_result.emit(False, str(e))
