from typing import Dict, Any
import os
import json
import logging
from dotenv import load_dotenv
from .ai_config import AIConfig

def _sanitize_config_for_logging(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    清理配置对象中的敏感信息，用于安全的日志输出
    
    Args:
        config: 原始配置字典
        
    Returns:
        清理后的配置字典，敏感信息已被替换为星号
    """
    if not isinstance(config, dict):
        return config
        
    sanitized = {}
    sensitive_keys = {'api_key', 'fallback_api_key', 'password', 'secret', 'token'}
    
    for key, value in config.items():
        if isinstance(value, dict):
            sanitized[key] = _sanitize_config_for_logging(value)
        elif any(sensitive_key in key.lower() for sensitive_key in sensitive_keys):
            # 如果值不为空，则显示前4位和后4位，中间用星号替代
            if value and len(str(value)) > 8:
                sanitized[key] = f"{str(value)[:4]}****{str(value)[-4:]}"
            elif value:
                sanitized[key] = "****"
            else:
                sanitized[key] = "未设置"
        else:
            sanitized[key] = value
    
    return sanitized

class Config:
    """配置管理类"""
    
    def __init__(self, config_file: str = "config.json"):
        """
        初始化配置

        Args:
            config_file: 配置文件路径
        """
        self._code_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        # 如果配置文件路径不是绝对路径，则相对于代码根目录
        if not os.path.isabs(config_file):
            self.config_file = os.path.join(self._code_dir, config_file)
        else:
            self.config_file = config_file

        # base_dir 基于配置文件所在目录（支持 ~/OCNovel 等外部目录）
        self.base_dir = os.path.dirname(os.path.abspath(self.config_file))
        
        # 加载环境变量（优先使用配置文件同目录下的 .env）
        env_file = os.path.join(self.base_dir, ".env")
        if os.path.exists(env_file):
            load_dotenv(env_file, override=True)
        else:
            load_dotenv()
        
        # 加载配置文件
        with open(self.config_file, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
            
        # 初始化 AI 配置
        self.ai_config = AIConfig()
        
        # 从配置文件中读取 output_dir，相对路径基于 base_dir
        config_output_dir = self.config["output_config"].get("output_dir")
        if config_output_dir and not os.path.isabs(config_output_dir):
            config_output_dir = os.path.join(self.base_dir, config_output_dir)
        
        # 优先使用config.json中的model_config（支持深合并：未声明的字段从 AIConfig 默认继承）
        # 这样 config.json 只需声明要覆盖的字段（如 temperature/reasoning_enabled），
        # 不必复制 api_key/base_url 等敏感与冗余信息。
        # 动态构建 AIConfig 默认 model_config（始终构建，作为深合并基线）
        default_model_config = {}
        model_selection = self.config["generation_config"].get("model_selection", {})
        # outline_model
        outline_sel = model_selection.get("outline", {"provider": "openai", "model_type": "outline"})
        if outline_sel["provider"] == "openai":
            default_model_config["outline_model"] = self.ai_config.get_openai_config(outline_sel["model_type"])
        elif outline_sel["provider"] == "claude":
            default_model_config["outline_model"] = self.ai_config.get_claude_config(outline_sel["model_type"])
        else:
            default_model_config["outline_model"] = self.ai_config.get_gemini_config(outline_sel["model_type"])
        # content_model
        content_sel = model_selection.get("content", {"provider": "openai", "model_type": "content"})
        if content_sel["provider"] == "openai":
            default_model_config["content_model"] = self.ai_config.get_openai_config(content_sel["model_type"])
        elif content_sel["provider"] == "claude":
            default_model_config["content_model"] = self.ai_config.get_claude_config(content_sel["model_type"])
        else:
            default_model_config["content_model"] = self.ai_config.get_gemini_config(content_sel["model_type"])
        # embedding_model 只支持openai
        default_model_config["embedding_model"] = self.ai_config.get_openai_config("embedding")

        if "model_config" in self.config:
            # 深合并：config.json 中的字段覆盖默认值，未声明的字段保留默认值
            override = self.config["model_config"]
            self.model_config = default_model_config
            for sub_key, sub_override in (override or {}).items():
                if isinstance(sub_override, dict) and isinstance(self.model_config.get(sub_key), dict):
                    self.model_config[sub_key] = {**self.model_config[sub_key], **sub_override}
                else:
                    self.model_config[sub_key] = sub_override
            logging.info("使用配置文件中的 model_config（已与 AIConfig 默认值深合并）")
        else:
            self.model_config = default_model_config
            logging.info("使用AIConfig的默认model_config")
        
        # 小说配置
        self.novel_config = self.config["novel_config"]
        
        # 知识库配置
        self.knowledge_base_config = self.config["knowledge_base_config"]
        self.knowledge_base_config["reference_files"] = [
            os.path.join(self.base_dir, file_path) if not os.path.isabs(file_path) else file_path
            for file_path in self.knowledge_base_config["reference_files"]
        ]
        # 缓存目录：相对路径基于 base_dir
        cache_dir = self.knowledge_base_config.get("cache_dir", "data/cache")
        if not os.path.isabs(cache_dir):
            self.knowledge_base_config["cache_dir"] = os.path.join(self.base_dir, cache_dir)
        
        # 生成器配置
        self.generator_config = {
            "target_chapters": self.novel_config["target_chapters"],
            "chapter_length": self.novel_config["chapter_length"],
            "output_dir": config_output_dir if config_output_dir else os.path.join(self.base_dir, "data", "output"),
            "max_retries": self.config["generation_config"]["max_retries"],
            "retry_delay": self.config["generation_config"]["retry_delay"],
            "validation": self.config["generation_config"]["validation"]
        }
        
        # 日志配置
        self.log_config = {
            "log_dir": os.path.join(self.base_dir, "data", "logs"),
            "log_level": "INFO",
            "log_format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        }
        
        # 输出配置
        self.output_config = self.config["output_config"]
        self.output_config.update({
            "output_dir": config_output_dir if config_output_dir else os.path.join(self.base_dir, "data", "output")
        })
        
        # 仿写配置
        self.imitation_config = self.config.get("imitation_config", {})

        # 启动时打印当前 model_config 便于调试（安全输出）
        logging.info(f"[调试] 当前 model_config: {_sanitize_config_for_logging(self.model_config)}")
    
    def get_model_config(self, model_type: str) -> Dict[str, Any]:
        """
        获取指定类型的模型配置
        
        Args:
            model_type: 模型类型（outline_model/content_model/embedding_model/imitation_model）
            
        Returns:
            Dict[str, Any]: 模型配置
        """
        if model_type in self.model_config:
            return self.model_config[model_type]
        raise ValueError(f"不支持的模型类型: {model_type}")
    
    def get_writing_guide(self) -> Dict:
        """获取写作指南"""
        return self.novel_config["writing_guide"]
        
    def save(self):
        """保存配置到文件"""
        config = {
            "novel_config": self.novel_config,
            "generation_config": {
                "max_retries": self.generator_config["max_retries"],
                "retry_delay": self.generator_config["retry_delay"],
                "validation": self.generator_config["validation"]
            },
            "output_config": self.output_config
        }
        
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    
    def __getattr__(self, name: str) -> Any:
        """获取配置项"""
        if name in self.config:
            return self.config[name]
        raise AttributeError(f"Config has no attribute '{name}'")

    def get_imitation_model(self) -> Dict[str, Any]:
        """
        获取仿写专用模型配置，优先级：
        1. model_config['imitation_model']
        2. content_model（默认使用当前内容生成模型）
        3. ai_config.gemini_config['fallback']（作为最后备用选项）
        """
        # 1. 优先使用 model_config['imitation_model']
        if "imitation_model" in self.model_config:
            logging.info(f"[仿写模型选择] 使用 model_config['imitation_model']: {_sanitize_config_for_logging(self.model_config['imitation_model'])}")
            return self.model_config["imitation_model"]
        # 2. 默认使用 content_model（推荐）
        content_model = self.model_config.get("content_model")
        if content_model:
            logging.info(f"[仿写模型选择] 使用 content_model: {_sanitize_config_for_logging(content_model)}")
            return content_model
        # 3. 最后使用 ai_config.gemini_config['fallback'] 作为备用
        fallback = getattr(self.ai_config, "gemini_config", {}).get("fallback")
        if fallback and fallback.get("enabled", False):
            fallback_model_name = fallback.get("models", {}).get("default", "deepseek-ai/DeepSeek-V3")
            imitation_fallback_config = {
                "type": "gemini",
                "model_name": fallback_model_name,
                "api_key": fallback.get("api_key", ""),
                "base_url": fallback.get("base_url", "https://api.siliconflow.cn/v1"),
                "timeout": fallback.get("timeout", 180),
            }
            logging.info(f"[仿写模型选择] 使用 gemini_config['fallback'] 作为最后备用: {_sanitize_config_for_logging(imitation_fallback_config)}")
            return imitation_fallback_config
        # 4. 如果所有配置都不可用，抛出异常
        raise ValueError("无法获取仿写模型配置：未配置 imitation_model、content_model 或 fallback 模型") 