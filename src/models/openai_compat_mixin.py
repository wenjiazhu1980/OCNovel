"""OpenAI 兼容 API 共用工具方法

OpenAIModel 和 GeminiModel 共享的响应解析逻辑。
两者都使用 OpenAI SDK 的 Chat Completions / Responses API 接口，
响应格式完全一致，因此解析方法可以共用。
"""
from typing import Any, Optional


class OpenAICompatMixin:
    """OpenAI 兼容 API 的响应解析工具方法（被 OpenAIModel 和 GeminiModel 共用）"""

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
