# CLAUDE.md - OCNovel

## Project Overview

AI小说自动生成系统，支持东方玄幻/仙侠/武侠等类型。Python 3.9+，CLI 驱动。

## Architecture

```
main.py                          # CLI入口，argparse子命令
src/
  config/
    config.py                    # Config类，加载config.json + .env
    ai_config.py                 # AIConfig类，多模型配置(Gemini/OpenAI)
  models/
    base_model.py                # BaseModel ABC: generate() + embed()
    openai_model.py              # OpenAI兼容实现
    gemini_model.py              # Google Gemini实现
  generators/
    outline/outline_generator.py # 大纲生成
    content/content_generator.py # 章节内容生成
    content/consistency_checker.py
    content/validators.py
    finalizer/finalizer.py       # 定稿处理
    prompts.py                   # Prompt模板
    humanization_prompts.py      # 人性化Prompt
    title_generator.py
    common/data_structures.py
    common/utils.py              # setup_logging等工具
  knowledge_base/
    knowledge_base.py            # 知识库，ChromaDB + FAISS向量检索
  tools/
    generate_config.py
    generate_marketing.py
    ai_density_checker.py        # AI浓度检测
data/                            # 运行时数据（gitignored）
  cache/ output/ logs/ reference/ style_sources/
```

## Key Patterns

- **Model abstraction**: `BaseModel` ABC → `OpenAIModel` / `GeminiModel`。
- **Config layering**: `config.json`（小说参数） + `.env`（API密钥/敏感配置） + `AIConfig`（模型默认值）。`config.json`中的`model_config`优先级高于AIConfig defaults。
- **Pipeline**: outline → content → finalize，通过`auto`命令串联。
- **Retry/Fallback**: tenacity重试 + 备用模型机制。
- **Knowledge Base**: 文本分块 → 嵌入(Qwen3-Embedding) → ChromaDB/FAISS向量检索 → Reranker。
- **Sensitive data sanitization**: `_sanitize_config_for_logging()` 过滤API key日志输出。

## Commands

```bash
python main.py outline --start 1 --end 10        # 生成大纲
python main.py content --start-chapter 3          # 从第3章续写
python main.py content --target-chapter 5         # 重生成第5章
python main.py finalize --chapter 8               # 定稿
python main.py auto                               # 全流程
python main.py auto --force-outline               # 强制重生成大纲
python main.py imitate --style-source ... --input-file ... --output-file ...
```

## Development Rules

- **Language**: 代码注释和用户输出使用中文；变量名/函数名使用英文。
- **No tests directory**: tests/已被gitignore，当前无测试框架。
- **Config files gitignored**: `config*.json`和`.env`不入库，仅`config.json.example`和`.env.example`入库。
- **data/ gitignored**: 所有运行时产出不入版本控制。
- **Dependencies**: `requirements.txt`管理，核心依赖见其中。
- **Env vars**: API密钥严禁硬编码，一律通过`.env`管理。

## Git Conventions

- Commit message使用中文，格式: `type(scope): 描述`
- Types: `feat`, `fix`, `docs`, `chore`, `refactor`
- Branch: `dev`为开发分支，`main`为主分支
