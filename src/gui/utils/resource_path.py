"""PyInstaller 资源路径兼容工具"""
import logging
import os
import shutil
import sys


logger = logging.getLogger(__name__)


def resource_path(relative_path: str) -> str:
    """获取资源文件的绝对路径，兼容 PyInstaller 打包环境"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), relative_path)


def get_user_data_dir() -> str:
    """获取用户应用目录：~/OCNovel/

    Raises:
        OSError: 目录创建失败（权限不足、磁盘满、杀软拦截等）。
                 调用方应当捕获并给用户可读的提示。
    """
    base = os.path.expanduser('~/OCNovel')
    try:
        os.makedirs(base, exist_ok=True)
    except OSError as e:
        logger.error("无法创建用户目录 %s: %s", base, e)
        raise
    return base


def get_project_root() -> str:
    """获取项目根目录（开发环境返回代码目录，打包环境返回用户目录）"""
    if hasattr(sys, '_MEIPASS'):
        return get_user_data_dir()
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))


def ensure_user_config():
    """首次启动时，在用户主目录下创建 ~/OCNovel 及子目录，从模板初始化配置文件。

    所有 I/O 失败都被捕获并以 warning 形式记日志，不向上抛出，避免 GUI
    启动阶段因权限/磁盘/杀软等原因直接崩溃。

    Returns:
        str | None: 成功返回用户目录路径；失败返回 None。
    """
    try:
        user_dir = get_user_data_dir()
    except OSError:
        # get_user_data_dir 已打 error 日志
        return None

    # 确定模板来源：打包环境从 bundle 读取，开发环境从项目根目录读取
    if hasattr(sys, '_MEIPASS'):
        template_dir = sys._MEIPASS
    else:
        template_dir = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))

    # 从模板创建配置文件（仅在目标不存在时）
    for template, target in [
        ("config.json.example", "config.json"),
        (".env.example", ".env"),
    ]:
        src = os.path.join(template_dir, template)
        dst = os.path.join(user_dir, target)
        if not os.path.exists(dst) and os.path.exists(src):
            try:
                shutil.copy2(src, dst)
                logger.info("首次启动：已从模板创建 %s", dst)
            except OSError as e:
                logger.warning("复制模板 %s 到 %s 失败: %s", template, dst, e)

    # 创建必要的 data 子目录
    for d in ["data/cache", "data/output", "data/logs", "data/reference", "data/style_sources"]:
        target_dir = os.path.join(user_dir, d)
        try:
            os.makedirs(target_dir, exist_ok=True)
        except OSError as e:
            logger.warning("创建目录 %s 失败: %s", target_dir, e)

    return user_dir
