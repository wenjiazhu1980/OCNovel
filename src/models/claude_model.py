from anthropic import Anthropic
import numpy as np
import time
import concurrent.futures
from typing import Optional, Dict, Any
from tenacity import retry, stop_after_attempt, wait_fixed
from .base_model import BaseModel
import logging
import os

class ClaudeModel(BaseModel):
    """Claude (Anthropic) 模型实现"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._validate_config()
        # 从 config 读取默认采样参数：generate(**kwargs) 未传 temperature 时回退此值，
        # 避免被硬编码兜底覆盖掉 AIConfig / config.json 中配置的温度。兜底统一为 1.0。
        self.temperature = config.get("temperature", 1.0)
        self.top_p = config.get("top_p", None)
        self.cancel_checker = None  # 可选：外部注入的取消检查回调
        self._init_client(config)

    def _init_client(self, config: Dict[str, Any]):
        """初始化 Claude 客户端"""
        timeout = config.get("timeout", 120)  # 默认120秒

        # 备用API配置
        fallback_enabled = config.get("fallback_enabled", False)
        if fallback_enabled:
            self.fallback_api_key = config.get("fallback_api_key", os.getenv("FALLBACK_API_KEY", ""))
            self.fallback_base_url = config.get("fallback_base_url", os.getenv("FALLBACK_API_BASE", "https://api.siliconflow.cn/v1"))
            self.fallback_model_name = config.get("fallback_model", os.getenv("FALLBACK_MODEL_ID", "Qwen/Qwen2.5-7B-Instruct"))
            self.fallback_timeout = config.get("fallback_timeout", 180)
        else:
            self.fallback_api_key = ""
            self.fallback_base_url = ""
            self.fallback_model_name = ""
            self.fallback_timeout = 180

        # 初始化 Claude 客户端
        self.client = Anthropic(
            api_key=config["api_key"],
            timeout=timeout,
            max_retries=0  # 防止内部重试导致严重等待
        )

        logging.info(f"Claude model initialized: {self.model_name}, timeout: {timeout}s")

    def _cancellable_call(self, fn, *args, **kwargs):
        """在子线程中执行 API 调用，主线程每秒检查取消信号"""
        if not self.cancel_checker:
            return fn(*args, **kwargs)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(fn, *args, **kwargs)
            elapsed = 0
            while not future.done():
                if self.cancel_checker():
                    future.cancel()
                    raise InterruptedError("用户取消生成")
                try:
                    return future.result(timeout=1.0)
                except concurrent.futures.TimeoutError:
                    elapsed += 1
                    if elapsed % 30 == 0:
                        logging.info(f"API 调用进行中... 已等待 {elapsed} 秒")
                    continue
                except Exception:
                    raise
            return future.result()

    def _generate_with_claude_api(
        self,
        client: Anthropic,
        model_name: str,
        prompt: str,
        max_tokens: Optional[int],
        temperature: float
    ) -> str:
        """使用 Claude Messages API 生成文本"""
        # Claude API 限制 max_tokens 不超过 8192
        if max_tokens and max_tokens > 8192:
            logging.warning(f"max_tokens ({max_tokens}) 过大，已限制为 8192")
            max_tokens = 8192

        # 如果未指定 max_tokens，使用默认值 4096
        if not max_tokens:
            max_tokens = 4096

        params = {
            "model": model_name,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }

        try:
            # 使用流式传输
            content_chunks = []
            with client.messages.stream(**params) as stream:
                for text in stream.text_stream:
                    if self.cancel_checker and self.cancel_checker():
                        raise InterruptedError("用户取消生成")
                    content_chunks.append(text)

            content = "".join(content_chunks).strip()
            if not content:
                raise Exception("Claude API 响应流为空")
            return content

        except Exception as e:
            # 如果流式失败，尝试非流式
            if "stream" in str(e).lower() or type(e).__name__ in ("TypeError", "AttributeError"):
                logging.warning(f"流式请求失败，回退至非流式请求: {e}")
                response = client.messages.create(**params)

                # 提取文本内容
                if response.content and len(response.content) > 0:
                    # Claude API 返回的 content 是一个列表
                    text_blocks = [block.text for block in response.content if hasattr(block, 'text')]
                    content = "".join(text_blocks).strip()
                    if not content:
                        raise Exception("Claude API 非流式请求返回空内容")
                    return content
                else:
                    raise Exception("Claude API 非流式请求返回空内容")
            raise e

    def _create_fallback_client(self):
        """创建备用客户端（OpenAI 兼容）"""
        if self.fallback_api_key:
            logging.warning(f"切换到备用API: {self.fallback_base_url}, 模型: {self.fallback_model_name}")
            # 使用 OpenAI 客户端作为备用
            from openai import OpenAI
            return OpenAI(
                api_key=self.fallback_api_key,
                base_url=self.fallback_base_url,
                timeout=self.fallback_timeout,
                max_retries=0
            )
        return None

    def generate(self, prompt: str, max_tokens: Optional[int] = None, **kwargs) -> str:
        """生成文本（含重试，支持取消检查）

        Args:
            prompt: 提示词
            max_tokens: 最大生成token数
            **kwargs: 额外参数，如 temperature 等
        """
        max_attempts = 5
        last_error = None

        for attempt in range(1, max_attempts + 1):
            # 每次尝试前检查取消信号
            if self.cancel_checker and self.cancel_checker():
                raise InterruptedError("用户取消生成")

            try:
                return self._generate_once(prompt, max_tokens, **kwargs)
            except InterruptedError:
                raise
            except Exception as e:
                last_error = e
                logging.warning(f"生成失败 (尝试 {attempt}/{max_attempts}): {type(e).__name__}: {e}")

                # 对确定性错误（认证/授权失败）不再重试
                error_str = str(e).lower()
                is_permanent = any(kw in error_str for kw in [
                    "401", "403", "unauthorized", "forbidden",
                    "authentication", "invalid api key", "api_key"
                ])
                if is_permanent:
                    logging.error("检测到认证/授权错误，不再重试")
                    break

                if attempt < max_attempts:
                    wait = min(4 * (2 ** (attempt - 1)), 60)
                    logging.info(f"等待 {wait} 秒后重试...")
                    # 分段等待，每秒检查一次取消信号
                    for _ in range(int(wait)):
                        if self.cancel_checker and self.cancel_checker():
                            raise InterruptedError("用户取消生成")
                        time.sleep(1)

        raise last_error

    def _generate_once(self, prompt: str, max_tokens: Optional[int] = None, **kwargs) -> str:
        """单次生成尝试（支持取消检查）

        Args:
            prompt: 提示词
            max_tokens: 最大生成token数
            **kwargs: 额外参数，如 temperature 等
        """
        temperature = kwargs.get("temperature", self.temperature)
        logging.info(f"开始生成文本，模型: {self.model_name}, 提示词长度: {len(prompt)}, temperature: {temperature}")

        try:
            # 如果提示词太长，进行截断
            max_prompt_length = 180000  # Claude 支持更长的上下文
            if len(prompt) > max_prompt_length:
                original_length = len(prompt)
                truncated_chars = original_length - max_prompt_length
                logging.warning(
                    f"提示词过长 ({original_length} 字符)，截断到 {max_prompt_length} 字符。"
                    f"丢失尾部 {truncated_chars} 字符（占比 {truncated_chars/original_length*100:.1f}%）"
                )
                prompt = prompt[:max_prompt_length]

            content = self._cancellable_call(
                self._generate_with_claude_api,
                self.client,
                self.model_name,
                prompt,
                max_tokens,
                temperature
            )

            logging.info(f"文本生成成功，返回内容长度: {len(content)}")
            return content

        except Exception as e:
            logging.error(f"Claude generation error: {str(e)}")

            # 检测可通过备用模型恢复的错误
            error_str = str(e).lower()
            should_fallback = any(keyword in error_str for keyword in [
                "timeout", "connection", "429", "rate limit",
                "500", "502", "503", "504", "internal error",
                "server error", "service unavailable", "bad gateway",
                "overloaded", "capacity",
                "401", "403", "unauthorized", "forbidden", "authentication",
                "api key", "invalid"
            ])

            if should_fallback and self.fallback_api_key:
                logging.warning("检测到服务端错误，尝试使用备用API...")
                fallback_client = self._create_fallback_client()
                if fallback_client:
                    try:
                        # 使用 OpenAI 兼容接口
                        response = fallback_client.chat.completions.create(
                            model=self.fallback_model_name,
                            messages=[{"role": "user", "content": prompt}],
                            max_tokens=max_tokens,
                            temperature=temperature,
                            timeout=self.fallback_timeout
                        )

                        content = response.choices[0].message.content
                        if not content:
                            raise Exception("备用API返回空内容")

                        logging.info(f"使用备用API生成成功，返回内容长度: {len(content)}")
                        return content
                    except Exception as fallback_error:
                        logging.error(f"备用API也失败了: {str(fallback_error)}")

            raise Exception(f"Claude generation error: {str(e)}")

    def embed(self, text: str) -> np.ndarray:
        """获取文本嵌入向量

        注意：Claude API 不直接提供嵌入功能，此方法抛出 NotImplementedError
        如需嵌入功能，请使用 OpenAI 模型或其他支持嵌入的模型
        """
        raise NotImplementedError(
            "Claude API 不支持文本嵌入功能。"
            "请在配置中为 embedding 模型使用 OpenAI 兼容的模型。"
        )

    def close(self):
        """关闭模型客户端"""
        # Claude SDK 会自动管理连接
        logging.debug("Claude model client closed")

    def __del__(self):
        """析构函数，确保资源清理"""
        try:
            self.close()
        except Exception:
            pass
