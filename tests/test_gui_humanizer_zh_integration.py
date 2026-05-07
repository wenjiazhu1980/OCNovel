#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试 GUI 界面的 Humanizer-zh 开关是否正确添加
"""
import sys
import os

# 添加项目根目录到 sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

def test_gui_humanizer_zh():
    """测试 GUI 界面的 Humanizer-zh 开关"""

    print("=" * 60)
    print("GUI Humanizer-zh 开关测试")
    print("=" * 60)

    # 读取源代码文件
    gui_file = os.path.join(project_root, "src/gui/tabs/novel_params_tab.py")

    with open(gui_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # 检查关键代码是否存在
    checks = {
        "界面控件定义": 'self._cb_humanizer_zh = QCheckBox(self.tr("Humanizer-zh 增强"))' in content,
        "控件添加到表单": 'h_form.addRow("", self._cb_humanizer_zh)' in content,
        "加载配置": 'self._cb_humanizer_zh.setChecked(bool(hum.get("enable_humanizer_zh", True)))' in content,
        "保存配置": '"enable_humanizer_zh": self._cb_humanizer_zh.isChecked()' in content,
        "默认配置": '"enable_humanizer_zh": True' in content,
        "工具提示": 'self._cb_humanizer_zh.setToolTip(self.tr("启用 Humanizer-zh 人性化增强规则,降低 AI 写作痕迹"))' in content,
    }

    print("\n检查结果:")
    print("-" * 60)

    all_passed = True
    for check_name, result in checks.items():
        status = "✅" if result else "❌"
        print(f"{status} {check_name}: {'通过' if result else '失败'}")
        if not result:
            all_passed = False

    print("\n总结:")
    print("=" * 60)
    if all_passed:
        print("✅ 所有检查通过！GUI 界面的 Humanizer-zh 开关已正确添加。")
        print("\n界面位置：小说参数 Tab -> 人性化参数 -> Humanizer-zh 增强")
        print("\n功能说明：")
        print("  - 勾选：启用 Humanizer-zh 人性化增强规则")
        print("  - 取消勾选：禁用 Humanizer-zh 人性化增强规则")
        print("  - 默认状态：勾选（启用）")
    else:
        print("❌ 部分检查失败，请检查代码。")
    assert all_passed, "GUI 界面的 Humanizer-zh 开关检查未全部通过"

if __name__ == "__main__":
    test_gui_humanizer_zh()
    exit(0)
