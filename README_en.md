# OCNovel - AI Novel Generation System

English | [简体中文](README.md)

An AI-driven automatic novel generation system based on Python, supporting the creation of various genres such as Eastern Fantasy, Xianxia, Wuxia, and more. The system adopts a modular design, integrates multiple AI model interfaces, and provides full-process automation from outline generation to chapter content creation. It also offers a PySide6 visual interface to lower the usage barrier.

## Project Structure

```text
OCNovel/
├── main.py                    # CLI Entry
├── gui_main.py                # GUI Entry
├── ocnovel.spec               # PyInstaller packaging configuration
├── config.json.example        # Configuration file template
├── .env.example               # Environment variables template
├── requirements.txt           # Python dependencies
├── assets/                    # App icons and other resources
│
├── src/
│   ├── config/                # Configuration Management
│   │   ├── ai_config.py       # AI model configuration (Gemini/OpenAI/VolcEngine)
│   │   └── config.py          # General configuration management
│   │
│   ├── generators/            # Content Generators
│   │   ├── common/            # Common tools and data structures
│   │   ├── content/           # Chapter content generation + consistency check + validation
│   │   ├── outline/           # Outline generation
│   │   ├── finalizer/         # Finalize processing
│   │   ├── prompts.py         # Prompt templates
│   │   ├── humanization_prompts.py
│   │   └── title_generator.py
│   │
│   ├── models/                # AI Model Interfaces
│   │   ├── base_model.py      # Base model abstract class
│   │   ├── gemini_model.py    # Google Gemini implementation
│   │   └── openai_model.py    # OpenAI compatible implementation (includes VolcEngine reuse)
│   │
│   ├── knowledge_base/        # Knowledge Base (Vector retrieval + Reranker)
│   │   └── knowledge_base.py
│   │
│   ├── gui/                   # PySide6 Visual Interface
│   │   ├── app.py             # QApplication factory + global styles
│   │   ├── main_window.py     # Main window (3 Tabs)
│   │   ├── theme.py           # Theme color constants
│   │   ├── tabs/
│   │   │   ├── model_config_tab.py   # Model configuration
│   │   │   ├── novel_params_tab.py   # Novel parameters
│   │   │   └── progress_tab.py       # Creation progress
│   │   ├── workers/
│   │   │   ├── pipeline_worker.py    # Background generation pipeline
│   │   │   ├── connection_tester.py  # Model connection test
│   │   │   └── writing_guide_worker.py # AI generated writing guide
│   │   ├── widgets/
│   │   │   ├── log_viewer.py         # Real-time log viewer
│   │   │   └── chapter_list.py       # Chapter status list
│   │   └── utils/
│   │       ├── config_io.py          # .env / config.json read/write
│   │       ├── log_handler.py        # logging → Qt Signal bridging
│   │       └── resource_path.py      # PyInstaller path compatibility
│   │
│   └── tools/                 # Auxiliary Tools
│       ├── generate_config.py
│       ├── generate_marketing.py
│       └── ai_density_checker.py
│
└── data/                      # Runtime Data (gitignored)
    ├── cache/
    ├── logs/
    ├── output/
    ├── reference/
    └── style_sources/
```

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configuration

```bash
cp config.json.example config.json
cp .env.example .env
```

Edit `.env` and fill in the API keys:

```bash
# Configure at least one set of models
OPENAI_EMBEDDING_API_KEY=your_key
OPENAI_EMBEDDING_API_BASE=https://api.siliconflow.cn/v1
OPENAI_OUTLINE_API_KEY=your_key
OPENAI_OUTLINE_API_BASE=https://api.siliconflow.cn/v1
OPENAI_CONTENT_API_KEY=your_key
OPENAI_CONTENT_API_BASE=https://api.siliconflow.cn/v1
```

### 3. Start

**GUI Mode (Recommended):**

```bash
python gui_main.py
```

**CLI Mode:**

```bash
# Automatically execute the full process (Outline + Content + Finalize)
python main.py auto

# Generate outline
python main.py outline --start 1 --end 10

# Continue writing from a specific chapter
python main.py content --start-chapter 3

# Regenerate a specific chapter
python main.py content --target-chapter 5

# Finalize processing
python main.py finalize --chapter 8

# Force regenerate outline
python main.py auto --force-outline

# Imitation writing
python main.py imitate --style-source sample.txt --input-file original.txt --output-file output.txt
```

## GUI Features

After starting `python gui_main.py`, three Tab pages are provided:

- **Model Configuration** — Manage API keys, Base URLs, and model names for Gemini / OpenAI / Fallback / Reranker, and support one-click connection testing.
- **Novel Parameters** — Edit novel settings, writing guides, generation parameters, imitation configuration, knowledge base, and output directory in `config.json`; supports AI automatic generation of writing guides, and creating/backing up configurations.
- **Creation Progress** — One-click start/stop of the generation pipeline, real-time viewing of the chapter status list and colorful logs, progress bar indicating current progress, and support for breakpoint continuation.

### Package as macOS App

```bash
pyinstaller ocnovel.spec --clean
# Output dist/OCNovel.app
```

## Core Architecture

- **Model Abstraction** — `BaseModel` ABC → `OpenAIModel` / `GeminiModel`, VolcEngine reuses OpenAI implementation.
- **Configuration Layering** — `config.json` (Novel parameters) + `.env` (API keys) + `AIConfig` (Model default values).
- **Generation Pipeline** — outline → content → finalize, connected via the `auto` command.
- **Knowledge Base** — Text chunking → Embedding vector → FAISS retrieval → Reranker API fine ranking.
- **Retry/Fallback** — tenacity retries + automatic backup model switching.

## Configuration Details

| Configuration Block | Description |
| ------------------- | ----------- |
| `novel_config` | Basic novel information, writing guide (Worldview / Characters / Plot / Style). |
| `generation_config` | Retry routing, model selection (provider), validation switches, humanization parameters. |
| `knowledge_base_config` | Reference file list, chunk size/overlap, cache directory. |
| `output_config` | Output format, encoding, output directory. |
| `imitation_config` | Imitation script toggle, style source lists, quality control parameters. |

## Requirements

- Python 3.9+
- macOS / Linux / Windows
- At least one set of AI model API keys configured (OpenAI compatible / Gemini)
