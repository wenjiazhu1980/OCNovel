import google.generativeai as genai
import numpy as np
import time
import logging
import os
import threading
from typing import Optional, Dict, Any
from tenacity import retry, stop_after_attempt, wait_exponential
from .base_model import BaseModel
from .openai_compat_mixin import OpenAICompatMixin

# 导入网络管理相关模块
try:
    from ..network.config import PoolConfig
    from ..network.model_client import ModelHTTPClient, ModelClientFactory
    from ..network.errors import NetworkError, TimeoutError, ConnectionError
    NETWORK_AVAILABLE = True
except ImportError:
    NETWORK_AVAILABLE = False
    # 使用标准HTTP客户端

class GeminiModel(OpenAICompatMixin, BaseModel):
    """Gemini模型实现，支持官方和OpenAI兼容API分流"""

    # 类级别的锁，保护 genai.configure() 全局状态
    _configure_lock = threading.Lock()
    _configured_api_key: Optional[str] = None
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._validate_config()
        self.model_name = config.get('model_name', 'gemini-2.5-flash')
        self.temperature = config.get('temperature', 1.0)
        self.timeout = config.get('timeout', 60)
        self.retry_delay = config.get('retry_delay', 30)
        self.max_retries = config.get('max_retries', 5)
        self.cancel_checker = None  # 可选：外部注入的取消检查回调
        self.max_input_length = config.get('max_input_length', 500000)
        self.api_key = config.get('api_key', None)

        # Gemini 仅支持官方 API，不支持自定义 base_url
        self.is_gemini_official = True
        logging.info(f"使用 Google 官方 Gemini API 调用模型: {self.model_name}")

        # 备用模型配置
        self._setup_fallback_config()

        # Gemini 官方 API 不使用网络管理客户端
        self.network_client = None
        self.fallback_network_client = None

        # 初始化模型客户端
        if self.is_gemini_official:
            # 线程安全地配置 genai 全局 API Key
            with GeminiModel._configure_lock:
                if GeminiModel._configured_api_key != self.api_key:
                    genai.configure(api_key=self.api_key)
                    GeminiModel._configured_api_key = self.api_key
                    logging.debug("genai.configure() 已更新 API Key")
            
            # 导入安全配置管理器
            from .gemini_safety_config import GeminiSafetyConfig
            
            # 获取安全设置
            content_type = config.get('content_type', 'creative')
            self.safety_settings = GeminiSafetyConfig.get_safety_settings_for_content_type(content_type)
            
            self.model = genai.GenerativeModel(
                self.model_name,
                safety_settings=self.safety_settings
            )
            logging.info(f"Gemini模型初始化完成，使用{content_type}内容类型的安全设置")
        else:
            # OpenAI兼容API客户端（保持作为备用）
            try:
                from openai import OpenAI
                self.openai_client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url,
                    timeout=self.timeout
                )
            except ImportError:
                self.openai_client = None
                logging.error("OpenAI库未安装，无法使用OpenAI兼容API模型")

    def _setup_fallback_config(self):
        """设置备用模型配置"""
        fallback_enabled = self.config.get("fallback_enabled", True)
        if not fallback_enabled:
            self.fallback_api_key = ""
            self.fallback_base_url = ""
            self.fallback_model_name = ""
            logging.info("Gemini模型备用功能已禁用")
            return
        self.fallback_base_url = self.config.get("fallback_base_url", os.getenv("FALLBACK_API_BASE", "https://api.siliconflow.cn/v1"))
        self.fallback_api_key = self.config.get("fallback_api_key", os.getenv("FALLBACK_API_KEY", ""))
        self.fallback_model_name = self.config.get("fallback_model", os.getenv("FALLBACK_MODEL_ID", "Qwen/Qwen2.5-7B-Instruct"))
        logging.info(f"Gemini模型备用配置: {self.fallback_model_name}")

    def _truncate_prompt(self, prompt: str) -> str:
        if len(prompt) <= self.max_input_length:
            return prompt
        original_length = len(prompt)
        keep_start = int(self.max_input_length * 0.7)
        keep_end = int(self.max_input_length * 0.2)
        truncated_middle = original_length - keep_start - keep_end
        logging.warning(
            f"提示词长度 ({original_length}) 超过限制 ({self.max_input_length})，将进行截断。"
            f"保留前 {keep_start} 字符 + 后 {keep_end} 字符，"
            f"中间 {truncated_middle} 字符已丢失（占比 {truncated_middle/original_length*100:.1f}%）"
        )
        truncated = prompt[:keep_start] + "\n\n[内容过长，已截断中间部分...]\n\n" + prompt[-keep_end:]
        logging.info(f"截断后长度: {len(truncated)}")
        return truncated

    def _generate_with_chat_api(
        self,
        client: Any,
        model_name: str,
        prompt: str,
        max_tokens: Optional[int],
        temperature: Optional[float] = None,
        top_p: Optional[float] = None
    ) -> str:
        _temp = temperature if temperature is not None else self.temperature
        params = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": _temp
        }
        if top_p is not None:
            params["top_p"] = top_p
        response = client.chat.completions.create(**params)
        content = self._extract_chat_content(response)
        if not content:
            raise Exception("Chat Completions 返回空内容")
        return content

    def _generate_with_responses_api(
        self,
        client: Any,
        model_name: str,
        prompt: str,
        max_tokens: Optional[int],
        temperature: Optional[float] = None
    ) -> str:
        if not self._supports_responses_api(client):
            raise Exception("当前 openai SDK 不支持 Responses API，请升级到 openai>=1.66.0")

        _temp = temperature if temperature is not None else self.temperature
        request_data = {
            "model": model_name,
            "input": prompt,
            "temperature": _temp,
        }
        if max_tokens is not None:
            request_data["max_output_tokens"] = max_tokens

        response = client.responses.create(**request_data)
        content = self._extract_responses_content(response)
        if not content:
            raise Exception("Responses API 返回空内容")
        return content

    def _generate_with_compatible_api(
        self,
        client: Any,
        model_name: str,
        prompt: str,
        max_tokens: Optional[int] = None,
        api_mode: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None
    ) -> str:
        mode = (api_mode or self.api_mode).strip().lower()
        if mode not in {"auto", "chat", "responses"}:
            mode = "auto"

        if mode == "chat":
            return self._generate_with_chat_api(client, model_name, prompt, max_tokens, temperature=temperature, top_p=top_p)

        if mode == "responses":
            return self._generate_with_responses_api(client, model_name, prompt, max_tokens, temperature=temperature)

        if self._supports_responses_api(client):
            try:
                return self._generate_with_responses_api(client, model_name, prompt, max_tokens, temperature=temperature)
            except Exception as responses_error:
                logging.warning(f"Responses API 调用失败，回退 Chat Completions: {responses_error}")
        else:
            logging.info("当前客户端不支持 Responses API，自动使用 Chat Completions")

        return self._generate_with_chat_api(client, model_name, prompt, max_tokens, temperature=temperature, top_p=top_p)
    
    def _use_network_client_for_generation(self, prompt: str, max_tokens: Optional[int] = None, temperature: Optional[float] = None, top_p: Optional[float] = None) -> str:
        """使用网络管理客户端进行文本生成（仅用于OpenAI兼容API）"""
        if self.is_gemini_official:
            raise Exception("官方Gemini模型不支持网络管理客户端")

        _temp = temperature if temperature is not None else self.temperature
        try:
            messages = [{"role": "user", "content": prompt}]

            # 构建请求参数
            request_kwargs = {
                "model": self.model_name,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": _temp
            }
            if top_p is not None:
                request_kwargs["top_p"] = top_p

            # 使用网络管理客户端
            response_data = self.network_client.chat_completion(**request_kwargs)
            
            content = response_data.get('choices', [{}])[0].get('message', {}).get('content')
            if content is None:
                raise Exception("模型返回空内容")
                
            logging.info(f"网络管理客户端生成成功，返回内容长度: {len(content)}")
            return content
            
        except (NetworkError, TimeoutError, ConnectionError) as e:
            logging.error(f"网络管理客户端生成失败: {str(e)}")
            
            # 如果配置了备用网络客户端，尝试使用
            if self.fallback_network_client:
                logging.warning("尝试使用备用网络客户端...")
                try:
                    response_data = self.fallback_network_client.chat_completion(
                        model=self.fallback_model_name,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=_temp
                    )
                    
                    content = response_data.get('choices', [{}])[0].get('message', {}).get('content')
                    if content is None:
                        raise Exception("备用模型返回空内容")
                        
                    logging.info(f"备用网络客户端生成成功，返回内容长度: {len(content)}")
                    return content
                    
                except Exception as fallback_error:
                    logging.error(f"备用网络客户端也失败了: {str(fallback_error)}")
            
            # 重新抛出原始异常
            raise e
        except Exception as e:
            logging.error(f"网络管理客户端生成出现未知错误: {str(e)}")
            raise e

    def generate(self, prompt: str, max_tokens: Optional[int] = None, **kwargs) -> str:
        """生成文本，支持官方Gemini和OpenAI兼容API分流

        Args:
            prompt: 提示词
            max_tokens: 最大生成token数
            **kwargs: 额外参数，如 temperature, top_p 等，用于覆盖模型默认值
        """
        # 从 kwargs 中提取采样参数，未指定则使用实例默认值
        effective_temperature = kwargs.get("temperature", self.temperature)
        effective_top_p = kwargs.get("top_p", None)
        last_exception = None
        prompt = self._truncate_prompt(prompt)
        if self.is_gemini_official:
            # 官方Gemini模型调用
            for attempt in range(self.max_retries):
                try:
                    logging.info(f"Gemini模型调用 (尝试 {attempt + 1}/{self.max_retries}), temperature: {effective_temperature}, top_p: {effective_top_p}")
                    generation_config = {"temperature": effective_temperature}
                    if effective_top_p is not None:
                        generation_config["top_p"] = effective_top_p
                    if max_tokens:
                        generation_config["max_output_tokens"] = max_tokens
                    response = self.model.generate_content(
                        prompt,
                        generation_config=generation_config,
                        request_options={"timeout": self.timeout}
                    )
                    
                    # 直接处理响应
                    from .gemini_safety_config import GeminiSafetyConfig
                    
                    # 检查响应是否有效
                    if not response or not response.candidates:
                        raise Exception("模型返回空响应或无候选结果")
                    
                    candidate = response.candidates[0]
                    
                    # 记录安全评级
                    if hasattr(candidate, 'safety_ratings') and candidate.safety_ratings:
                        safety_ratings = {}
                        for rating in candidate.safety_ratings:
                            safety_ratings[rating.category.name] = rating.probability.name
                        GeminiSafetyConfig.log_safety_ratings(safety_ratings)
                        logging.info(f"安全评级: {safety_ratings}")
                    
                    # 检查完成原因
                    finish_reason = candidate.finish_reason.name if hasattr(candidate, 'finish_reason') else 'UNKNOWN'
                    logging.info(f"完成原因: {finish_reason}")
                    
                    # 提取内容
                    if hasattr(candidate, 'content') and candidate.content and hasattr(candidate.content, 'parts'):
                        content_parts = []
                        for part in candidate.content.parts:
                            if hasattr(part, 'text') and part.text:
                                content_parts.append(part.text)
                        
                        if content_parts:
                            content = ''.join(content_parts)
                            logging.info(f"Gemini模型调用成功，内容长度: {len(content)}")
                            return content
                    
                    # 如果没有内容，提供详细错误信息
                    error_msg = f"模型返回空响应 - 完成原因: {finish_reason}"
                    if finish_reason == 'SAFETY':
                        error_msg += "\n建议: 内容可能触发了安全过滤器，请尝试修改提示词或调整安全设置"
                    elif finish_reason == 'MAX_TOKENS':
                        error_msg += "\n建议: 响应长度超过限制，请尝试增加max_tokens参数"
                    elif finish_reason == 'RECITATION':
                        error_msg += "\n建议: 内容可能涉及版权问题，请修改提示词"
                    
                    raise Exception(error_msg)
                except Exception as e:
                    last_exception = e
                    error_msg = str(e)
                    logging.error(f"Gemini模型调用失败 (尝试 {attempt + 1}/{self.max_retries}): {error_msg}")

                    # 对确定性错误（认证/授权失败）不再重试，直接跳出进入 fallback
                    error_lower = error_msg.lower()
                    is_permanent = any(kw in error_lower for kw in [
                        "401", "403", "unauthorized", "forbidden",
                        "authentication", "令牌", "invalid api key",
                        "api_key_invalid", "permission_denied"
                    ])
                    if is_permanent:
                        logging.error("检测到认证/授权错误，不再重试，尝试备用模型")
                        break

                    if "500" in error_msg or "internal error" in error_msg.lower():
                        delay = self.retry_delay * (attempt + 1) * 2
                    else:
                        delay = self.retry_delay * (attempt + 1)
                    if attempt < self.max_retries - 1:
                        logging.info(f"等待 {delay} 秒后重试...")
                        time.sleep(delay)
                    else:
                        logging.error(f"所有重试都失败了，最后一次错误: {str(e)}")
            # 官方模型失败后尝试 fallback
            if self.fallback_api_key:
                logging.warning("Gemini模型失败，尝试使用备用模型...")
                try:
                    from openai import OpenAI
                    fallback_client = OpenAI(
                        api_key=self.fallback_api_key,
                        base_url=self.fallback_base_url,
                        timeout=self.config.get("fallback_timeout", 180)
                    )
                    logging.info(f"使用备用模型: {self.fallback_model_name}")
                    content = self._generate_with_compatible_api(
                        fallback_client,
                        self.fallback_model_name,
                        prompt,
                        max_tokens=max_tokens,
                        api_mode="auto",
                        temperature=effective_temperature,
                        top_p=effective_top_p
                    )
                    if content:
                        logging.info(f"备用模型调用成功，返回内容长度: {len(content)}")
                        return content
                    else:
                        raise Exception("备用模型返回空响应")
                except Exception as fallback_error:
                    logging.error(f"备用模型也失败了: {str(fallback_error)}")
                    last_exception = fallback_error
            raise Exception(f"All models failed. Last error: {str(last_exception)}")
        else:
            # OpenAI兼容API模型调用
            # 优先使用网络管理客户端
            if NETWORK_AVAILABLE and self.network_client and self.api_mode != "responses":
                try:
                    return self._use_network_client_for_generation(prompt, max_tokens, temperature=effective_temperature, top_p=effective_top_p)
                except Exception as e:
                    logging.warning(f"网络管理客户端失败，回退到原始客户端: {str(e)}")
            
            # 回退到原始OpenAI客户端
            if not self.openai_client:
                raise Exception("OpenAI兼容API客户端未初始化，无法调用自定义模型")
            try:
                logging.info(f"直接调用OpenAI兼容API模型: {self.model_name}")
                content = self._generate_with_compatible_api(
                    self.openai_client,
                    self.model_name,
                    prompt,
                    max_tokens=max_tokens,
                    temperature=effective_temperature,
                    top_p=effective_top_p
                )
                if content:
                    logging.info(f"OpenAI兼容API模型调用成功，返回内容长度: {len(content)}")
                    return content
                else:
                    raise Exception("OpenAI兼容API模型返回空响应")
            except Exception as e:
                logging.error(f"OpenAI兼容API模型调用失败: {str(e)}")
                raise

    def embed(self, text: str) -> np.ndarray:
        raise NotImplementedError("Embedding is not supported in Gemini model yet")
    
    def close(self):
        """关闭模型客户端"""
        if NETWORK_AVAILABLE:
            if self.network_client:
                self.network_client.close()
            if self.fallback_network_client:
                self.fallback_network_client.close()
        logging.debug("Gemini model clients closed")
    
    def __del__(self):
        """析构函数，确保资源清理"""
        try:
            self.close()
        except Exception:
            pass
