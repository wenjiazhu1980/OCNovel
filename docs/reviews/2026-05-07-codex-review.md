# Codex 代码评审报告 · 2026-05-07

> **评审范围**：`19c4207^..HEAD`（30 commits, 24 files, +3119 / -852）
> **评审工具**：Codex MCP (read-only)
> **评审日期**：2026-05-07
> **评审分支**：`main` (HEAD: `a1232e7`)
> **评审 Session**：`019e0292-03d9-70c3-a65a-6de141cef304`

---

## 一、整体评估

### 综合评分：6.5 / 10

**核心理由**

- 实质性加固：大纲稀疏加载、缺洞补生成、连续生成摘要补写、GUI worker 模型创建上下文、合并仿写回退
- 阻塞发布：5 个会直接影响发布可用性的 High 风险问题
  1. CI/tests 入口与仓库实际内容断裂
  2. 语言热切换 zh→en 崩溃
  3. 进度计算的并集逻辑会掩盖正文缺失
  4. GUI pipeline 章节失败后仍发出成功信号
  5. 大纲扩展字段在落盘时被丢弃，导致三层 Prompt 设计失效

### 工程纪律评估

- 提交粒度整体可读，commit message 大多符合中文 `type(scope): 描述` 习惯
- `fc6e2e8 / cc97f5c / 7ccc0cc` 对 `.gitignore` 与 `tests/` 的来回处理结果不合格：当前 `git ls-files tests` 为空，而 CI 仍执行 `python -m pytest tests/`，仓库级测试体系在干净 checkout 下失效

### 验证范围

- 已检查 `19c4207^..HEAD` 的 diff / stat / name-status / log
- `git diff --check` 无格式错误
- 21 个变更 Python 文件 `ast.parse` 解析通过
- 未运行 pytest（仓库无被 Git 跟踪的 `tests/`）

---

## 二、Critical / High 严重问题

### H1 — CI 测试入口与仓库实际内容断裂

| 项 | 内容 |
|---|---|
| 严重度 | High |
| 影响范围 | PR/push CI、测试覆盖率 |
| 涉及文件 | `.github/workflows/ci.yml:37`、`.gitignore:42` |

**问题描述**

`.github/workflows/ci.yml` 仍执行 `python -m pytest tests/`，但 `.gitignore` 直接忽略 `tests/*`；本范围内还删除了被跟踪的 `tests/test_fallback_logic.py`。当前 `git ls-files tests` 为空。

**修复建议**

恢复跟踪测试代码，改 `.gitignore` 为只忽略测试产物：

```gitignore
# 旧
tests/*

# 新
tests/__pycache__/
tests/.pytest_cache/
!tests/**/*.py
!tests/conftest.py
!tests/__init__.py
```

并为本轮核心链路补充测试：`test_outline_generator.py`、`test_content_generator.py`、`test_focus_dedup.py`、`test_knowledge_base.py`。

---

### H2 — 语言热切换 zh→en 因 `_translators` 未初始化而崩溃

| 项 | 内容 |
|---|---|
| 严重度 | High |
| 影响范围 | GUI 默认中文环境的语言切换功能完全不可用 |
| 涉及文件 | `src/gui/i18n/translator.py:109`、`src/gui/i18n/translator.py:148` |

**问题描述**

`load_translation()` 在 `zh_CN` 源语言路径直接返回，不创建 `app._translators`；随后 `switch_language()` 无条件执行 `app._translators.clear()`。如果应用启动语言是中文（默认），第一次切换到英文会触发 `AttributeError`。

**修复建议**

在 `switch_language()` 中使用安全访问：

```python
translators = getattr(app, "_translators", [])
for tr in translators:
    app.removeTranslator(tr)
app._translators = []
```

或在初始化阶段始终保证 `app._translators = []`。

---

### H3 — `summary.json` 与磁盘正文的并集进度会掩盖正文缺失

| 项 | 内容 |
|---|---|
| 严重度 | High |
| 影响范围 | 内容生成、GUI 进度、断点续写、最终合并 |
| 涉及文件 | `src/generators/content/content_generator.py:213`、`src/gui/workers/pipeline_worker.py:261` |

**问题描述**

`_load_progress()` 用 `summary_keys | disk_keys` 计算最长连续前缀。若 `summary.json` 有第 2 章但正文 `第2章_*.txt` 被删或从未写入，`union_keys` 仍会把第 2 章视为完成，pipeline 可能从第 4 章继续甚至直接返回"全部完成"。

**修复建议**

完成态以"正文存在"为硬条件。建议把状态分为：

- `content_exists`：正文存在
- `summary_exists`：摘要存在
- `pending_finalize`：正文存在但未生成摘要
- `stale_summary_only`：仅有摘要无正文（异常态）

遇到 `stale_summary_only` 应重新生成正文或 fail-fast 提示修复。

---

### H4 — GUI pipeline 遇到章节失败后仍可能最终发出成功信号

| 项 | 内容 |
|---|---|
| 严重度 | High |
| 影响范围 | GUI 自动生成流程、章节状态、最终合并 |
| 涉及文件 | `src/gui/workers/pipeline_worker.py:313 / 358 / 383` |

