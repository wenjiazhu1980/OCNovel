# Tests · 测试约定

## 运行

```bash
# 全量
python -m pytest tests/ -v

# 单文件
python -m pytest tests/test_translator_h2.py -v

# 静默 + 失败摘要
python -m pytest tests/ -q --tb=short

# 跳过慢测试（依赖 FlagEmbedding/远程服务的）
python -m pytest tests/ -m "not slow"
```

## 命名约定

- 测试文件：`test_<被测模块>.py`
- 类：`Test<被测组件>`
- 函数：`test_<行为描述_条件>`
- 回归测试：附 `_<issueid>` 后缀，例如 `test_translator_h2.py`

## 必备 mock 套路

- `BaseModel`：用 `MagicMock(spec=BaseModel)`，避免触发真实 API
- 文件 IO：用 `tmp_path` fixture
- Qt：headless 环境用 `MagicMock(spec=QApplication)`，无需 `QApplication([])`

## 跟踪策略

- 测试代码本体（`*.py / conftest.py / __init__.py`）入库
- 测试产物（`__pycache__ / .pytest_cache / .coverage / htmlcov / data / output`）忽略
- 详见仓库根 `.gitignore` `tests/` 段落

## 已知问题

- `test_chapter_list_and_regen.py::TestPipelineWorkerTargetChapters::test_run_allows_regen_when_outline_covers_selected_chapter_only`：mock 未同步 `patch_missing_chapters` 返回 `(succeeded, still_missing)` 元组的新签名；待 follow-up 修复
- 部分 KB 测试依赖 FlagEmbedding，无法在最小依赖环境运行；建议加 `@pytest.mark.slow` 标记后通过 marker 隔离

## CI 集成

参考 `.github/workflows/ci.yml`，PR 与 push 触发：

```yaml
- name: Run tests
  run: python -m pytest tests/ -v --tb=short
```
