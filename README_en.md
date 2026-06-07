# OCNovel

English | [简体中文](README.md)

### Agent-based Long-form Content Generation System for Narrative Coherence

OCNovel is an open-source, agent-based system for **long-form content generation**, designed to address one of the core limitations of modern large language models: **maintaining narrative coherence across extended contexts**.

It provides a full pipeline from **high-level planning to chapter-level generation and finalization**, integrating multi-model orchestration, retrieval-augmented memory, and consistency validation.

------

## Why OCNovel

Long-form generation (e.g. novels, scripts, multi-chapter content) presents several unsolved challenges:

- Context fragmentation across long sequences
- Character and plot inconsistency
- Lack of structured planning before generation
- Weak integration between retrieval and generation

OCNovel addresses these issues through a **multi-stage generation pipeline with persistent memory and validation loops**.

------

## Core Capabilities

### 1. Multi-stage Generation Pipeline

The system decomposes long-form writing into structured stages:

- Outline Planning (global structure)
- Chapter Generation (localized reasoning)
- Consistency Validation (cross-context alignment)
- Finalization (style + quality refinement)

This reduces hallucination and improves global coherence.

------

### 2. Agent-like Orchestration

OCNovel simulates an **agent workflow**:

- Planner → Writer → Reviewer → Refiner
- Each stage uses specialized prompts and constraints
- Supports iterative regeneration and correction

------

### 3. Long-context Consistency Management

Key mechanisms include:

- Structured outline as global memory anchor
- Chapter-level dependency tracking
- Consistency checking between generated segments

This enables stable narrative progression across long outputs.

------

### 4. Retrieval-Augmented Memory (RAG)

The system integrates a memory layer:

- Text chunking → Embedding → FAISS retrieval
- Reranker for relevance refinement
- External reference injection into generation

This improves factual grounding and stylistic alignment.

------

### 5. Multi-model Abstraction Layer

OCNovel provides a unified interface for multiple LLM providers:

- OpenAI-compatible models
- Anthropic Claude
- Google Gemini

The architecture allows dynamic switching, fallback, and hybrid usage.

------

### 6. Outline Audit & Blocking Quality Gate

OCNovel provides **two complementary mechanisms** to validate the global outline before any chapter is written:

**Read-only audit** (`outline_audit_enabled`, on by default):
- Runs a cross-chapter structural audit after the full outline is generated
- Five algorithmic rules: **O1** foreshadowing closure, **O2** entity life-line (characters that vanish mid-story), **O3** task/arc closure, **O4** character-identity consistency, **O5** recovery rate
- Outputs `outline_audit_report.json`; does **not** block generation
- Can be augmented with LLM semantic review via `tools/audit_outline.py --llm` to catch false closures caused by motif reuse

**Blocking quality gate** (`outline_quality_gate_enabled`, on by default):
- Runs in the `auto` pipeline after outline generation
- Algorithmic audit + LLM review; on fatal findings, auto-revises the outline (with `.bak` backup) and re-audits
- If fatal findings remain after `outline_quality_gate_max_rounds` rounds, the pipeline is halted before any chapter is produced
- Outputs `outline_quality_gate_report.json`

Both mechanisms feed into the same revision engine, accessible via:
- `tools/revise_outline_from_audit.py` (CLI)
- GUI "Revise Outline" button

------

### 7. Emotion-arc Pacing

Per-volume **6-stage spiral emotional rhythm** (growth → setback → desperation → outbreak → fall → new beginning):

- Configurable via `arc_config`; can auto-derive the optimal number of volumes from the total chapter count
- Aligns the 25% / 50% / 75% disaster anchors with each volume's setback / desperation / fall phases

------

### 8. Chapter Content Audit & Revision

After chapters are generated, OCNovel can **audit** and **revise** their content:

- **C0**: Input completeness pre-check
- **C1**: Chapter text vs. outline consistency
- **C2**: Transition naturalness between the current chapter's opening and the previous chapter's ending

The audit supports both **full-novel** and **selected-chapter** modes. Based on the audit report, the revision module automatically rewrites chapters with fatal/warning findings, backs up originals, and optionally refreshes chapter summaries.

CLI usage:

```bash
python main.py revise-content --audit-report data/output/content_audit_report.json
python main.py revise-content --include-warning   # also process warnings
python main.py revise-content --dry-run            # preview only, no writes
python main.py revise-content --update-summary     # refresh summaries after revision
```

------

## System Architecture

```
User Input
   ↓
[Outline Generator]
   ↓
[Memory Layer (RAG)]
   ↓
[Chapter Generator]
   ↓
[Consistency Validator]
   ↓
[Finalizer]
```

Key layers:

