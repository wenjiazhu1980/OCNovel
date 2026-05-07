# CLAUDE.md - OCNovel

## Project Overview

AI小说自动生成系统，支持东方玄幻/仙侠/武侠等类型。Python 3.9+，CLI + PySide6 GUI 双入口。

## Architecture

```
main.py                          # CLI入口，argparse子命令
gui_main.py                      # GUI入口（PySide6）
ocnovel.spec / ocnovel_win.spec  # PyInstaller macOS / Windows 打包配置
src/
  config/
    config.py                    # Config类，加载config.json + .env
    ai_config.py                 # AIConfig类，多模型配置(Claude/Gemini/OpenAI)
  models/
    base_model.py                # BaseModel ABC: generate() + embed()
    claude_model.py              # Anthropic Claude 实现
    gemini_model.py              # Google Gemini 实现
    gemini_safety_config.py      # Gemini 安全策略配置
    openai_model.py              # OpenAI 兼容实现
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
    knowledge_base.py            # 知识库，FAISS向量检索 + Reranker
  gui/                           # PySide6 可视化界面
    app.py                       # QApplication 工厂
    main_window.py               # 主窗口（3 Tab）
    theme.py
    i18n/                        # 中英文翻译（zh_CN / en_US）
    tabs/                        # model_config_tab / novel_params_tab / progress_tab
    workers/                     # pipeline_worker / connection_tester / marketing_worker / writing_guide_worker
    widgets/                     # log_viewer / chapter_list
    utils/                       # config_io / log_handler / resource_path / platform_utils / fonts
  tools/
    generate_config.py
    generate_marketing.py
    ai_density_checker.py        # AI浓度检测
data/                            # 运行时数据（gitignored）
  cache/ output/ logs/ reference/ style_sources/
```

## Key Patterns

- **Model abstraction**: `BaseModel` ABC → `ClaudeModel` / `GeminiModel` / `OpenAIModel`。
- **Config layering**: `config.json`（小说参数） + `.env`（API密钥/敏感配置） + `AIConfig`（模型默认值）。`config.json`中的`model_config`优先级高于AIConfig defaults。
- **Pipeline**: outline → content → finalize，通过`auto`命令串联（CLI 和 GUI `pipeline_worker` 共用）。
- **Retry/Fallback**: tenacity重试 + 备用模型机制。
- **Knowledge Base**: 文本分块 → 嵌入(OpenAI 兼容 Embedding) → FAISS 向量检索 → Reranker API。Claude 不支持嵌入，需额外配置 OpenAI 兼容的嵌入模型。
- **GUI**: PySide6 三 Tab 界面（模型配置 / 小说参数 / 创作进度），`pipeline_worker` 后台线程运行生成流水线，`log_handler` 将 `logging` 桥接到 Qt Signal 实时输出。支持中英双语切换（i18n .qm 文件）。
- **Sensitive data sanitization**: `_sanitize_config_for_logging()` 过滤API key日志输出。
- **稀疏大纲与自动补洞**: `outline.json` 支持 `None` 占位的稀疏列表（`b8267c7`），生成失败章节不丢空槽。`_outline_discontinuous` 检测缺洞后由 `OutlineGenerator.patch_missing_chapters()` 单一权威实现补洞（多轮重试 + 一致性检查 + 即时落盘）。CLI 工具 `tools/fill_outline_gaps.py` 与 `pipeline_worker` 均薄封装调用此方法。

## generation_config 关键键

| 键 | 默认值 | 说明 |
|---|---|---|
| `outline_auto_patch_holes` | `true` | `pipeline_worker` 检测到大纲不连续时是否自动调用 `patch_missing_chapters` 补洞（关闭则改为提示用户手动处理） |
| `outline_gap_max_retries` | `2` | `patch_missing_chapters` 单章最大重试轮数 |
| `outline_gap_retry_delay` | `3` | 单章失败后退避秒数 |
| `max_retries` | 跟随用户 | `_process_single_chapter` 单章生成失败的最大重试次数 |

## Commands

### CLI

```bash
python main.py outline --start 1 --end 10        # 生成大纲
python main.py content --start-chapter 3          # 从第3章续写
python main.py content --target-chapter 5         # 重生成第5章
python main.py finalize --chapter 8               # 定稿
python main.py auto                               # 全流程
python main.py auto --force-outline               # 强制重生成大纲
python main.py imitate --style-source ... --input-file ... --output-file ...
```

### GUI

```bash
python gui_main.py                                # 启动 PySide6 可视化界面
```

### 打包

```bash
pyinstaller ocnovel.spec --clean                  # macOS → dist/OCNovel.app
pyinstaller ocnovel_win.spec --clean              # Windows → dist/OCNovel/OCNovel.exe
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

## CI/CD - GitHub Actions 自动打包发布

### 工作流配置

位置：`.github/workflows/build-release.yml`

**触发条件**：推送 `v*` 格式的 tag（如 `v1.0.4`）

**构建矩阵**：
- **macOS**: `macos-14` (Apple Silicon) → `OCNovel-macOS-arm64.zip`
- **Windows**: `windows-latest` (x64) → `OCNovel-Windows-x64.zip`

**关键设计**：
- CI 安装依赖时跳过 `FlagEmbedding`（会拉取 torch，体积巨大且 PyInstaller spec 已排除）
- 两平台并行构建，全部成功后自动创建 GitHub Release
- 使用 `softprops/action-gh-release@v2` 自动生成 Release Notes

### 发布流程

```bash
# 1. 确保所有变更已提交到 main 分支
git add .
git commit -m "feat: 新功能描述"
git push origin main

# 2. 创建并推送 tag（触发 CI）
git tag v1.0.x
git push origin v1.0.x
```

### 重要注意事项

⚠️ **工作流文件必须先存在于 main 分支**

如果工作流文件和 tag 在同一次 `git push` 中推送，GitHub Actions 无法识别工作流，不会触发构建。

**解决方案**：
1. 先推送包含工作流文件的 commit 到 main
2. 等待 GitHub 识别工作流（通常几秒钟）
3. 再单独推送 tag

或者，如果已经同时推送：
```bash
# 删除远程 tag
git push origin :refs/tags/v1.0.x

# 本地重建 tag
git tag -d v1.0.x
git tag v1.0.x

# 单独推送 tag（此时工作流已在 main 上）
git push origin v1.0.x
```

### 构建产物

- **macOS**: `dist/OCNovel.app` → 压缩为 `.zip`
- **Windows**: `dist/OCNovel/OCNovel.exe` + 依赖 → 压缩为 `.zip`

发布后自动附加到 GitHub Release 页面，用户可直接下载。
