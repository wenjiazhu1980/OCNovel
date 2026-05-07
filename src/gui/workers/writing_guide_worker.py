"""后台线程：调用 AI 模型自动生成写作指南"""
import json
import logging
import os
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
目标篇幅: {target_chapters} 章（约 {total_words_wan} 万字）

【角色数量要求】
- supporting_roles 必须恰好生成 {n_supporting} 个（当前篇幅为 {target_chapters} 章，角色数量应与篇幅匹配：短篇 ≤30 章建议 2-4 个配角，中篇 30-100 章建议 4-8 个，长篇 100+ 章建议 8-15 个）
- antagonists 必须恰好生成 {n_antagonists} 个（短篇 1-2 个，中篇 2-4 个，长篇 4-8 个）
- 所有角色（supporting_roles + antagonists）中，约 {female_pct}% 应为女性角色
- 每个角色必须包含 name（中文姓名，2-4 字）、gender（"男" / "女" / "其他"）、role_type、personality 字段
- 配角的 role_type 应多样化（导师/亲人、伙伴/挚友、红颜/道侣、对手/竞争者、情报/线人等），避免全部是同一类型
- 反派应分层次（初期反派、中期BOSS、幕后黑手等），确保不同阶段都有对手

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
      {{"name": "角色姓名", "gender": "男/女/其他", "role_type": "角色类型", "personality": "性格描述", "relationship": "与主角的关系"}}
    ],
    "antagonists": [
      {{"name": "角色姓名", "gender": "男/女/其他", "role_type": "反派类型", "personality": "性格描述", "conflict_point": "冲突点"}}
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
    }},
    "disasters": {{
      "first_disaster": "约 25% 处发生的第一次灾难事件，迫使主角在生死中成长",
      "second_disaster": "约 50% 处发生的第二次灾难事件，主角遭遇重大挫折或身份危机",
      "third_disaster": "约 75% 处发生的第三次灾难事件，主角必须直面远超自身的威胁"
    }}
  }},
  "style_guide": {{
    "tone": "整体基调描述",
    "pacing": "节奏描述",
    "description_focus": [
      "第一个描写侧重点，例如：战斗场面、招式神通的力量感",
      "第二个描写侧重点，例如：世界观奇观、神秘氛围的营造",
      "第三个描写侧重点，例如：主角的成长与反思、配角群像的刻画"
    ]
  }}
}}