**问题描述**

连续模式中，正文已存在但补 finalize 失败时只 `chapter_failed.emit(...)` 后 `continue`；正常生成返回 `False` 时也只发出失败信号，循环继续。最终无论中间失败多少章，仍会执行合并并 `pipeline_finished.emit(True)`。

**修复建议**

```python
failed_chapters = []
# 循环中：
if not ok:
    failed_chapters.append(chapter_num)
    if mode == "continuous":
        break  # 连续模式立即中止
    continue   # 指定章节模式允许多章独立失败

# 终态：
overall_ok = (len(failed_chapters) == 0)
if overall_ok:
    self._auto_merge()
self.pipeline_finished.emit(overall_ok)
```

---

### H5 — 大纲 Prompt 要求的扩展字段没有写入 `ChapterOutline`

| 项 | 内容 |
|---|---|
| 严重度 | High |
| 影响范围 | 三层 Prompt / 雪花写作法增强设计基本失效 |
| 涉及文件 | `src/generators/prompts.py:305`、`src/generators/common/data_structures.py:13`、`src/generators/outline/outline_generator.py:627 / 880` |

**问题描述**

Prompt 明确要求输出 `emotion_tone / character_goals / scene_sequence / foreshadowing / pov_character`，数据结构和内容 Prompt 也支持这些字段；但 `_generate_batch()` 和 `_generate_single_chapter_outline()` 构造 `ChapterOutline` 时只传基础 5 个字段，扩展字段全部丢弃。

**修复建议**

构造 `ChapterOutline` 时传入扩展字段并做类型归一化：

```python
ChapterOutline(
    chapter_number=...,
    title=...,
    key_points=...,
    characters=...,
    settings=...,
    conflicts=...,
    emotion_tone=raw.get("emotion_tone", ""),
    character_goals=raw.get("character_goals", {}),
    scene_sequence=raw.get("scene_sequence", []),
    foreshadowing=raw.get("foreshadowing", {}),
    pov_character=raw.get("pov_character", ""),
)
```

补充回归测试：模型返回扩展字段后 `outline.json` 与 content prompt 都能读取到。

---

## 三、改进建议（Medium / Low）

### 主题 1：大纲生成鲁棒性

| 项 | 问题 | 文件:行 |
|---|---|---|
| 死循环风险 | 已确认无：`generate_outline()` 与 `patch_missing_chapters()` 都是有上限轮次的 `for` 循环并有取消检查 | — |
| 多进程竞态 | 多进程同时写 `outline.json` 时无文件锁保护（边界） | — |
| DRY 违反 | 三处重复"逐章补洞 + 重试 + 保存" | `outline_generator.py:383 / 697`、`tools/fill_outline_gaps.py:128` |
| 稀疏读取 | `NovelFinalizer` 仍按 compact list 读稀疏大纲会越界 | `src/generators/finalizer/finalizer.py:58` |
| JSON 流式恢复 | `raw_decode` 失败后跳到下一个 `{` 可能恢复到嵌套对象，缺 schema 校验 | `outline_generator.py:985` |

**收敛建议**：补洞策略统一收敛到 `patch_missing_chapters()`，CLI 脚本只做参数解析和调用；抽共享 `load_outline_by_number()` 替代位置访问。

### 主题 2：内容生成与摘要管理

| 项 | 问题 | 文件:行 |
|---|---|---|
| recover_summary 索引 | apply 路径继承大纲按位置读取的越界问题 | `src/tools/recover_summary.py:221`、`finalizer.py:62` |
| 仿写文案不一致 | 无仿写文件时不产出仿写完整版，与 commit 描述不符 | `content_generator.py:806` |
| 多版本章节匹配 | `_chapter_content_exists()` 依赖 `os.listdir()` 顺序 | `content_generator.py:579` |

### 主题 3：GUI 改进

| 项 | 问题 | 文件:行 |
|---|---|---|
| 主线程网络 | `focus_dedup` 在主线程逐条 `embed()`，可能触发网络请求卡住界面 | `novel_params_tab.py:1783`、`focus_dedup.py:123` |
| 配置迁移 | spinbox 语义变更（"新增"→"目标总数"）需要在迁移说明里明确 | `novel_params_tab.py:1254` |
| i18n 不完整 | `NovelParamsTab.changeEvent()` 仅 `pass`；多 group title / tooltip / placeholder 不刷新 | `novel_params_tab.py:1854`、`model_config_tab.py:462`、`progress_tab.py:727` |

**改进方向**：每个 Tab 实现完整 `retranslateUi()`；嵌入向量去重移到 worker 中批量执行。

### 主题 4：配置与依赖

| 项 | 问题 | 文件:行 |
|---|---|---|
| 部分兼容 | 旧变量兼容只覆盖 `GEMINI_FALLBACK_ENABLED / TIMEOUT`，未覆盖 `BASE_URL` | `ai_config.py:258` |
| 文档缺口 | `.env.example` 未说明 `OPENAI_FALLBACK_ENABLED / TIMEOUT` | `.env.example:45` |
| 章节正则 | 只识别 `第\d+章`，不识别 `第一章 / 第十章` | `knowledge_base.py:75` |
| 缓存 schema | temp pickle 缺 `schema_version`，旧文件恢复会重复向量 | `knowledge_base.py:269` |

