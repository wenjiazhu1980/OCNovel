# Claude 模型集成指南

## 概述

OCNovel 现已支持 Anthropic Claude 模型作为大纲生成和内容生成的选项。Claude 模型以其强大的推理能力和长上下文支持（最高 200K tokens）著称，特别适合复杂的小说创作任务。

## 支持的模型

- `claude-3-5-sonnet-20241022` (推荐) - 平衡性能和成本
- `claude-3-opus-20240229` - 最强性能
- `claude-3-haiku-20240307` - 快速响应

## 配置步骤

### 1. 获取 API 密钥

访问 [Anthropic Console](https://console.anthropic.com/) 获取 API 密钥。

### 2. 配置环境变量

在项目根目录的 `.env` 文件中添加以下配置：

```bash
# Claude API 配置
CLAUDE_API_KEY=your_api_key_here
CLAUDE_OUTLINE_MODEL=claude-3-5-sonnet-20241022
CLAUDE_CONTENT_MODEL=claude-3-5-sonnet-20241022
CLAUDE_TIMEOUT=120
CLAUDE_RETRY_DELAY=10

# 可选：备用模型配置（当 Claude API 失败时使用）
CLAUDE_FALLBACK_ENABLED=True
FALLBACK_API_KEY=your_fallback_api_key
FALLBACK_API_BASE=https://api.siliconflow.cn/v1
FALLBACK_MODEL=Qwen/Qwen2.5-7B-Instruct
```

### 3. 配置小说项目

在 `config.json` 中指定使用 Claude 模型：

```json
{
  "model_config": {
    "outline_model": "claude_outline",
    "content_model": "claude_content"
  }
}
```

## 使用示例

### 生成大纲

```bash
python main.py outline --start 1 --end 10
```

### 生成内容

```bash
python main.py content --start-chapter 1
```

### 全流程自动生成

```bash
python main.py auto
```

## 特性说明

### 1. 长上下文支持

Claude 模型支持最高 200K tokens 的上下文窗口，相比其他模型有显著优势：

- **OpenAI GPT-4**: ~8K-32K tokens
- **Gemini Pro**: ~32K tokens
- **Claude 3.5 Sonnet**: ~200K tokens

这意味着可以在生成时提供更多的背景信息和参考内容。

### 2. 流式输出

Claude 模型支持流式输出，可以实时查看生成进度，提升用户体验。

### 3. 备用模型机制

当 Claude API 出现以下情况时，会自动切换到备用模型：

- 超时
- 速率限制 (429)
- 服务器错误 (500, 502, 503, 504)
- 认证失败 (401, 403)

### 4. 取消支持

支持在生成过程中取消操作，避免长时间等待。

## 注意事项

### 1. 嵌入模型限制

⚠️ **重要**: Claude API 不支持文本嵌入功能。如果需要使用知识库功能，必须配置 OpenAI 兼容的嵌入模型：

```bash
# 必须配置嵌入模型
OPENAI_EMBEDDING_API_KEY=your_embedding_api_key
OPENAI_EMBEDDING_API_BASE=https://api.siliconflow.cn/v1
OPENAI_EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B
```

### 2. API 限制

Claude API 有以下限制：

- **max_tokens**: 最大 8192 tokens（单次生成）
- **速率限制**: 根据订阅计划不同而异
- **成本**: 相比开源模型成本较高

### 3. 提示词长度

虽然 Claude 支持长上下文，但系统会自动截断过长的提示词（>180K 字符）以确保稳定性。

## 成本估算

以 Claude 3.5 Sonnet 为例（2024年价格）：

- **输入**: $3 / 1M tokens
- **输出**: $15 / 1M tokens

生成一部 100 章的小说（每章 3000 字）：

- 输入约 30M tokens: $90
- 输出约 30M tokens: $450
- **总计**: ~$540

建议：
- 开发测试阶段使用开源模型（如 Qwen）
- 正式创作时使用 Claude 提升质量

## 故障排查

### 问题 1: 认证失败

```
Error: 401 Unauthorized
```

**解决方案**: 检查 `CLAUDE_API_KEY` 是否正确配置。

### 问题 2: 速率限制

```
Error: 429 Too Many Requests
```

**解决方案**: 
1. 增加 `CLAUDE_RETRY_DELAY` 值
2. 配置备用模型
3. 升级 API 订阅计划

### 问题 3: 超时

```
Error: Timeout
```

**解决方案**:
1. 增加 `CLAUDE_TIMEOUT` 值（默认 120 秒）
2. 检查网络连接
3. 配置备用模型

### 问题 4: 嵌入功能报错

```
NotImplementedError: Claude API 不支持文本嵌入功能
```

**解决方案**: 配置 OpenAI 兼容的嵌入模型（见上文"嵌入模型限制"）。

## 最佳实践

1. **混合使用**: 大纲使用 Claude，内容生成使用开源模型，平衡质量和成本
2. **备用配置**: 始终配置备用模型，确保服务稳定性
3. **监控成本**: 定期检查 API 使用量，避免超支
4. **批量生成**: 使用 `auto` 命令批量生成，减少 API 调用次数

## 相关文档

- [Anthropic API 文档](https://docs.anthropic.com/)
- [Claude 模型对比](https://www.anthropic.com/claude)
- [OCNovel 配置指南](../CLAUDE.md)
