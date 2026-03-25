""".env 和 config.json 读写工具"""
import json
import os
import re
from typing import Dict, Any, Optional


def load_env(path: str) -> Dict[str, str]:
    """解析 .env 文件，返回 key-value 字典（保留注释行用于写回）"""
    data = {}
    if not os.path.exists(path):
        return data
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            match = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)=(.*)', line)
            if match:
                key = match.group(1)
                value = match.group(2).strip()
                # 去除引号
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                data[key] = value
    return data


def save_env(path: str, data: Dict[str, str]):
    """写入 .env 文件，保留原有注释行和顺序"""
    lines = []
    existing_keys = set()

    # 读取原文件保留注释和顺序
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                raw = line.rstrip('\n')
                stripped = raw.strip()
                if not stripped or stripped.startswith('#'):
                    lines.append(raw)
                    continue
                match = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)=', stripped)
                if match:
                    key = match.group(1)
                    existing_keys.add(key)
                    if key in data:
                        lines.append(f'{key}={data[key]}')
                    else:
                        lines.append(raw)
                else:
                    lines.append(raw)

    # 追加新增的 key
    for key, value in data.items():
        if key not in existing_keys:
            lines.append(f'{key}={value}')

    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def load_config(path: str) -> Dict[str, Any]:
    """加载 config.json"""
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_config(path: str, data: Dict[str, Any]):
    """保存 config.json，ensure_ascii=False, indent=2"""
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