- Model Layer (LLM abstraction)
- Pipeline Layer (generation workflow)
- Memory Layer (retrieval + embedding)
- Interface Layer (CLI + GUI)

![OCNovel System Architecture](https://pic.2rmz.com/1776517432835.png)

------

## Quick Start

Install dependencies and create local configuration files:

```bash
pip install -r requirements.txt
cp config.json.example config.json
cp .env.example .env
```

Fill in at least one model provider in `.env`:

- Claude: `CLAUDE_API_KEY` plus OpenAI-compatible embedding settings
- Gemini: `GEMINI_API_KEY`
- OpenAI-compatible APIs: `OPENAI_OUTLINE_API_KEY`, `OPENAI_CONTENT_API_KEY`, and `OPENAI_EMBEDDING_API_KEY`
- Optional fallback model: `FALLBACK_API_KEY`, `FALLBACK_API_BASE`, `FALLBACK_MODEL_ID`, `FALLBACK_API_MODE`

Run the GUI:

```bash
python gui_main.py
```

Run the CLI pipeline:

```bash
python main.py auto
python main.py outline --start 1 --end 10
python main.py content --start-chapter 3
python main.py finalize --chapter 8
```

------

## Maintenance Tools

The repository includes standalone tools under `tools/`:

- `audit_outline.py` — global outline audit (O1–O5 algorithmic rules), with optional `--llm` semantic review for task closure
- `revise_outline_from_audit.py` — revise an outline based on an audit report; supports `--dry-run`, `--include-warning`, `--rules O3,O4`
- `fill_outline_gaps.py` — patch missing sparse outline slots
- `recommend_arc_size.py` — recommend `chapters_per_arc` for emotion-arc pacing
- `backfill_emotion_tone.py` — backfill emotion-tone placeholders for existing outlines

```bash
# Outline audit (algorithmic only)
python tools/audit_outline.py --outline data/output/outline.json

# Outline audit with LLM semantic review
python tools/audit_outline.py --outline data/output/outline.json --llm --config config.json

# Revise outline from audit report (fatal findings only)
python tools/revise_outline_from_audit.py --outline data/output/outline.json --config config.json

# Preview mode (no writes)
python tools/revise_outline_from_audit.py --outline data/output/outline.json --config config.json --dry-run
```

Runtime configuration examples are maintained in `config.json.example` and `.env.example`.

------

## OpenAI Integration

OCNovel is designed to work seamlessly with OpenAI-compatible models:

- Embedding-based retrieval (RAG memory)
- Structured prompt pipelines optimized for reasoning models
- Long-context generation workflows

Recommended usage:

- Outline generation: reasoning-capable models
- Content generation: balanced cost-performance models
- Embedding: OpenAI-compatible embedding APIs

------

## Example Use Cases

- Long-form fiction generation (novels, web fiction)
- Script and narrative design
- Multi-step content generation pipelines
- Research into long-context coherence in LLMs

------

## Research Relevance

OCNovel can serve as a practical testbed for:

- Long-context reasoning
- Narrative consistency in LLM outputs
- Multi-stage generation strategies
- Retrieval-augmented generation pipelines

------

## Project Structure (Simplified)

```
src/
 ├── models/          # LLM abstraction layer
 ├── generators/      # multi-stage generation pipeline
 ├── knowledge_base/  # RAG memory system
 ├── gui/             # user interface
```

------

## Key Design Principles

- Decomposition over monolithic prompting
- Memory-augmented generation
- Iterative refinement loops
- Model-agnostic architecture

------

## Roadmap

-  Advanced agent coordination (multi-agent planning)
-  Long-term memory persistence across projects
-  Evaluation benchmarks for narrative consistency
-  OpenAI-native optimization (reasoning + tool use)

------

## Repository Migration Notice

This project has been migrated from `github.com/wenjiazhu/OCNovel` to **[github.com/wenjiazhu1980/OCNovel](https://github.com/wenjiazhu1980/OCNovel)**.

The original GitHub account `wenjiazhu` is no longer used for open-source project maintenance due to account policy changes. All development has moved to the new account `wenjiazhu1980` for long-term management and continuous updates. All commit history, tags, and branches have been fully preserved — functionality and usage remain unchanged.

If you previously cloned the old repository, update your remote URL with:

```bash
git remote set-url origin https://github.com/wenjiazhu1980/OCNovel.git
```

------

## Contribution

OCNovel is actively maintained and open to contributions:

- Prompt engineering improvements
- Long-context optimization strategies
- Model integration
- Evaluation and benchmarking

------

## License

MIT License

------

## Summary

OCNovel is not just a writing tool, but a **structured system for long-form generation**, focusing on:

- coherence
- memory
- multi-stage reasoning

It aims to explore how LLMs can move beyond short outputs toward **stable, large-scale content generation**.
