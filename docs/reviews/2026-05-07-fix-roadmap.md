# 修复路线图 · 2026-05-07

> **关联评审**：[`./2026-05-07-codex-review.md`](./2026-05-07-codex-review.md)
> **目标**：让 5 个 High 项全部修复，干净 checkout 的 CI 通过，可基于 HEAD 打 release tag
> **总估计工时**：8–12 人时（不含编写测试用例时间）

---

## 总体策略

### 排序原则

1. **基建先行**：测试基础设施必须最先恢复，否则后续修复缺乏自动化验证
2. **独立优先**：无依赖、风险低、可独立验证的修复优先（快速回收信心）
3. **状态模型集中重构**：H3 状态语义会影响 H4，必须 H3 → H4 串行
4. **多文件设计闭环**：H5 涉及 prompt / data_structure / generator 三处，需要 H1 提供的测试守护
5. **Medium / Low 收敛**：在 High 项稳定后批量处理，避免合并冲突

### 阶段总览

| 阶段 | 范围 | 估算 | 阻塞下游？ | 可并行？ |
|---|---|---|---|---|
| Phase 0 | H1：CI/tests 基建 | 1.5h | ✅ 阻塞所有验证 | 否 |
| Phase 1 | H2：translator 崩溃 | 0.5h | 否 | ✅ 与 P2/P4 并行 |
| Phase 2 | H3：progress 状态重构 | 2.5h | ✅ 阻塞 P3 | 否 |
| Phase 3 | H4：pipeline 成功收敛 | 1.5h | 否 | 否（依赖 P2） |
| Phase 4 | H5：扩展字段透传 | 1.5h | 否 | ✅ 与 P1 并行 |
| Phase 5 | Medium 收敛 | 2–3h | 否 | 部分并行 |
| Phase 6 | Low + 文档 | 1h | 否 | ✅ 全程可穿插 |

---

## Phase 0 — 基建恢复（H1）

### 目标

让 `tests/` 重新被 Git 跟踪，CI 在干净 checkout 下 `pytest tests/` 有真实测试可跑。

### 任务清单

- [ ] **0.1** 修改 `.gitignore`：保留测试代码，仅忽略测试产物
- [ ] **0.2** 恢复 `tests/__init__.py`、`tests/conftest.py`（如缺失）
- [ ] **0.3** 恢复或重建 `tests/test_fallback_logic.py`（参考 `ef01dbf` 提交内容）
- [ ] **0.4** 添加 `tests/README.md` 说明测试约定
- [ ] **0.5** 本地 `pytest tests/ -v` 跑通
- [ ] **0.6** 在 `.github/workflows/ci.yml` 添加缓存 + 失败时上传日志

### 修改示例

```gitignore
# tests/ 处理：忽略产物，保留代码
tests/__pycache__/
tests/.pytest_cache/
tests/htmlcov/
tests/.coverage
!tests/**/*.py
!tests/conftest.py
!tests/__init__.py
!tests/README.md
```

### 验证

```bash
# 必须返回非空
git ls-files tests | head

# 必须通过
python -m pytest tests/ -v --tb=short
```

### 验收标准

- `git ls-files tests` 至少包含 `__init__.py`、`conftest.py`、1 个 `test_*.py`
- 本地与 CI 双端 `pytest tests/` 退出码 0
- CI workflow 可见测试结果汇总

### 回滚策略

如果 `pytest` 有遗留依赖问题（如 `FlagEmbedding` import），先在 `tests/conftest.py` 中加 import skip 装饰器，不阻塞 Phase 0 推进。

---

## Phase 1 — translator 崩溃修复（H2）

### 目标

GUI 默认中文环境下，`switch_language()` 切换到英文不再 `AttributeError`。

### 任务清单

- [ ] **1.1** 在 `src/gui/i18n/translator.py:148` 改用 `getattr(app, "_translators", [])`
- [ ] **1.2** 在 `load_translation()` 入口先 `app._translators = getattr(app, "_translators", [])`，统一初始化
- [ ] **1.3** 添加 `tests/test_translator.py` 覆盖 zh→en、en→zh、zh→zh 三条路径
- [ ] **1.4** 手动验证：`python gui_main.py` 启动后切语言无 traceback

### 验收标准

- 单元测试 3 路径全绿
- 手动切换 5 次以上无报错

### 回滚策略

`git revert` 即可，无副作用。

---

## Phase 2 — progress 状态模型重构（H3）

### 目标

完成态以"正文存在"为硬条件；`summary-only` 不再被误判为已完成。

### 任务清单

- [ ] **2.1** 引入 `ChapterStatus` 枚举（`MISSING / CONTENT_ONLY / SUMMARY_ONLY / COMPLETE`）
- [ ] **2.2** 重构 `src/generators/content/content_generator.py:213` `_load_progress()`
- [ ] **2.3** 同步重构 `src/gui/workers/pipeline_worker.py:261` 进度计算
- [ ] **2.4** `SUMMARY_ONLY` 章节策略：默认重生成正文；CLI 参数 `--allow-stale-summary` 时跳过
- [ ] **2.5** 日志：每个状态分类计数并输出 INFO 级别
- [ ] **2.6** 添加 `tests/test_load_progress.py` 覆盖 4 种状态 × 3 种排列（连续/中间缺/末尾缺）