注意事项：
- description_focus 必须包含至少 3 条，每条 30~80 字，且聚焦不同维度（战斗 / 世界观 / 人物 / 情感 / 权谋等）。
- supporting_roles 与 antagonists 的数量必须严格匹配上述要求；女性角色比例尽量接近 {female_pct}%。"""


class WritingGuideWorker(QThread):
    """调用大纲模型生成写作指南"""

    # (success, result_dict_or_error_msg)
    finished_result = Signal(bool, object)

    def __init__(self, env_path: str, story_idea: str, title: str,
                 novel_type: str, theme: str, style: str,
                 n_supporting: int = 6, n_antagonists: int = 4,
                 female_ratio: float = 0.3, target_chapters: int = 100,
                 chapter_length: int = 2500,
                 existing_focus: list = None,
                 dedup_max_total: int = 8,
                 parent=None):
        super().__init__(parent)
        self._env_path = env_path
        self._story_idea = story_idea
        self._title = title
        self._novel_type = novel_type
        self._theme = theme
        self._style = style
        self._n_supporting = max(0, int(n_supporting))
        self._n_antagonists = max(0, int(n_antagonists))
        self._female_ratio = max(0.0, min(1.0, float(female_ratio)))
        self._target_chapters = max(1, int(target_chapters))
        self._chapter_length = max(500, int(chapter_length))
        # [5.3] 异步化:把描写侧重去重(含 embedding 网络调用)挪到 worker 线程,
        # 主线程 _on_guide_result 不再直接 embed(),避免 UI 卡顿
        self._existing_focus = list(existing_focus or [])
        self._dedup_max_total = max(1, int(dedup_max_total))

    def stop(self):
        """协作取消：run() 内 stream 循环会在下一个 chunk 感知并立即退出。"""
        self.requestInterruption()

    def run(self):
        stream = None
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
            total_words = self._target_chapters * self._chapter_length
            prompt = _PROMPT.format(
                story_idea=self._story_idea,
                title=self._title,
                novel_type=self._novel_type,
                theme=self._theme,
                style=self._style,
                n_supporting=self._n_supporting,
                n_antagonists=self._n_antagonists,
                female_pct=int(round(self._female_ratio * 100)),
                target_chapters=self._target_chapters,
                total_words_wan=f"{total_words / 10000:.0f}",
            )

            # 调用 API - 使用 stream 模式以支持协作取消
            # （每个 chunk 之间检查 isInterruptionRequested()，关窗时可秒级退出）
            client = openai.OpenAI(api_key=api_key, base_url=base_url, timeout=120)
            stream = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=1.0,
                stream=True,
            )

            chunks: list[str] = []
            for chunk in stream:
                if self.isInterruptionRequested():
                    self.finished_result.emit(False, "已取消")
                    return
                try:
                    delta = chunk.choices[0].delta.content
                except (AttributeError, IndexError):
                    delta = None
                if delta:
                    chunks.append(delta)
            text = "".join(chunks).strip()

            # 去除可能的 markdown 代码块标记
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3].rstrip()

            result = json.loads(text)
            if not isinstance(result, dict):
                self.finished_result.emit(False, "模型返回的不是有效的 JSON 对象")
                return

            # [5.3] 在 worker 线程内完成描写侧重去重,
            # 避免主线程在收到结果后被 embed() 网络调用阻塞
            self._maybe_dedup_focus(result)

            self.finished_result.emit(True, result)

        except json.JSONDecodeError as e:
            self.finished_result.emit(False, f"JSON 解析失败: {e}")
        except Exception as e:
            logger.error(f"生成写作指南失败: {e}", exc_info=True)
            self.finished_result.emit(False, str(e))
        finally:
            # 显式关闭 stream，确保底层 HTTP 连接不泄漏
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # [5.3] 后台线程内执行描写侧重去重,避免阻塞主线程 UI
    # ------------------------------------------------------------------
    def _maybe_dedup_focus(self, result: dict) -> None:
        """若 result.style_guide.description_focus 存在,则在本线程内去重

        副作用: 在 result 中写入两个新字段供主线程消费:
        - 'description_focus_kept': 已去重并截断的列表
        - 'description_focus_dedup_stats': 去重统计 dict (与 deduplicate_focus_items 返回一致)
        失败时静默(不写新字段),主线程会回退到旧路径处理。
        """
        try:
            sg = result.get("style_guide", {}) or {}
            df = sg.get("description_focus", [])
            if isinstance(df, list):
                candidates = [str(x) for x in df if str(x).strip()]
            elif isinstance(df, str) and df.strip():
                candidates = [df]
            else:
                return

            if not candidates:
                return

            from ..utils.focus_dedup import deduplicate_focus_items
            embed_model = self._create_embedding_model_in_worker()
            kept, stats = deduplicate_focus_items(
                existing=self._existing_focus,
                candidates=candidates,
                embedding_model=embed_model,
                max_total=self._dedup_max_total,
            )
            result["description_focus_kept"] = kept
            result["description_focus_dedup_stats"] = stats
        except Exception as e:
            logger.warning(f"[5.3] worker 内去重失败,主线程将走兜底路径: {e}")

    def _create_embedding_model_in_worker(self):
        """与 NovelParamsTab._try_create_embedding_model 等价的工厂方法

        Returns:
            可用的 embedding 模型实例;失败时返回 None,deduplicate_focus_items
            会自动降级到 Jaccard 词级路径。
        """
        try:
            from dotenv import load_dotenv
            from src.config.ai_config import AIConfig
            from .model_factory import create_model

            if self._env_path and os.path.exists(self._env_path):
                load_dotenv(self._env_path, override=True)
            ai_config = AIConfig()
            embed_config = ai_config.get_openai_config("embedding")
            if not embed_config.get("api_key"):
                logger.info("[5.3] embedding API key 未配置,worker 内将走 Jaccard 兜底")
                return None
            return create_model(embed_config, context="WritingGuide")
        except Exception as e:
            logger.warning(f"[5.3] worker 内创建 embedding 模型失败: {type(e).__name__}: {e}")
            return None
