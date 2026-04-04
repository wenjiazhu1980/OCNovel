"""后台营销内容生成 Worker：在 QThread 中执行营销内容生成"""
import os
import json
import logging
from PySide6.QtCore import QThread, Signal

from src.gui.utils.log_handler import SignalLogHandler


def create_model(model_config: dict):
    """根据配置创建 AI 模型实例"""
    model_type = model_config["type"]
    if model_type == "gemini":
        from src.models.gemini_model import GeminiModel
        return GeminiModel(model_config)
    elif model_type in ("openai",):
        from src.models.openai_model import OpenAIModel
        return OpenAIModel(model_config)
    else:
        raise ValueError(f"不支持的模型类型: {model_type}")


class MarketingWorker(QThread):
    """后台运行营销内容生成"""

    # ---- 信号 ----
    generation_finished = Signal(bool, str)  # (是否成功, 结果消息或错误信息)
    log_message = Signal(str, str)           # (message, level)

    def __init__(
        self,
        config_path: str,
        env_path: str,
        output_dir: str = "data/marketing",
    ):
        super().__init__()
        self._config_path = config_path
        self._env_path = env_path
        self._output_dir = output_dir

    # ------------------------------------------------------------------
    # 核心执行逻辑
    # ------------------------------------------------------------------

    def run(self):
        logger = logging.getLogger("MarketingWorker")
        handler: SignalLogHandler | None = None

        try:
            # ---- 1. 加载环境变量 ----
            from dotenv import load_dotenv
            load_dotenv(self._env_path, override=True)

            # ---- 2. 加载配置 ----
            from src.config.config import Config
            config = Config(self._config_path)

            # ---- 3. 安装日志桥接 Handler ----
            handler = SignalLogHandler()
            handler.emitter.log_message.connect(self.log_message.emit)
            root_logger = logging.getLogger()
            root_logger.addHandler(handler)

            logger.info("开始生成营销内容...")

            # ---- 4. 创建内容生成模型 ----
            content_model = create_model(config.get_model_config("content_model"))
            logger.info("AI模型初始化完成")

            # ---- 5. 创建标题生成器 ----
            from src.generators.title_generator import TitleGenerator
            generator = TitleGenerator(content_model, self._output_dir)

            # ---- 6. 加载章节摘要 ----
            chapter_summaries = []
            output_dir = config.output_config.get("output_dir", "data/output")
            if not os.path.isabs(output_dir):
                output_dir = os.path.join(os.path.dirname(self._config_path), output_dir)
            summary_file = os.path.join(output_dir, "summary.json")

            if os.path.exists(summary_file):
                try:
                    with open(summary_file, "r", encoding="utf-8") as f:
                        summaries = json.load(f)
                        chapter_summaries = list(summaries.values())
                    logger.info(f"已加载 {len(chapter_summaries)} 条章节摘要")
                except Exception as e:
                    logger.warning(f"加载摘要文件时出错: {e}")

            # ---- 7. 准备小说配置 ----
            novel_config = {
                "type": config.novel_config.get("type", "玄幻"),
                "theme": config.novel_config.get("theme", "修真逆袭"),
                "keywords": config.novel_config.get("keywords", []),
                "main_characters": config.novel_config.get("main_characters", [])
            }

            # ---- 8. 一键生成所有营销内容 ----
            result = generator.one_click_generate(novel_config, chapter_summaries)

            logger.info("营销内容生成完成！")
            logger.info(f"结果已保存到：{result['saved_file']}")

            # 构建结果消息
            result_msg = f"营销内容已保存到：\n{result['saved_file']}\n\n"
            result_msg += "【标题方案】\n"
            for platform, title in result["titles"].items():
                result_msg += f"{platform}: {title}\n"

            self.generation_finished.emit(True, result_msg)

        except Exception as exc:
            error_msg = f"生成营销内容时出错: {exc}"
            logger.error(error_msg, exc_info=True)
            self.generation_finished.emit(False, error_msg)
        finally:
            # 移除日志桥接，避免泄漏
            if handler is not None:
                logging.getLogger().removeHandler(handler)
