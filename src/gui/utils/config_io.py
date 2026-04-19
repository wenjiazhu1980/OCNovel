""".env 和 config.json 读写工具"""
import json
import logging
import os
import re
import tempfile
from typing import Dict, Any


logger = logging.getLogger(__name__)


def _atomic_write_text(path: str, content: str, encoding: str = 'utf-8') -> None:
    """原子写入文本：先写同目录下的临时文件，再 os.replace() 替换目标。

    保证中断/断电时不会留下半截配置（POSIX 与 Windows 上 os.replace 均为原子操作）。
    失败会清理临时文件并抛出原始异常。
    """
    abs_path = os.path.abspath(path)
    target_dir = os.path.dirname(abs_path) or '.'
    os.makedirs(target_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix='.' + os.path.basename(abs_path) + '.',
        suffix='.tmp',
        dir=target_dir,
    )
    try:
        with os.fdopen(fd, 'w', encoding=encoding, newline='') as f:
            f.write(content)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # 某些文件系统（网络盘、虚拟盘）不支持 fsync，忽略
                pass
        os.replace(tmp_path, abs_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


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
    """写入 .env 文件，保留原有注释行和顺序（原子写）"""
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

    _atomic_write_text(path, '\n'.join(lines) + '\n')


def load_config(path: str) -> Dict[str, Any]:
    """加载 config.json"""
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_config(path: str, data: Dict[str, Any]):
    """保存 config.json，ensure_ascii=False, indent=2（原子写）"""
    content = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    _atomic_write_text(path, content)
