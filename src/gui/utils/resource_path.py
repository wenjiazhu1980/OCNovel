"""PyInstaller 资源路径兼容工具"""
import os
import sys
import shutil
import logging


def resource_path(relative_path: str) -> str:
    """获取资源文件的绝对路径，兼容 PyInstaller 打包环境"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), relative_path)


def get_user_data_dir() -> str:
    """获取用户应用目录：~/OCNovel/"""
    base = os.path.expanduser('~/OCNovel')
    os.makedirs(base, exist_ok=True)
    return base


def get_project_root() -> str:
    """获取项目根目录（开发环境返回代码目录，打包环境返回用户目录）"""
    if hasattr(sys, '_MEIPASS'):
        return get_user_data_dir()
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))


def ensure_user_config():
    """首次启动时，在用户主目录下创建 ~/OCNovel 及子目录，从模板初始化配置文件"""
    user_dir = get_user_data_dir()

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
            shutil.copy2(src, dst)
            logging.info(f"首次启动：已从模板创建 {dst}")

    # 创建必要的 data 子目录
    for d in ["data/cache", "data/output", "data/logs", "data/reference", "data/style_sources"]:
        os.makedirs(os.path.join(user_dir, d), exist_ok=True)

    return user_dir
