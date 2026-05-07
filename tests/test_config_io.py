# -*- coding: utf-8 -*-
"""config_io 原子写与解析测试

覆盖 src/gui/utils/config_io.py:
- save_env / save_config 通过 tempfile + os.replace 原子替换目标文件
- 写入失败时清理临时文件，不留残骸
- 读写往返保真（key-value、注释保留、UTF-8 非 ASCII）
"""
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.gui.utils.config_io import (
    _atomic_write_text,
    load_config,
    load_env,
    save_config,
    save_env,
)


def test_atomic_write_creates_file(tmp_path: Path):
    """_atomic_write_text 正常写入"""
    target = tmp_path / "foo.txt"
    _atomic_write_text(str(target), "hello\nworld\n")
    assert target.read_text(encoding="utf-8") == "hello\nworld\n"


def test_atomic_write_no_tempfile_leak_on_failure(tmp_path: Path):
    """写入过程抛异常时临时文件必须被清理"""
    target = tmp_path / "cfg.json"
    target.write_text("{}", encoding="utf-8")

    # 模拟 os.replace 失败
    with patch("src.gui.utils.config_io.os.replace", side_effect=OSError("simulated")):
        with pytest.raises(OSError):
            _atomic_write_text(str(target), "new content")

    # 目标文件保持原状
    assert target.read_text(encoding="utf-8") == "{}"
    # 临时文件必须被清理（目录下只剩原目标文件）
    remaining = [p.name for p in tmp_path.iterdir()]
    assert remaining == ["cfg.json"], f"残留临时文件: {remaining}"


def test_save_env_preserves_comments_and_order(tmp_path: Path):
    """save_env 保留注释行与 key 原顺序；新增 key 追加到末尾"""
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# 主配置\n"
        "FOO=old\n"
        "\n"
        "# 备注\n"
        "BAR=keep\n",
        encoding="utf-8",
    )

    save_env(str(env_path), {"FOO": "new", "NEW_KEY": "val"})

    content = env_path.read_text(encoding="utf-8")
    # 注释保留
    assert "# 主配置" in content
    assert "# 备注" in content
    # FOO 被更新
    assert "FOO=new" in content
    # BAR 保留原值
    assert "BAR=keep" in content
    # NEW_KEY 追加
    assert "NEW_KEY=val" in content
    # FOO 在 BAR 之前（保持顺序）
    assert content.index("FOO=") < content.index("BAR=")


def test_save_load_config_roundtrip_utf8(tmp_path: Path):
    """save_config + load_config 往返保真（含中文）"""
    cfg_path = tmp_path / "config.json"
    original = {
        "novel_config": {"title": "仙侠小说", "target_chapters": 100},
        "model_config": {"outline": "claude", "content": "gemini"},
    }
    save_config(str(cfg_path), original)

    loaded = load_config(str(cfg_path))
    assert loaded == original
    # 文件包含非 ASCII 中文（未被转义为 \uXXXX）
    assert "仙侠小说" in cfg_path.read_text(encoding="utf-8")


def test_load_env_strips_quotes():
    """load_env 去除成对引号包裹的值"""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False, encoding="utf-8") as f:
        f.write('KEY1="quoted"\n')
        f.write("KEY2='single'\n")
        f.write("KEY3=plain\n")
        tmp = f.name
    try:
        data = load_env(tmp)
        assert data == {"KEY1": "quoted", "KEY2": "single", "KEY3": "plain"}
    finally:
        os.unlink(tmp)


def test_load_env_missing_file_returns_empty(tmp_path: Path):
    """load_env 对不存在的文件返回空 dict"""
    assert load_env(str(tmp_path / "nope.env")) == {}


def test_load_config_missing_file_returns_empty(tmp_path: Path):
    """load_config 对不存在的文件返回空 dict"""
    assert load_config(str(tmp_path / "nope.json")) == {}
