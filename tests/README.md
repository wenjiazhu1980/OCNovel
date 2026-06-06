# Tests · 测试约定

## 运行

```bash
# 全量
python -m pytest tests/ -v

# 单文件
python -m pytest tests/test_translator_h2.py -v

# 静默 + 失败摘要
python -m pytest tests/ -q --tb=short

# 与 CI 一致：静默运行并输出失败摘要
python -m pytest tests/ --tb=short -q
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

## 当前状态

- 当前测试套件为纯单元测试路径，KnowledgeBase 相关测试使用 mock，避免真实加载 FlagEmbedding/远程服务。
- 如未来新增依赖大模型、网络服务或大体积本地模型的慢测试，应补充 `@pytest.mark.slow` 标记，并在 `pytest.ini` 注册 marker 后再使用 `-m "not slow"` 隔离。

## CI 集成

参考 `.github/workflows/ci.yml`，PR 与 push 触发：

```yaml
- name: Run tests
  run: python -m pytest tests/ --tb=short -q
```
