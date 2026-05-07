# Humanizer-zh 集成测试

本目录包含 Humanizer-zh 功能的集成测试脚本。

## 测试脚本列表

### 1. test_humanizer_zh_integration.py
**功能：** 测试 Humanizer-zh 核心功能是否正常工作

**测试内容：**
- 配置加载测试
- Prompt 生成测试（启用/禁用）
- 规则完整性验证
- Prompt 长度对比

**运行方法：**
```bash
python tests/test_humanizer_zh_integration.py
```

**预期结果：**
```
✅ 所有测试通过！Humanizer-zh 功能正常工作。
```

---

### 2. test_cli_override_integration.py
**功能：** 测试命令行参数覆盖配置的功能

**测试内容：**
- 原始配置加载
- --enable-humanizer-zh 参数模拟
- --disable-humanizer-zh 参数模拟
- 配置覆盖验证

**运行方法：**
```bash
python tests/test_cli_override_integration.py
```

**预期结果：**
```
✅ 命令行参数覆盖功能正常工作！
```

---

### 3. test_gui_humanizer_zh_integration.py
**功能：** 测试 GUI 界面的 Humanizer-zh 开关是否正确添加

**测试内容：**
- 界面控件定义检查
- 控件添加到表单检查
- 加载配置检查
- 保存配置检查
- 默认配置检查
- 工具提示检查

**运行方法：**
```bash
python tests/test_gui_humanizer_zh_integration.py
```

**预期结果：**
```
✅ 所有检查通过！GUI 界面的 Humanizer-zh 开关已正确添加。
```

---

## 运行所有测试

```bash
# 方法一：逐个运行
python tests/test_humanizer_zh_integration.py
python tests/test_cli_override_integration.py
python tests/test_gui_humanizer_zh_integration.py

# 方法二：使用 pytest（如果已安装）
pytest tests/test_*_integration.py -v
```

## 测试覆盖范围

### 功能测试
- ✅ Humanizer-zh 规则注入
- ✅ 规则启用/禁用
- ✅ Prompt 长度变化
- ✅ 配置加载/保存

### 接口测试
- ✅ 命令行参数接口
- ✅ 配置文件接口
- ✅ GUI 界面接口

### 集成测试
- ✅ 配置系统集成
- ✅ Prompt 生成系统集成
- ✅ GUI 系统集成

## 测试环境要求

- Python 3.9+
- 项目依赖已安装（requirements.txt）
- 配置文件存在（config.json）

## 故障排查

### 测试失败：配置文件不存在
**错误信息：** `FileNotFoundError: config.json`

**解决方法：**
```bash
# 从示例配置创建配置文件
cp config.json.example config.json
```

### 测试失败：模块导入错误
**错误信息：** `ModuleNotFoundError: No module named 'src'`

**解决方法：**
```bash
# 确保从项目根目录运行测试
cd /path/to/OCNovel
python tests/test_humanizer_zh_integration.py
```

### 测试失败：规则未包含
**错误信息：** `❌ 启用时部分规则未包含`

**解决方法：**
1. 检查 `src/generators/humanization_prompts.py` 是否包含所有规则函数
2. 检查 `src/generators/prompts.py` 是否正确调用 `get_enhanced_humanization_prompt()`
3. 重新运行测试

## 相关文档

- **使用指南：** `/Users/zzz/.claude/plans/humanizer-zh-usage-guide.md`
- **实施报告：** `/Users/zzz/.claude/plans/humanizer-zh-phase1-implementation.md`
- **测试报告：** `/Users/zzz/.claude/plans/humanizer-zh-test-report.md`
- **GUI 修改报告：** `/Users/zzz/.claude/plans/humanizer-zh-gui-modification-report.md`

## 维护说明

### 添加新测试
1. 在 `tests/` 目录下创建新的测试文件
2. 文件名格式：`test_<功能名>_integration.py`
3. 添加到本 README 的测试脚本列表中

### 更新测试
1. 修改对应的测试文件
2. 运行测试验证修改
3. 更新本 README 的相关说明

---

**创建日期：** 2026-03-29
**维护者：** 浮浮酱
