from openai import OpenAI
import numpy as np
import time
import concurrent.futures
from typing import Optional, Dict, Any
from tenacity import retry, stop_after_attempt, wait_fixed, wait_exponential
from .base_model import BaseModel
import logging
import json
import time
import os

# 导入网络管理相关模块
try:
    from ..network.config import PoolConfig
    from ..network.model_client import ModelHTTPClient, ModelClientFactory
    from ..network.errors import NetworkError, TimeoutError, ConnectionError
    NETWORK_AVAILABLE = True
except ImportError:
    NETWORK_AVAILABLE = False
    # 使用标准HTTP客户端

class OpenAIModel(BaseModel):
    """OpenAI模型实现"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._validate_config()
        self.api_mode = "auto"
        self.reasoning_enabled = config.get("reasoning_enabled", False)
        self.cancel_checker = None  # 可选：外部注入的取消检查回调
        self._init_standard_client(config)
            
    def _init_standard_client(self, config: Dict[str, Any]):
        """初始化标准OpenAI客户端（原有逻辑）"""
        # 增加超时时间，特别是对于本地服务器
        timeout = config.get("timeout", 120)  # 默认120秒
        base_url = config.get("base_url", "https://api.siliconflow.cn/v1")
        
        # 备用API配置
        self.fallback_base_url = os.getenv("FALLBACK_API_BASE", "https://api.siliconflow.cn/v1")
        self.fallback_api_key = os.getenv("FALLBACK_API_KEY", "")  # 使用独立的备用API密钥
        # 根据当前模型类型选择备用模型
        if "gemini-2.5-flash" in self.model_name:
            self.fallback_model_name = "moonshotai/Kimi-K2-Instruct"  # 使用Kimi-K2作为gemini-2.5-flash的备用
        elif "gemini-2.5-pro" in self.model_name:
            self.fallback_model_name = "Qwen/Qwen3-235B-A22B-Thinking-2507"  # 使用Qwen作为gemini-2.5-pro的备用
        else:
            self.fallback_model_name = "deepseek-ai/DeepSeek-V3"  # 默认备用模型

        self.api_mode = str(config.get("api_mode", "auto")).strip().lower()
        if self.api_mode not in {"auto", "chat", "responses"}:
            logging.warning(f"未知 API 模式: {self.api_mode}，已回退为 auto")
            self.api_mode = "auto"
        
        # 初始化网络管理客户端（如果可用）
        if NETWORK_AVAILABLE:
            # 创建连接池配置
            pool_config = PoolConfig(
                max_connections=config.get("max_connections", 100),
                max_connections_per_host=config.get("max_connections_per_host", 10),
                connection_timeout=config.get("connection_timeout", 30.0),
                read_timeout=config.get("read_timeout", timeout),
                idle_timeout=config.get("idle_timeout", 300.0),
                enable_http2=config.get("enable_http2", True),
                enable_keepalive=config.get("enable_keepalive", True)
            )
            
            # 创建网络管理客户端
            self.network_client = ModelClientFactory.create_openai_client(
                base_url=base_url,
                api_key=config["api_key"],
                pool_config=pool_config,
                timeout=timeout
            )
            
            # 创建备用客户端
            if self.fallback_api_key:
                self.fallback_network_client = ModelClientFactory.create_openai_client(
                    base_url=self.fallback_base_url,
                    api_key=self.fallback_api_key,
                    pool_config=pool_config,
                    timeout=180  # 备用API使用更长的超时时间
                )
            else:
                self.fallback_network_client = None
            
            logging.info(f"OpenAI model initialized with network management: {base_url}, timeout: {timeout}s")
        else:
            # 回退到原始OpenAI客户端
            self.network_client = None
            self.fallback_network_client = None
            
        # 保持原始客户端作为备用
        self.client = OpenAI(
            api_key=config["api_key"],
            base_url=base_url,
            timeout=timeout
        )
        logging.info(f"OpenAI model initialized with base URL: {base_url}, timeout: {timeout}s")
        
    def _process_thinking_output(self, content: str) -> str:
        """处理包含思考过程的输出"""
        # 提取思考过程和最终答案
        if "<thinking>" in content and "</thinking>" in content:
            # 记录思考过程用于调试
            thinking_start = content.find("<thinking>")
            thinking_end = content.find("</thinking>") + len("</thinking>")
            thinking_process = content[thinking_start:thinking_end]
            
            logging.debug(f"深度思考过程: {thinking_process[:500]}...")
            
            # 返回思考标签后的内容作为最终答案
            final_answer = content[thinking_end:].strip()
            if final_answer:
                return final_answer
            else:
                # 如果没有思考标签后的内容，返回整个内容
                return content
        
        return content

    def _supports_responses_api(self, client: Any) -> bool:
        """检测当前客户端是否支持 Responses API"""
        responses_attr = getattr(client, "responses", None)
        return responses_attr is not None and hasattr(responses_attr, "create")

    def _extract_chat_content(self, response: Any) -> Optional[str]:
        """从 Chat Completions 响应中提取文本"""
        content = response.choices[0].message.content
        if isinstance(content, str):
            return content

        # 兼容 content 为结构化数组的情况
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue

                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text:
                        parts.append(text)
                    continue

                text = getattr(item, "text", None)
                if isinstance(text, str) and text:
                    parts.append(text)

            merged = "".join(parts).strip()
            return merged or None

        return None

    def _extract_responses_content(self, response: Any) -> Optional[str]:
        """从 Responses API 响应中提取文本"""
        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str):
            cleaned = output_text.strip()
            if cleaned:
                return cleaned

        output_items = getattr(response, "output", None)
        if not output_items:
            return None

        chunks = []
        for item in output_items:
            content_blocks = getattr(item, "content", None)
            if content_blocks is None and isinstance(item, dict):
                content_blocks = item.get("content")
            if not content_blocks:
                continue

            for block in content_blocks:
                text = getattr(block, "text", None)
                if text is None and isinstance(block, dict):
                    text = block.get("text")

                if isinstance(text, str) and text:
                    chunks.append(text)
                    continue

                nested_text = getattr(text, "value", None)
                if nested_text is None and isinstance(text, dict):
                    nested_text = text.get("value")
                if isinstance(nested_text, str) and nested_text:
                    chunks.append(nested_text)

        merged = "".join(chunks).strip()
        return merged or None

    def _is_reasoning_enabled(self) -> bool:
        """检查是否启用推理模式"""
        return bool(self.reasoning_enabled)

    def _generate_with_chat_api(
        self,
        client: Any,
        model_name: str,
        prompt: str,
        max_tokens: Optional[int],
        temperature: float
    ) -> str:
        # 限制 max_tokens 不超过模型常见上限
        if max_tokens and max_tokens > 16384:
            logging.warning(f"max_tokens ({max_tokens}) 过大，已限制为 16384")
            max_tokens = 16384
        params = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        if max_tokens:
            params["max_tokens"] = max_tokens
        if self._is_reasoning_enabled():
            logging.info("Chat API 推理模式已启用，由模型自行决定推理强度")

        response = client.chat.completions.create(**params)

        content = self._extract_chat_content(response)
        if content is None:
            raise Exception("Chat Completions 返回空内容")
        return content

    def _generate_with_responses_api(
        self,
        client: Any,
        model_name: str,
        prompt: str,
        max_tokens: Optional[int],
        temperature: float
    ) -> str:
        if not self._supports_responses_api(client):
            raise Exception("当前 openai SDK 不支持 Responses API，请升级到 openai>=1.66.0")

        request_data = {
            "model": model_name,
            "input": prompt,
            "temperature": temperature,
        }
        if max_tokens is not None:
            if max_tokens > 16384:
                logging.warning(f"max_output_tokens ({max_tokens}) 过大，已限制为 16384")
                max_tokens = 16384
            request_data["max_output_tokens"] = max_tokens
        if self._is_reasoning_enabled():
            logging.info("Responses API 推理模式已启用，由模型自行决定推理强度")

        response = client.responses.create(**request_data)
        content = self._extract_responses_content(response)
        if content is None:
            raise Exception("Responses API 返回空内容")
        return content

    def _generate_with_compatible_api(
        self,
        client: Any,
        model_name: str,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        api_mode: Optional[str] = None
    ) -> str:
        """兼容 Chat Completions 与 Responses 两种接口"""
        mode = (api_mode or self.api_mode).strip().lower()
        if mode not in {"auto", "chat", "responses"}:
            mode = "auto"

        if mode == "chat":
            return self._generate_with_chat_api(client, model_name, prompt, max_tokens, temperature)

        if mode == "responses":
            return self._generate_with_responses_api(client, model_name, prompt, max_tokens, temperature)

        # auto: 优先尝试 Responses，不可用或失败时回退 Chat
        if self._supports_responses_api(client):
            try:
                return self._generate_with_responses_api(
                    client, model_name, prompt, max_tokens, temperature
                )
            except Exception as responses_error:
                logging.warning(f"Responses API 调用失败，回退 Chat Completions: {responses_error}")
        else:
            logging.info("当前客户端不支持 Responses API，自动使用 Chat Completions")

        return self._generate_with_chat_api(client, model_name, prompt, max_tokens, temperature)
    
    def _create_fallback_client(self):
        """创建备用客户端"""
        if self.fallback_api_key:
            logging.warning(f"切换到备用API: {self.fallback_base_url}, 模型: {self.fallback_model_name}")
            return OpenAI(
                api_key=self.fallback_api_key,
                base_url=self.fallback_base_url,
                timeout=180  # 备用API使用更长的超时时间
            )
        return None
    
    def _generate_with_fallback(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        """使用备用模型生成文本"""
        logging.warning(f"切换到备用模型: {self.fallback_model_name}")
        
        fallback_client = OpenAI(
            api_key=self.fallback_api_key,
            base_url=self.fallback_base_url,
            timeout=180
        )
        
        try:
            content = self._generate_with_compatible_api(
                fallback_client,
                self.fallback_model_name,
                prompt,
                max_tokens=max_tokens or 8192,
                temperature=0.7,
                api_mode="auto"
            )
                
            logging.info(f"备用模型生成成功，返回内容长度: {len(content)}")
            return content
            
        except Exception as fallback_error:
            logging.error(f"备用模型也失败了: {str(fallback_error)}")
            raise fallback_error
    
    def _use_network_client_for_generation(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        """使用网络管理客户端进行文本生成"""
        try:
            # 如果提示词太长，进行截断
            max_prompt_length = 65536  # 设置最大提示词长度
            if len(prompt) > max_prompt_length:
                original_length = len(prompt)
                truncated_chars = original_length - max_prompt_length
                logging.warning(
                    f"[网络客户端] 提示词过长 ({original_length} 字符)，截断到 {max_prompt_length} 字符。"
                    f"丢失尾部 {truncated_chars} 字符（占比 {truncated_chars/original_length*100:.1f}%）"
                )
                prompt = prompt[:max_prompt_length]

            messages = [{"role": "user", "content": prompt}]

            # 使用网络管理客户端
            response_data = self.network_client.chat_completion(
                model=self.model_name,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.7
            )
            
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
                        temperature=0.7
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
    
    def _use_network_client_for_embedding(self, text: str) -> np.ndarray:
        """使用网络管理客户端获取嵌入向量"""
        try:
            logging.info(f"使用网络管理客户端生成嵌入向量，文本长度: {len(text)}")
            
            response_data = self.network_client.embeddings(
                model=self.model_name,
                input_text=text
            )
            
            # 解析响应
            if 'data' in response_data and len(response_data['data']) > 0:
                embedding = np.array(response_data['data'][0]['embedding'])
                logging.info(f"网络管理客户端成功生成嵌入向量，维度: {len(embedding)}")
                return embedding
            else:
                logging.error("嵌入响应数据为空或无效")
                raise Exception("嵌入响应数据为空或无效")
                
        except (NetworkError, TimeoutError, ConnectionError) as e:
            logging.error(f"网络管理客户端嵌入失败: {str(e)}")
            raise e
        except Exception as e:
            logging.error(f"网络管理客户端嵌入出现未知错误: {str(e)}")
            raise e
        
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
                    raise  # 子线程异常直接抛出
            return future.result()

    def generate(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        """生成文本（含重试，支持取消检查）"""
        max_attempts = 5
        last_error = None

        for attempt in range(1, max_attempts + 1):
            # 每次尝试前检查取消信号
            if self.cancel_checker and self.cancel_checker():
                raise InterruptedError("用户取消生成")

            try:
                return self._generate_once(prompt, max_tokens)
            except InterruptedError:
                raise
            except Exception as e:
                last_error = e
                logging.warning(f"生成失败 (尝试 {attempt}/{max_attempts}): {type(e).__name__}: {e}")
                if attempt < max_attempts:
                    wait = min(4 * (2 ** (attempt - 1)), 60)
                    logging.info(f"等待 {wait} 秒后重试...")
                    # 分段等待，每秒检查一次取消信号
                    for _ in range(int(wait)):
                        if self.cancel_checker and self.cancel_checker():
                            raise InterruptedError("用户取消生成")
                        time.sleep(1)

        raise last_error

    def _generate_once(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        """单次生成尝试（支持取消检查）"""
        logging.info(f"开始生成文本，模型: {self.model_name}, 提示词长度: {len(prompt)}")

        # 优先使用网络管理客户端（该客户端只支持 chat/completions）
        if NETWORK_AVAILABLE and self.network_client and self.api_mode != "responses":
            try:
                return self._cancellable_call(
                    self._use_network_client_for_generation, prompt, max_tokens)
            except InterruptedError:
                raise
            except Exception as e:
                logging.warning(f"网络管理客户端失败，回退到原始客户端: {str(e)}")
        
        # 回退到原始实现
        try:
            # 如果提示词太长，进行截断
            max_prompt_length = 65536  # 设置最大提示词长度
            if len(prompt) > max_prompt_length:
                original_length = len(prompt)
                truncated_chars = original_length - max_prompt_length
                logging.warning(
                    f"[原始客户端] 提示词过长 ({original_length} 字符)，截断到 {max_prompt_length} 字符。"
                    f"丢失尾部 {truncated_chars} 字符（占比 {truncated_chars/original_length*100:.1f}%）"
                )
                prompt = prompt[:max_prompt_length]
            
            content = self._cancellable_call(
                self._generate_with_compatible_api,
                self.client,
                self.model_name,
                prompt,
                max_tokens=max_tokens,
                temperature=0.7
            )
                
            logging.info(f"文本生成成功，返回内容长度: {len(content)}")
            return content
            
        except Exception as e:
            logging.error(f"OpenAI generation error: {str(e)}")
            
            # 如果是连接错误且配置了备用API，尝试使用备用API
            if ("timeout" in str(e).lower() or "connection" in str(e).lower()) and self.fallback_api_key:
                logging.warning("检测到连接错误，尝试使用备用API...")
                fallback_client = self._create_fallback_client()
                if fallback_client:
                    try:
                        content = self._generate_with_compatible_api(
                            fallback_client,
                            self.fallback_model_name,
                            prompt,
                            max_tokens=max_tokens,
                            temperature=0.7,
                            api_mode="auto"
                        )
                            
                        logging.info(f"使用备用API生成成功，返回内容长度: {len(content)}")
                        return content
                    except Exception as fallback_error:
                        logging.error(f"备用API也失败了: {str(fallback_error)}")
            
            if "timeout" in str(e).lower() or "connection" in str(e).lower():
                logging.warning("检测到超时或连接错误，将重试...")
                time.sleep(5)  # 等待5秒后重试
            raise Exception(f"OpenAI generation error: {str(e)}")
            
    @retry(stop=stop_after_attempt(3), wait=wait_fixed(10))
    def embed(self, text: str) -> np.ndarray:
        """获取文本嵌入向量"""
        logging.info(f"生成嵌入向量，文本长度: {len(text)}")
        logging.info(f"使用模型: {self.model_name}")
        
        # 优先使用网络管理客户端
        if NETWORK_AVAILABLE and self.network_client:
            try:
                return self._use_network_client_for_embedding(text)
            except Exception as e:
                logging.warning(f"网络管理客户端嵌入失败，回退到原始客户端: {str(e)}")
        
        # 回退到原始实现
        try:
            # 打印请求信息
            request_data = {
                "model": self.model_name,
                "input": text[:100] + "..." if len(text) > 100 else text  # 只打印前100个字符
            }
            logging.info(f"Request data: {json.dumps(request_data, ensure_ascii=False)}")
            
            try:
                response = self.client.embeddings.create(
                    model=self.model_name,
                    input=text
                )
                
                # 打印响应信息
                if hasattr(response, 'data') and len(response.data) > 0:
                    embedding = np.array(response.data[0].embedding)
                    logging.info(f"Successfully generated embedding with dimension {len(embedding)}")
                    return embedding
                else:
                    logging.error("Response data is empty or invalid")
                    logging.error(f"Response: {response}")
                    raise Exception("Embedding response is empty or invalid")
                    
            except Exception as api_error:
                logging.error(f"API call failed: {str(api_error)}")
                # 检查是否有response属性（OpenAI API错误通常有）
                if hasattr(api_error, 'response') and api_error.response is not None:
                    logging.error(f"Response status: {api_error.response.status_code}")
                    logging.error(f"Response body: {api_error.response.text}")
                raise
                
        except Exception as e:
            logging.error(f"OpenAI embedding error: {str(e)}")
            raise
    
    def close(self):
        """关闭模型客户端"""
        if NETWORK_AVAILABLE:
            if self.network_client:
                self.network_client.close()
            if self.fallback_network_client:
                self.fallback_network_client.close()
        logging.debug("OpenAI model clients closed")
    
    def __del__(self):
        """析构函数，确保资源清理"""
        try:
            self.close()
        except Exception:
            pass
