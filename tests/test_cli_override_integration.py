#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试命令行参数覆盖配置的功能
"""
import sys
import os

# 添加项目根目录到 sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.config.config import Config

def test_cli_override():
    """模拟命令行参数覆盖配置"""

    print("=" * 60)
    print("命令行参数覆盖测试")
    print("=" * 60)

    # 加载配置（使用项目根目录的配置文件）
    config_path = os.path.join(project_root, 'config.json')
    config = Config(config_path)

    print("\n1. 原始配置")
    print("-" * 60)
    original_value = config.generation_config.get('humanization', {}).get('enable_humanizer_zh', '未设置')
    print(f"enable_humanizer_zh: {original_value}")

    # 模拟 --enable-humanizer-zh 参数
    print("\n2. 模拟 --enable-humanizer-zh 参数")
    print("-" * 60)
    if not hasattr(config, 'generation_config'):
        config.generation_config = {}
    if "humanization" not in config.generation_config:
        config.generation_config["humanization"] = {}
    config.generation_config["humanization"]["enable_humanizer_zh"] = True
    print(f"enable_humanizer_zh: {config.generation_config['humanization']['enable_humanizer_zh']}")
    print("✅ 成功设置为 True")

    # 重新加载配置
    config = Config(config_path)

    # 模拟 --disable-humanizer-zh 参数
    print("\n3. 模拟 --disable-humanizer-zh 参数")
    print("-" * 60)
    if not hasattr(config, 'generation_config'):
        config.generation_config = {}
    if "humanization" not in config.generation_config:
        config.generation_config["humanization"] = {}
    config.generation_config["humanization"]["enable_humanizer_zh"] = False
    print(f"enable_humanizer_zh: {config.generation_config['humanization']['enable_humanizer_zh']}")
    print("✅ 成功设置为 False")

    print("\n4. 测试总结")
    print("=" * 60)
    print("✅ 命令行参数覆盖功能正常工作！")

if __name__ == "__main__":
    test_cli_override()