### 推荐数据结构

```python
from enum import Enum
from dataclasses import dataclass

class ChapterStatus(str, Enum):
    MISSING = "missing"
    CONTENT_ONLY = "content_only"      # 有正文无摘要 → 待 finalize
    SUMMARY_ONLY = "summary_only"      # 仅摘要无正文 → 异常态
    COMPLETE = "complete"              # 正文 + 摘要齐全

@dataclass
class ChapterState:
    number: int
    status: ChapterStatus
    content_path: str | None = None
    summary_text: str | None = None
```

### 验收标准

- `_load_progress()` 单元测试 12 用例（4×3）全绿
- 人工构造 `summary-only` 场景，pipeline 不再"假成功"
- 已存在的 `recover_summary.py` 工具仍可用（向后兼容）

### 风险与回滚

- **风险**：状态语义变化可能影响 `recover_summary.py`、`finalizer.py`
- **回滚**：保留旧 `_load_progress()` 为 `_load_progress_legacy()`，通过环境变量 `OCNOVEL_LEGACY_PROGRESS=1` 切换

---

## Phase 3 — pipeline 成功判定收敛（H4）

> **依赖**：Phase 2 完成（`ChapterStatus` 枚举可用）

### 目标

GUI pipeline 在连续模式下任一章节失败即中止；最终 `pipeline_finished` 信号反映真实成败。

### 任务清单

- [ ] **3.1** `pipeline_worker.py` 引入 `failed_chapters: list[int]` 状态
- [ ] **3.2** 修改 `_run_continuous_mode()`：失败立即 `break`
- [ ] **3.3** 修改 `_run_target_chapters()`：允许多章独立失败但记录
- [ ] **3.4** 终态判定：`overall_ok = len(failed_chapters) == 0`
- [ ] **3.5** 失败列表非空时跳过自动合并并通过 signal 传出失败章节号
- [ ] **3.6** 添加 `tests/test_pipeline_worker.py` mock 失败场景

### 关键代码片段

```python
# _run_continuous_mode
failed = []
for ch in target_range:
    if self._cancelled:
        break
    ok = self._generate_one(ch)
    if not ok:
        failed.append(ch)
        self.chapter_failed.emit(ch)
        break  # 连续模式中止
self._failed_chapters = failed

# 终态
overall = len(self._failed_chapters) == 0
if overall and self._auto_merge_enabled:
    self._do_merge()
self.pipeline_finished.emit(overall, self._failed_chapters)  # signal 增加列表参数
```

### 验收标准

- mock 单元测试覆盖：第 N 章失败时 emit(False) 且不触发合并
- 现有成功路径回归：emit(True) 且触发合并
- GUI 手动验证：故意制造 API 失败，进度面板正确标红

### 兼容性提示

`pipeline_finished` signal 签名从 `(bool,)` 改为 `(bool, list)`，需要同步 `main_window.py` 中的连接函数。

---

## Phase 4 — 大纲扩展字段透传（H5）

### 目标

Prompt 要求的扩展字段被实际写入 `outline.json`，content prompt 能读取。

### 任务清单

- [ ] **4.1** 审查 `src/generators/common/data_structures.py:13` `ChapterOutline` 字段已存在
- [ ] **4.2** 修改 `outline_generator.py:627` `_generate_batch()` 构造调用
- [ ] **4.3** 修改 `outline_generator.py:880` `_generate_single_chapter_outline()` 构造调用
- [ ] **4.4** 添加类型归一化辅助 `_normalize_extended_fields(raw: dict) -> dict`
- [ ] **4.5** `outline.json` schema 校验：缺字段时回填默认值并记录 warning
- [ ] **4.6** 添加 `tests/test_outline_extended_fields.py` 覆盖：完整字段 / 缺字段 / 类型错误

### 类型归一化建议

```python
def _normalize_extended_fields(raw: dict) -> dict:
    return {
        "emotion_tone": str(raw.get("emotion_tone", "")).strip(),
        "character_goals": dict(raw.get("character_goals") or {}),
        "scene_sequence": list(raw.get("scene_sequence") or []),
        "foreshadowing": dict(raw.get("foreshadowing") or {}),
        "pov_character": str(raw.get("pov_character", "")).strip(),
    }
```

### 验收标准

- 单元测试 3 路径全绿
- 端到端：生成大纲后 `outline.json` 含扩展字段；content prompt 渲染时能引用
- 旧 outline 文件加载不报错（默认值填充）

---

## Phase 5 — Medium 收敛（按主题）

### 5.1 大纲补洞 DRY 整合

