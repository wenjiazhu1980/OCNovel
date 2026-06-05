from abc import ABC, abstractmethod
import numpy as np
from typing import Optional, Dict, Any

DEFAULT_MAX_PROMPT_LENGTH = 190000


class BaseModel(ABC):
    """AI模型基础接口类"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.api_key = config.get("api_key", "")
        self.model_name = config.get("model_name", "")

    @abstractmethod
    def generate(self, prompt: str, max_tokens: Optional[int] = None, **kwargs) -> str:
        """生成文本

        Args:
            prompt: 提示词
            max_tokens: 最大生成token数
            **kwargs: 额外参数，如 temperature, top_p 等，用于覆盖模型默认值
        """
        pass

    @abstractmethod
    def embed(self, text: str) -> np.ndarray:
        """获取文本嵌入向量"""
        pass

    def _validate_config(self) -> bool:
        """验证配置是否有效"""
        if not self.api_key:
            raise ValueError("API key is required")
        if not self.model_name:
            raise ValueError("Model name is required")
        return True

    def close(self):
        """关闭模型客户端，子类应该重写此方法"""
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


def truncate_prompt_preserving_ends(prompt: str, max_length: int, head_ratio: float = 0.7) -> str:
    """将超长 prompt 截断到 max_length 字符，保留首尾、省略中间。

    相比直接砍尾部（prompt[:max_length]），保首尾能同时保住头部的角色/指令与
    尾部的输出格式/当前任务约定，避免静默丢失关键信息；中间部分通常是参考
    上下文，丢失代价相对最小。

    Args:
        prompt: 原始提示词。
        max_length: 截断后允许的最大字符数（含省略标记）。
        head_ratio: 预算中分配给头部的比例（其余给尾部），默认 0.7。

    Returns:
        长度不超过 max_length 的提示词；未超长时原样返回。
    """
    if len(prompt) <= max_length:
        return prompt
    marker_tpl = "\n\n……（已省略中间约 {n} 字符以适应模型长度限制）……\n\n"
    # 用最大可能的 n（原始长度）估算标记占位，确保最终长度不超过 max_length
    reserved = len(marker_tpl.format(n=len(prompt)))
    budget = max_length - reserved
    if budget <= 0:
        # max_length 过小，容纳不下标记，退化为纯头部截断
        return prompt[:max_length]
    head = int(budget * head_ratio)
    tail = budget - head
    omitted = len(prompt) - head - tail
    marker = marker_tpl.format(n=omitted)
    if tail > 0:
        return prompt[:head] + marker + prompt[-tail:]
    return prompt[:head] + marker
