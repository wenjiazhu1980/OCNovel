# OCNovel - AI小说生成系统

[English](README_en.md) | 简体中文

一个基于 Python 的 AI 小说自动生成系统，支持东方玄幻、仙侠、武侠等多种类型的小说创作。系统采用模块化设计，集成多种 AI 模型接口，提供从大纲生成到章节内容创作的全流程自动化。同时提供 PySide6 可视化界面，降低使用门槛。

## 下载

**[前往最新版 Release 下载 →](https://github.com/wenjiazhu/OCNovel/releases/latest)**

无需配置 Python 环境，下载对应平台的压缩包，解压后即可直接运行 GUI：

| 平台 | 下载链接 | 当前最新 |
|------|----------|----------|
| macOS (Apple Silicon) | [OCNovel-macOS-arm64.zip](https://github.com/wenjiazhu/OCNovel/releases/latest/download/OCNovel-macOS-arm64.zip) | v1.0.11 |
| Windows (x64) | [OCNovel-Windows-x64.zip](https://github.com/wenjiazhu/OCNovel/releases/latest/download/OCNovel-Windows-x64.zip) | v1.0.11 |

> 历史版本与更新日志：[Releases 页面](https://github.com/wenjiazhu/OCNovel/releases)  ·  本次发布：[v1.0.11](https://github.com/wenjiazhu/OCNovel/releases/tag/v1.0.11)

> **macOS 用户首次启动**：因应用未经 Apple 公证（Apple Developer Program 收费 $99/年），
> 解压后请在终端执行一次以下命令清除 quarantine 标记：
>
> ```bash
> xattr -cr ~/Downloads/OCNovel.app   # 若已拖入 /Applications/，请改成对应路径
> ```
>
> 之后双击即可正常启动。该命令仅清除下载隔离属性，不修改应用本身。

## 作者与项目说明

OCNovel 由 @wenjiazhu 个人发起并持续维护，是一个面向长篇小说创作场景的开源项目。项目目标是帮助用户更高效地完成长文本生成、内容规划和多轮迭代，并欢迎社区提出 issue、建议和 PR 共同完善。

## 项目结构

```text
OCNovel/
├── main.py                    # CLI 入口
├── gui_main.py                # GUI 入口
├── ocnovel.spec               # PyInstaller macOS 打包配置
├── ocnovel_win.spec           # PyInstaller Windows 打包配置
├── config.json.example        # 配置文件模板
├── .env.example               # 环境变量模板
├── requirements.txt           # Python 依赖
├── assets/                    # App 图标等资源
│
├── src/
│   ├── config/                # 配置管理
│   │   ├── ai_config.py       # AI 模型配置（Claude/Gemini/OpenAI）
│   │   └── config.py          # 通用配置管理
│   │
│   ├── generators/            # 内容生成器
│   │   ├── common/            # 通用工具和数据结构
│   │   ├── content/           # 章节内容生成 + 一致性检查 + 验证
│   │   ├── outline/           # 大纲生成
│   │   ├── finalizer/         # 定稿处理
│   │   ├── prompts.py         # Prompt 模板
│   │   ├── humanization_prompts.py
│   │   └── title_generator.py
│   │
│   ├── models/                # AI 模型接口
│   │   ├── base_model.py      # 基础模型抽象类
│   │   ├── claude_model.py    # Anthropic Claude 实现
│   │   ├── gemini_model.py    # Google Gemini 实现
│   │   └── openai_model.py    # OpenAI 兼容实现
│   │
│   ├── knowledge_base/        # 知识库（向量检索 + Reranker）
│   │   └── knowledge_base.py
│   │
│   ├── gui/                   # PySide6 可视化界面
│   │   ├── app.py             # QApplication 工厂 + 全局样式
│   │   ├── main_window.py     # 主窗口（3 Tab）
│   │   ├── theme.py           # 主题色常量
│   │   ├── i18n/              # 国际化翻译文件
│   │   │   ├── translator.py  # 翻译管理器
│   │   │   ├── zh_CN.ts       # 中文翻译源文件
│   │   │   ├── en_US.ts       # 英文翻译源文件
│   │   │   ├── zh_CN.qm       # 中文编译翻译文件
│   │   │   └── en_US.qm       # 英文编译翻译文件
│   │   ├── tabs/
│   │   │   ├── model_config_tab.py   # 模型配置
│   │   │   ├── novel_params_tab.py   # 小说参数
│   │   │   └── progress_tab.py       # 创作进度
│   │   ├── workers/
│   │   │   ├── pipeline_worker.py    # 后台生成流水线
│   │   │   ├── connection_tester.py  # 模型连接测试
│   │   │   ├── marketing_worker.py   # 营销内容生成
│   │   │   └── writing_guide_worker.py # AI 生成写作指南
│   │   ├── widgets/
│   │   │   ├── log_viewer.py         # 实时日志查看器
│   │   │   └── chapter_list.py       # 章节状态列表
│   │   └── utils/
│   │       ├── config_io.py          # .env / config.json 读写
│   │       ├── log_handler.py        # logging → Qt Signal 桥接
│   │       ├── resource_path.py      # PyInstaller 路径兼容
│   │       ├── platform_utils.py     # 跨平台工具（打开目录等）
│   │       └── fonts.py              # 跨平台字体常量
│   │
│   └── tools/                 # 辅助工具
│       ├── generate_config.py
│       ├── generate_marketing.py
│       └── ai_density_checker.py
│
└── data/                      # 运行时数据（gitignored）
    ├── cache/
    ├── logs/
    ├── output/
    ├── reference/
    └── style_sources/
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

```bash
cp config.json.example config.json
cp .env.example .env
```

编辑 `.env` 填入 API 密钥：

```text
# 方式一：使用 Claude 模型（推荐用于高质量创作）
CLAUDE_API_KEY=your_claude_key
CLAUDE_OUTLINE_MODEL=claude-3-5-sonnet-20241022
CLAUDE_CONTENT_MODEL=claude-3-5-sonnet-20241022

# 嵌入模型（必需，Claude 不支持嵌入）
OPENAI_EMBEDDING_API_KEY=your_key
OPENAI_EMBEDDING_API_BASE=https://api.siliconflow.cn/v1

# 方式二：使用 OpenAI 兼容模型（推荐用于开发测试）
OPENAI_EMBEDDING_API_KEY=your_key
OPENAI_EMBEDDING_API_BASE=https://api.siliconflow.cn/v1
OPENAI_OUTLINE_API_KEY=your_key
OPENAI_OUTLINE_API_BASE=https://api.siliconflow.cn/v1
OPENAI_CONTENT_API_KEY=your_key
OPENAI_CONTENT_API_BASE=https://api.siliconflow.cn/v1

# 方式三：使用 Gemini 模型
GEMINI_API_KEY=your_gemini_key
GEMINI_OUTLINE_MODEL=gemini-2.5-pro
GEMINI_CONTENT_MODEL=gemini-2.5-flash
```

### 3. 启动

**GUI 模式（推荐）：**

```bash
python gui_main.py
```

**CLI 模式：**

```text
# 自动执行完整流程（大纲 + 内容 + 定稿）
python main.py auto

# 生成大纲
python main.py outline --start 1 --end 10

# 从指定章节续写
python main.py content --start-chapter 3

# 重新生成指定章节
python main.py content --target-chapter 5

# 定稿处理
python main.py finalize --chapter 8

# 强制重生成大纲
python main.py auto --force-outline

# 仿写
python main.py imitate --style-source 范文.txt --input-file 原文.txt --output-file 输出.txt
```

## GUI 功能

启动 `python gui_main.py` 后提供三个 Tab 页：

- **模型配置** — 管理 Claude / Gemini / OpenAI / Fallback / Reranker 的 API 密钥、Base URL、模型名称，支持一键测试连接
- **小说参数** — 编辑 config.json 中的小说设定、写作指南、生成参数（支持温度、Top_P、Humanizer-zh 校验等）、仿写配置、知识库和输出目录；支持 AI 自动生成写作指南、新建/备份配置
- **创作进度** — 一键启停生成流水线，实时查看章节状态列表和彩色日志，进度条显示当前进度，支持断点续写

### 国际化支持

GUI 界面支持**中文**和**英文**两种语言：

- **自动检测**: 中文系统默认显示中文界面，非中文系统默认显示英文界面
- **手动切换**: 通过菜单栏「语言 / Language」可随时切换界面语言
- **持久化**: 语言偏好自动保存，重启应用后保持选择的语言
- **覆盖范围**: 所有按钮、标签、菜单、消息框、工具提示均已翻译（242个文本，91.7%已翻译）

> 注：核心生成模块的技术日志保持英文，以便调试和问题排查。

### 打包为桌面应用

**macOS：**

```bash
pyinstaller ocnovel.spec --clean
# 输出 dist/OCNovel.app
```

**Windows：**

```bash
pyinstaller ocnovel_win.spec --clean
# 输出 dist/OCNovel/OCNovel.exe
```

> 注：PyInstaller 不支持交叉编译，macOS 打包须在 macOS 上执行，Windows 打包须在 Windows 上执行。详见 [构建指南](BUILD.md)。

## 核心架构

- **模型抽象** — `BaseModel` ABC → `ClaudeModel` / `GeminiModel` / `OpenAIModel`
- **配置分层** — `config.json`（小说参数）+ `.env`（API 密钥）+ `AIConfig`（模型默认值）
- **生成流水线** — outline → content → finalize，通过 `auto` 命令串联
- **知识库** — 文本分块 → 嵌入向量 → FAISS 检索 → Reranker API 精排
- **重试/备用** — tenacity 重试 + 备用模型自动切换

## 支持的 AI 模型

### Claude (Anthropic)

- **优势**: 强大的推理能力，200K tokens 长上下文，适合复杂创作
- **推荐模型**: `claude-3-5-sonnet-20241022`
- **注意**: 不支持嵌入功能，需配合 OpenAI 兼容的嵌入模型使用
- **详细文档**: [Claude 集成指南](docs/claude_integration.md)

### Gemini (Google)

- **优势**: 官方 API 稳定，支持长上下文
- **推荐模型**: `gemini-2.5-pro` (大纲) / `gemini-2.5-flash` (内容)
- **注意**: 仅支持 Google 官方 API

### OpenAI 兼容

- **优势**: 生态丰富，支持多种第三方 API（如硅基流动）
- **推荐模型**: `Qwen/Qwen2.5-7B-Instruct` (开源免费)
- **适用场景**: 开发测试、成本敏感场景

## 配置说明

| 配置块                  | 说明                                                                                              |
|------------------------|---------------------------------------------------------------------------------------------------|
| `novel_config`         | 小说基本信息、写作指南（世界观/角色/剧情/风格）                                                     |
| `generation_config`    | 重试策略、模型选择、验证开关、人性化参数（Humanizer-zh）、采样参数（Temperature/Top_P）             |
| `knowledge_base_config`| 参考文件列表、分块大小/重叠、缓存目录                                                               |
| `output_config`        | 输出格式、编码、输出目录                                                                           |
| `imitation_config`     | 仿写开关、风格源列表、质量控制参数                                                                 |

## 环境要求

- Python 3.9+
- macOS / Linux / Windows
- 至少配置一组 AI 模型 API 密钥（Claude / Gemini / OpenAI 兼容）
- 如使用 Claude，需额外配置嵌入模型（OpenAI 兼容）

## 常见问题 (FAQ)

### 1. 如何下载和运行 Mac App？

1. 下载最新发布的 Mac App 压缩包。
2. 解压后将 `OCNovel.app` 拖入”应用程序”文件夹（或在你希望的目录下）。
3. 如果首次打开时系统提示应用”已损坏，无法打开”或”无法验证开发者”，请在终端执行以下命令清除隔离属性：

   ```bash
   sudo xattr -rd com.apple.quarantine /path/to/OCNovel.app
   ```

   *(请将 `/path/to/OCNovel.app` 替换为你实际存放 App 的路径)*，然后再次尝试打开该应用。

### 2. 如何下载和运行 Windows 版？

1. 下载最新发布的 Windows 压缩包。
2. 解压后运行 `OCNovel.exe`。
3. 首次启动时，应用会在用户主目录自动创建 `%USERPROFILE%\OCNovel\` 并初始化配置文件。
4. 编辑 `%USERPROFILE%\OCNovel\.env` 填入 API 密钥后即可使用。

### 3. 关于硅基流动注册邀请链接的说明

我们在文档中可能会提供带有邀请码（aff）的硅基流动（SiliconFlow）注册连接：

- 通过该邀请链接注册，您通常能获得该平台提供的新用户免费体验额度，同时作为推荐人我们也会获得一定比例的代金券或算力奖励。
- 我们通过这些推广链接获得的奖励，将全部投入到本项目后续的模型 API 调用测试及新功能的开发中。
- 这并非强制使用，您完全可以自行访问平台官网进行无邀请码的独立注册。非常感谢您的支持与理解！
