"""OCNovel GUI 入口"""
import sys
import os

# macOS 系统级日志（IMK 输入法、TSM 键盘）通过 NSLog 输出到 stderr，
# Python 层无法拦截，在 fd 级别临时屏蔽
_suppress_stderr = sys.platform == 'darwin' and not os.environ.get('OCNOVEL_DEBUG')
if _suppress_stderr:
    _devnull = os.open(os.devnull, os.O_WRONLY)
    _orig_fd2 = os.dup(2)
    os.dup2(_devnull, 2)
    os.close(_devnull)

# 确保项目根目录在 sys.path 中
_root = os.path.dirname(os.path.abspath(__file__))
if _root not in sys.path:
    sys.path.insert(0, _root)

from src.gui.app import create_app
from src.gui.main_window import MainWindow
from src.gui.utils.resource_path import ensure_user_config


def main():
    ensure_user_config()
    app = create_app()
    window = MainWindow()
    window.show()

    # 窗口显示后恢复 stderr（让 Python 异常能正常输出）
    if _suppress_stderr:
        os.dup2(_orig_fd2, 2)
        os.close(_orig_fd2)

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