---

## 四、值得肯定的设计

- **稀疏列表 + None 占位**：用 `None` 保留洞位，比过去排序后按位置访问更安全，能显式暴露缺失章节
- **自动补洞优先于强制全量重生**：节省 token，也避免覆盖已写正文对应的大纲
- **`is_target_chapter` 区分**：避免单章重生成覆盖已有摘要，业务语义拆分正确
- **合并仿写降级**：仿写文件读取失败不影响原版合并，附加产物失败不拖垮主产物
- **`model_config` 深合并**：减少用户复制 API key / base_url 的需要，降低配置漂移风险

---

## 五、后续行动建议

### 必须修复（阻塞发布）

1. CI/tests 断裂（H1）
2. `switch_language()` zh→en 崩溃（H2）
3. 进度并集误判（H3）
4. GUI pipeline 失败后仍成功（H4）
5. 扩展大纲字段丢失（H5）

### 建议补充测试

| 模块 | 用例 |
|---|---|
| `_load_progress()` | summary-only / disk-only / disk+summary / 中间缺章 |
| `PipelineWorker` | 章节失败后最终失败收敛 |
| `switch_language()` | zh → en 路径 |
| `OutlineGenerator` | 扩展字段落盘 + 回读 |
| `KnowledgeBase` | 旧 `.temp_*` 文件恢复语义 |

### 文档缺口

- `.env.example` 补充 fallback 迁移说明
- GUI 文案说明 spinbox 是目标总数语义
- README / CLAUDE.md 同步说明 `outline_auto_patch_holes`、`outline_gap_*`、稀疏大纲修复脚本和测试运行方式

### 发布建议

> 在上述 High 项修复并让干净 checkout 的 CI 通过前，**不建议基于当前 HEAD 打 release tag**。

---

## 附录 A：评审范围 commit 清单（30 项）

```
a1232e7 feat(outline): 添加自动补洞功能以处理大纲缺失章节
eb8f319 fix(content): 处理大纲缺失槽位并改进合并日志
7f8cf26 feat(gui): 描写侧重列表语义去重 (Tier B 嵌入向量 + Tier A Jaccard 兜底)
3576b44 fix(gui): 配角/反派 spinbox 改为目标总数语义,扣除已有再新增
c4cf264 fix(gui): 切换配置文件后故事创意输入框未同步新种子内容
f3ffef9 fix(content): pipeline 连续模式漏写章节摘要导致后续章节失去前情
0d4751e feat(gui): 写作指南改用增补模式 + 自动加载 core_seed 作为故事创意
449c6da feat(tools): 新增 fill_outline_gaps.py 经济补生成脚本
b8267c7 fix(outline-load): _load_outline 改用位置对齐稀疏列表 + 去重防御
f8216af docs(gui): 明示「大纲范围」仅作用于「仅生成大纲」按钮
04de2b8 fix(outline-gui): 仅生成大纲 3 条件独立组合（范围/强制/提示词）
f584e19 fix(outline): GUI 自定义范围 / 强制重生成大纲未传 force_regenerate
eb2e820 feat(outline+gui): 提升大纲鲁棒性、新增温度配置与三层 Prompt
7d9d7f0 feat(merge): 合并所有章节时自动产出仿写完整版
d88a101 fix(progress): 修复已存在章节被误判"未生成"导致反复覆盖的 bug
7ccc0cc chore(gitignore): 更新 .gitignore 以简化测试文件管理
fc6e2e8 移除 .gitignore 和 tests 文件夹的跟踪
cc97f5c chore(gitignore): 更新忽略规则以放行测试代码
e93d2b7 fix(cli): --start-chapter 越界时报错并退出，避免假成功 (#27)
577d42a refactor(content): 删除未使用的 _regenerate_specific_chapter (#25)
14ce8dd fix(content): 重生成单章不再覆盖 summary.json (#23)
16e10e3 fix(config): OpenAI fallback 兼容旧变量名 GEMINI_FALLBACK_* 并提示废弃
ef01dbf fix(test): 修正 test_get_openai_config_includes_fallback 环境变量
6eb5a5b chore(gitignore): 放行 tests 测试代码入库
0f791de fix(gui): worker 调用 create_model 时传入 context 参数
d017628 chore(deps): 显式声明 httpx 依赖
00afe70 fix(knowledge_base): 章节切分丢弃首段非章节内容
989616a fix(knowledge_base): 修复从临时文件恢复时丢失已缓存 chunk 的回归
19c4207 feat(gui): 语言切换无需重启，热切换翻译器 + UI 文本刷新
```

## 附录 B：交叉引用

- 修复路线图：[`./2026-05-07-fix-roadmap.md`](./2026-05-07-fix-roadmap.md)
- 项目架构说明：[`../../CLAUDE.md`](../../CLAUDE.md)