- 收敛三处补洞实现到 `OutlineGenerator.patch_missing_chapters()`
- `tools/fill_outline_gaps.py` 改为薄 CLI 封装
- 涉及：`outline_generator.py:383 / 697`、`tools/fill_outline_gaps.py:128`

### 5.2 稀疏大纲统一读取

- 抽 `OutlineGenerator.load_outline_by_number(n) -> ChapterOutline | None`
- `NovelFinalizer`、`recover_summary.py` 改用此方法
- 涉及：`finalizer.py:58 / 62`、`recover_summary.py:221`

### 5.3 focus_dedup 异步化

- 嵌入向量调用从主线程移到 `WritingGuideWorker`
- 主线程只接收已去重结果
- 涉及：`novel_params_tab.py:1783`、`focus_dedup.py:123`

### 5.4 i18n retranslateUi 完整覆盖

- 每个 Tab 实现完整 `retranslateUi()`
- 涉及：`novel_params_tab.py:1854`、`model_config_tab.py:462`、`progress_tab.py:727`

### 5.5 JSON 流式恢复 schema 校验

- `raw_decode` 失败回退时校验对象包含 `title / key_points / characters / settings / conflicts`
- 涉及：`outline_generator.py:985`

### 5.6 章节匹配排序

- `_chapter_content_exists()` 按修改时间排序，多候选时打 warning
- 涉及：`content_generator.py:579`

---

## Phase 6 — Low 优化与文档

### 6.1 配置兼容补齐

- `ai_config.py:258` 兼容 `GEMINI_FALLBACK_BASE_URL`
- `.env.example:45` 补充 `OPENAI_FALLBACK_*` 说明

### 6.2 章节正则扩展

- `knowledge_base.py:75` 支持 `第一章 / 第十章 / 第一百零一章` 等中文数字
- 推荐使用 `cn2an` 库或自写正则映射

### 6.3 KB temp 文件 schema version

- `knowledge_base.py:269` temp pickle 写入 `{"schema_version": 2, "next_chunk_idx": ...}`
- 加载旧文件（无 version）时保守丢弃或重建

### 6.4 文档补齐

- `.env.example` 补 fallback 迁移说明
- `CLAUDE.md` 补 `outline_auto_patch_holes`、`outline_gap_*` 配置说明
- `README.md` 补"如何运行测试"段落
- GUI 文案：spinbox 旁加 tooltip 说明"目标总数（含已有）"

---

## 里程碑与发布门禁

| 里程碑 | 完成条件 | 解锁 |
|---|---|---|
| **M0** | Phase 0 完成 | 测试基础设施可用 |
| **M1** | Phase 1–4 完成 | 5 个 High 全部修复 |
| **M2** | Phase 5 完成 | Medium 项归零 |
| **M3** | Phase 6 完成 + CI 全绿 | **可打 release tag** |

### 发布前 Checklist

- [ ] 干净 checkout（无 ignored 文件）`pytest tests/` 通过
- [ ] CI 双平台（macOS arm64 / Windows x64）打包成功
- [ ] 手工烟雾测试：CLI `auto` + GUI pipeline 各跑 3 章
- [ ] `CHANGELOG.md` 列出本次所有 High 修复
- [ ] `git tag v1.0.x && git push origin v1.0.x`（参考 `CLAUDE.md` 发布流程）

---

## 风险登记

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| Phase 2 状态重构破坏现有 outline.json | 中 | 高 | 保留 legacy 模式 + schema version 字段 |
| `pipeline_finished` 签名变更影响其他 connect | 中 | 中 | grep 全仓 `pipeline_finished.connect` 一次性改完 |
| 测试恢复后发现历史断言失效 | 高 | 中 | Phase 0 完成后预留 0.5h 修复历史用例 |
| Phase 4 修改影响已生成的旧 outline | 低 | 低 | 默认值填充策略覆盖 |
| Medium 收敛与 High 修复合并冲突 | 中 | 低 | High 先合入 main，Medium 后续 PR |

---

## 提交与分支策略

参考 `CLAUDE.md` 的 Git Conventions：

```bash
# 每个 Phase 一个 feature branch
git checkout -b fix/h1-restore-tests
# ... 实现 + 测试
git commit -m "fix(ci): 恢复 tests/ 跟踪并修正 .gitignore"

# Phase 1
git checkout -b fix/h2-translator-zh-to-en
git commit -m "fix(gui): 修复语言切换 zh→en 时 _translators 未初始化"

# 以此类推
```

每个 PR 在描述中：
1. 引用本路线图章节
2. 列出验证命令
3. 附 `pytest` 输出截图

---

## 附录：依赖图

```
H1 (CI/tests)
  ├─→ 守护所有后续修复的验证
  │
  ├─→ H2 (translator) ─────────────┐
  │                                 │
  ├─→ H3 (progress) ─→ H4 (pipeline)┤
  │                                 │
  └─→ H5 (extended fields) ────────┤
                                    ↓
                              Phase 5 Medium
                                    ↓
                              Phase 6 Low + Docs
                                    ↓
                                 Release
```
