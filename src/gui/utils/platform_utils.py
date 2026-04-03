"""跨平台工具函数"""
import sys
import os
import subprocess
import logging

logger = logging.getLogger(__name__)


def open_directory(path: str) -> bool:
    """在系统文件管理器中打开目录，成功返回 True"""
    if not os.path.isdir(path):
        return False
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]  # Windows-only API
        else:
            subprocess.Popen(["xdg-open", path])
    except OSError as e:
        logger.warning("无法打开目录 %s: %s", path, e)
        return False
    return True
