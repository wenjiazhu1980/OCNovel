#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试 Humanizer-zh 功能是否正常工作
"""
import sys
import os

# 添加项目根目录到 sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.config.config import Config
from src.generators.prompts import get_chapter_prompt

def test_humanizer_zh():
    """测试 Humanizer-zh 规则是否被正确应用"""

    print("=" * 60)
    print("Humanizer-zh 功能测试")
    print("=" * 60)

    # 加载配置（使用项目根目录的配置文件）
    config_path = os.path.join(project_root, 'config.json')
    config = Config(config_path)
    humanization_config = config.generation_config.get('humanization', {})

    print("\n1. 配置加载测试")
    print("-" * 60)
    print(f"enable_humanizer_zh: {humanization_config.get('enable_humanizer_zh', '未设置')}")
    print(f"temperature: {humanization_config.get('temperature', '未设置')}")
    print(f"dialogue_ratio: {humanization_config.get('dialogue_ratio', '未设置')}")

    # 测试章节 Prompt 生成
    print("\n2. Prompt 生成测试")
    print("-" * 60)

    test_outline = {
        'chapter_number': 1,
        'title': '测试章节',
        'key_points': ['测试要点1', '测试要点2'],
        'characters': ['主角', '配角'],
        'settings': ['测试场景'],
        'conflicts': ['测试冲突']
    }

    test_references = {}

    # 测试启用 Humanizer-zh
    print("\n测试场景 A: 启用 Humanizer-zh")
    humanization_config_enabled = humanization_config.copy()
    humanization_config_enabled['enable_humanizer_zh'] = True

    prompt_enabled = get_chapter_prompt(
        outline=test_outline,
        references=test_references,
        humanization_config=humanization_config_enabled
    )

    # 检查关键标记
    markers_enabled = {
        'Humanizer-zh 核心原则': 'Humanizer-zh 核心原则' in prompt_enabled,
        'AI 写作模式黑名单': 'AI 写作模式黑名单' in prompt_enabled,
        '节奏变化要求': '节奏变化要求' in prompt_enabled,
        '生成后质量自检': '生成后质量自检' in prompt_enabled,
        '删除填充短语': '删除填充短语' in prompt_enabled,
        '打破公式结构': '打破公式结构' in prompt_enabled,
    }

    print("关键规则检测:")
    for marker, found in markers_enabled.items():
        status = "✅" if found else "❌"
        print(f"  {status} {marker}: {'已包含' if found else '未包含'}")

    # 测试禁用 Humanizer-zh
    print("\n测试场景 B: 禁用 Humanizer-zh")
    humanization_config_disabled = humanization_config.copy()
    humanization_config_disabled['enable_humanizer_zh'] = False

    prompt_disabled = get_chapter_prompt(
        outline=test_outline,
        references=test_references,
        humanization_config=humanization_config_disabled
    )

    markers_disabled = {
        'Humanizer-zh 核心原则': 'Humanizer-zh 核心原则' in prompt_disabled,
        'AI 写作模式黑名单': 'AI 写作模式黑名单' in prompt_disabled,
        '节奏变化要求': '节奏变化要求' in prompt_disabled,
        '生成后质量自检': '生成后质量自检' in prompt_disabled,
    }

    print("关键规则检测:")
    for marker, found in markers_disabled.items():
        status = "✅" if not found else "❌"
        print(f"  {status} {marker}: {'已排除' if not found else '仍包含'}")

    # 统计 Prompt 长度差异
    print("\n3. Prompt 长度对比")
    print("-" * 60)
    print(f"启用 Humanizer-zh: {len(prompt_enabled)} 字符")
    print(f"禁用 Humanizer-zh: {len(prompt_disabled)} 字符")
    print(f"差异: {len(prompt_enabled) - len(prompt_disabled)} 字符 ({(len(prompt_enabled) - len(prompt_disabled)) / len(prompt_disabled) * 100:.1f}%)")

    # 总结
    print("\n4. 测试总结")
    print("=" * 60)

    all_enabled_found = all(markers_enabled.values())
    all_disabled_excluded = all(not v for v in markers_disabled.values())

    if all_enabled_found and all_disabled_excluded:
        print("✅ 所有测试通过！Humanizer-zh 功能正常工作。")
    else:
        print("❌ 部分测试失败，请检查实现。")
        if not all_enabled_found:
            print("  - 启用时部分规则未包含")
        if not all_disabled_excluded:
            print("  - 禁用时部分规则仍然包含")
    assert all_enabled_found, "启用 Humanizer-zh 时部分关键规则未包含"
    assert all_disabled_excluded, "禁用 Humanizer-zh 时部分关键规则仍然存在"

if __name__ == "__main__":
    success = test_humanizer_zh()
    exit(0 if success else 1)
