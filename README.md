# OCNovel - AI小说生成系统

[English](README_en.md) | 简体中文

一个基于 Python 的 AI 小说自动生成系统，支持东方玄幻、仙侠、武侠等多种类型的小说创作。系统采用模块化设计，集成多种 AI 模型接口，提供从大纲生成到章节内容创作的全流程自动化。同时提供 PySide6 可视化界面，降低使用门槛。

## 项目结构

```
OCNovel/
├── main.py                    # CLI 入口
├── gui_main.py                # GUI 入口
├── ocnovel.spec               # PyInstaller 打包配置
├── config.json.example        # 配置文件模板
├── .env.example               # 环境变量模板
├── requirements.txt           # Python 依赖
├── assets/                    # App 图标等资源
│
├── src/
│   ├── config/                # 配置管理
│   │   ├── ai_config.py       # AI 模型配置（Gemini/OpenAI/VolcEngine）
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
│   │   ├── gemini_model.py    # Google Gemini 实现
│   │   └── openai_model.py    # OpenAI 兼容实现（含 VolcEngine 复用）
│   │
│   ├── knowledge_base/        # 知识库（向量检索 + Reranker）
│   │   └── knowledge_base.py
│   │
│   ├── gui/                   # PySide6 可视化界面
│   │   ├── app.py             # QApplication 工厂 + 全局样式
│   │   ├── main_window.py     # 主窗口（3 Tab）
│   │   ├── theme.py           # 主题色常量
│   │   ├── tabs/
│   │   │   ├── model_config_tab.py   # 模型配置
│   │   │   ├── novel_params_tab.py   # 小说参数
│   │   │   └── progress_tab.py       # 创作进度
│   │   ├── workers/
│   │   │   ├── pipeline_worker.py    # 后台生成流水线
│   │   │   ├── connection_tester.py  # 模型连接测试
│   │   │   └── writing_guide_worker.py # AI 生成写作指南
│   │   ├── widgets/
│   │   │   ├── log_viewer.py         # 实时日志查看器
│   │   │   └── chapter_list.py       # 章节状态列表
│   │   └── utils/
│   │       ├── config_io.py          # .env / config.json 读写
│   │       ├── log_handler.py        # logging → Qt Signal 桥接
│   │       └── resource_path.py      # PyInstaller 路径兼容
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
```bash
# 至少配置一组模型
OPENAI_EMBEDDING_API_KEY=your_key
OPENAI_EMBEDDING_API_BASE=https://api.siliconflow.cn/v1
OPENAI_OUTLINE_API_KEY=your_key
OPENAI_OUTLINE_API_BASE=https://api.siliconflow.cn/v1
OPENAI_CONTENT_API_KEY=your_key
OPENAI_CONTENT_API_BASE=https://api.siliconflow.cn/v1
```

### 3. 启动

**GUI 模式（推荐）：**
```bash
python gui_main.py
```

**CLI 模式：**
```bash
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

- **模型配置** — 管理 Gemini / OpenAI / Fallback / Reranker 的 API 密钥、Base URL、模型名称，支持一键测试连接
- **小说参数** — 编辑 config.json 中的小说设定、写作指南、生成参数、仿写配置、知识库和输出目录；支持 AI 自动生成写作指南、新建/备份配置
- **创作进度** — 一键启停生成流水线，实时查看章节状态列表和彩色日志，进度条显示当前进度，支持断点续写

### 打包为 macOS App

```bash
pyinstaller ocnovel.spec --clean
# 输出 dist/OCNovel.app
```

## 核心架构

- **模型抽象** — `BaseModel` ABC → `OpenAIModel` / `GeminiModel`，VolcEngine 复用 OpenAI 实现
- **配置分层** — `config.json`（小说参数）+ `.env`（API 密钥）+ `AIConfig`（模型默认值）
- **生成流水线** — outline → content → finalize，通过 `auto` 命令串联
- **知识库** — 文本分块 → 嵌入向量 → FAISS 检索 → Reranker API 精排
- **重试/备用** — tenacity 重试 + 备用模型自动切换

## 配置说明

| 配置块 | 说明 |
|--------|------|
| `novel_config` | 小说基本信息、写作指南（世界观/角色/剧情/风格） |
| `generation_config` | 重试策略、模型选择（provider）、验证开关、人性化参数 |
| `knowledge_base_config` | 参考文件列表、分块大小/重叠、缓存目录 |
| `output_config` | 输出格式、编码、输出目录 |
| `imitation_config` | 仿写开关、风格源列表、质量控制参数 |

## 环境要求

- Python 3.9+
- macOS / Linux / Windows
- 至少配置一组 AI 模型 API 密钥（OpenAI 兼容 / Gemini）
