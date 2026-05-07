import os
import json
import logging
import sys # 引入 sys 模块以访问 stdout
from logging.handlers import RotatingFileHandler # 推荐使用 RotatingFileHandler 以防日志文件过大
from typing import Dict, List, Optional, Any
from opencc import OpenCC

def setup_logging(log_dir: str, clear_logs: bool = False):
    """设置日志系统"""
    root_logger = logging.getLogger()
    
    # 清理所有现有的处理器，避免重复
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        handler.close()

    # 清理旧的日志文件
    log_file = os.path.join(log_dir, "generation.log")
    if clear_logs and os.path.exists(log_file):
        try:
            os.remove(log_file)
        except Exception as e:
            print(f"清理日志文件失败: {e}")

    # 配置根日志记录器
    root_logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    # 添加文件处理器
    file_handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8')
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # 添加控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    logging.info("日志系统初始化完成，将输出到文件和终端。")

def load_json_file(file_path: str, default_value: Any = None) -> Any:
    """加载JSON文件"""
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logging.error(f"加载JSON文件 {file_path} 时出错: {str(e)}")
    return default_value

def save_json_file(file_path: str, data: Any) -> bool:
    """保存数据到JSON文件"""
    try:
        # 确保目录存在
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logging.info(f"成功保存JSON文件: {file_path}") # 添加成功保存日志
        return True
    except Exception as e:
        logging.error(f"保存JSON文件 {file_path} 时出错: {str(e)}", exc_info=True) # 增加 exc_info 以打印完整堆栈信息
        return False

def clean_text(text: str) -> str:
    """清理文本内容"""
    # 创建繁简转换器
    t2s = OpenCC('t2s')
    # 转换为简体
    return t2s.convert(text.strip())

def validate_directory(directory: str) -> bool:
    """验证目录是否存在，不存在则创建"""
    try:
        os.makedirs(directory, exist_ok=True)
        return True
    except Exception as e:
        logging.error(f"创建目录 {directory} 时出错: {str(e)}")
        return False


def load_outline_chapter_data(output_dir: str, chapter_num: int) -> Optional[Dict[str, Any]]:
    """[5.2] 按 chapter_number 字段查找单章大纲数据,适用于稀疏大纲

    替代旧的 chapters_list[chapter_num - 1] 位置访问方式。当大纲含 None
    占位(b8267c7 引入的稀疏列表语义)或顺序乱序时,位置访问会拿到错误章节
    甚至越界。本 helper 通过 chapter_number 字段精确匹配,确保读取正确性。

    Args:
        output_dir: 输出目录,outline.json 所在路径
        chapter_num: 章节编号(1-based)

    Returns:
        匹配的章节 dict;找不到或文件异常时返回 None
    """
    outline_file = os.path.join(output_dir, "outline.json")
    if not os.path.exists(outline_file):
        logging.error(f"无法找到大纲文件: {outline_file}")
        return None
    data = load_json_file(outline_file, default_value=None)
    if data is None:
        return None
    # 兼容 dict {chapters: [...]} 与 list [...] 两种顶层格式
    chapters = data.get("chapters") if isinstance(data, dict) else data
    if not isinstance(chapters, list):
        logging.error(f"无法识别的大纲文件格式: {outline_file}")
        return None
    for entry in chapters:
        if isinstance(entry, dict) and entry.get("chapter_number") == chapter_num:
            return entry
    logging.error(
        f"在大纲中未找到第 {chapter_num} 章 (按 chapter_number 字段精确匹配,大纲共 {len(chapters)} 个条目)"
    )
    return None