# AGENTS.md - OCNovel

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
    recover_summary.py           # 章节摘要恢复工具
tools/                           # 命令行维护工具
  audit_outline.py               # 全局大纲审计
  revise_outline_from_audit.py   # 根据审计报告修订大纲
  fill_outline_gaps.py           # 补齐 outline.json 缺失槽位
  recommend_arc_size.py          # 推荐情绪节奏分卷数
  backfill_emotion_tone.py       # 回填 emotion_tone 占位
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
- **章节落盘清理**：`_save_chapter_content` 与 `merge_all_chapters` 自动剥离章节首行的 leading `#`（LLM 自带 Markdown 标题），保证作家助手等写作软件兼容。
- **合并分卷**：`merge_all_chapters` 在产物超过 `output_config.max_volume_size_mb`（默认 2MB，UTF-8 字节）时按章节边界分卷，文件命名 `{title}_完整版_第N卷.txt`；返回 `Optional[List[str]]`。
- **大纲全局审计（终局闸门）**：`generate_outline` 全书生成（补洞后）由 `_run_outline_audit` 调用 `src/generators/outline/outline_auditor.py` 的 `run_audit`，做**跨章结构审计**（O1 伏笔闭环 / O2 实体收口 / O3 任务闭环 / O4 人物身份 / O5 回收率），落盘 `outline_audit_report.json`。**只读不阻断生成**，由 `generation_config.outline_audit_enabled` 开关；异常被吞不影响大纲。审计核心在 `src/` 层（CLI `tools/audit_outline.py` 与流水线共用，确保打包可用）。算法为高召回初筛，`llm_review_task_closure(chapters, model)` 提供可选 LLM 语义裁决，专治"母题复用/顺带提及"导致的假闭环漏报（纯算法与 LLM 会犯同样的母题混淆错——闭环判定本质是语义任务）。
- **大纲质量闸门（阻断式，auto 流水线）**：`src/generators/outline/outline_quality_gate.py` 的 `run_quality_gate` / `run_quality_gate_for_pipeline`。auto 流程（CLI `main.py` 与 GUI `pipeline_worker` 共用）在大纲生成（含补洞）后、正文生成前跑此闸门：算法审计 + LLM 复核，有 fatal 则调 `revise_outline_from_audit` 修订写回 `outline.json`（带 `.bak` 备份）并重审；最终仍有 fatal 则 `passed=False`，调用方中止流水线、不进正文，并落盘 `outline_quality_gate_report.json`。**与只读 `_run_outline_audit` 的区别**：后者只读不阻断、只算法；本闸门含 LLM、会改写大纲、会中止流程。闸门自身执行异常 → fail-open 放行（与 `_run_outline_audit` 异常哲学一致）。由 `generation_config.outline_quality_gate_enabled` 开关（默认开）。

## generation_config 关键键

| 键 | 默认值 | 说明 |
|---|---|---|
| `outline_auto_patch_holes` | `true` | `pipeline_worker` 检测到大纲不连续时是否自动调用 `patch_missing_chapters` 补洞（关闭则改为提示用户手动处理） |
| `outline_gap_max_retries` | `2` | `patch_missing_chapters` 单章最大重试轮数 |
| `outline_gap_retry_delay` | `3` | 单章失败后退避秒数 |
| `max_retries` | 跟随用户 | `_process_single_chapter` 单章生成失败的最大重试次数 |
| `outline_audit_enabled` | `true` | 全书大纲生成后跑全局审计（O1-O5：伏笔闭环/事件线收口/人物身份），落盘 `outline_audit_report.json` 并日志提示 fatal。**只读报告，不阻断生成**；详查或叠加 LLM 复核用 `tools/audit_outline.py` |
| `outline_quality_gate_enabled` | `true` | auto 流程大纲生成后跑**阻断式**质量闸门（算法审计+LLM复核 → 有 fatal 自动修订重审 → 仍 fatal 中止流水线、不进正文）。区别于只读的 `outline_audit_enabled`，核心见 `outline_quality_gate.py` |
| `outline_quality_gate_llm_review` | `true` | 质量闸门内是否含 LLM 任务闭环复核（关闭则只跑算法审计，省额度） |
| `outline_quality_gate_max_rounds` | `1` | 闸门「修订→重审」最大轮数（默认单轮裁决） |

## output_config 关键键

| 键 | 默认 | 说明 |
|---|---|---|
| `output_dir` | `data/output` | 章节与合并产物落盘目录 |
| `max_volume_size_mb` | `2` | 合并产物按 UTF-8 字节超过此值自动按章节边界分卷；`<=0` 禁用,无论多大都单文件输出 |

## novel_config.arc_config 关键键（情绪节奏）

| 键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `chapters_per_arc` | int | 0 | 每卷章节数。`>0` 启用卷内 6 阶段螺旋情绪节奏（成长→挫折→绝境→爆发→跌落→新局），`0` 禁用 |
| `auto_compute` | bool | false | `chapters_per_arc<=0` 且 `target_chapters>0` 时按总章数自动推算最优分卷数（K∈{5,9,13,17,21,25,29}），保证全书 25%/50%/75% 灾难锚点对齐卷内挫折/绝境/跌落期 |

**优先级**：`chapters_per_arc>0` (user) > `auto_compute=true` (auto) > 禁用 (disabled)。
解析结果以 `_resolved_by` 审计字段标记，不写回 disk config.json。

**配套工具**：
- `tools/recommend_arc_size.py --total-chapters N` 查询推荐 cpa 与对齐质量
- `tools/backfill_emotion_tone.py --output-dir <DIR> --chapters-per-arc N` 为已有 outline.json 回填阶段占位

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

### 配套工具（tools/）

```bash
# 查询推荐 chapters_per_arc（不修改任何文件）
python tools/recommend_arc_size.py --total-chapters 400 [--show-candidates] [--json]

# 为已有 outline.json 回填 emotion_tone 占位（自动备份）
python tools/backfill_emotion_tone.py --output-dir data/output --chapters-per-arc 80

# 补生成 outline.json 缺失槽位
python tools/fill_outline_gaps.py --config config.json --env .env

# 全局审计大纲（剧情闭环/伏笔回收/人物身份），纯算法初筛
python tools/audit_outline.py --outline data/output/outline.json [--json]
# 叠加 LLM 语义复核任务闭环（识破"母题复用"导致的假闭环）
python tools/audit_outline.py --outline data/output/outline.json --llm --config config.json

# 根据审计报告修订大纲（支持 dry-run / JSON 输出）
python tools/revise_outline_from_audit.py --outline data/output/outline.json --config config.json [--dry-run] [--json]
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
- **Tests**: `tests/` 目录已入库，使用 pytest；测试代码本体入库，测试产物（`__pycache__` / `.pytest_cache` / `.coverage` / `htmlcov` / `data` / `output`）忽略。当前 KnowledgeBase 等路径以 mock 为主，避免真实加载 FlagEmbedding / 远程服务。
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
