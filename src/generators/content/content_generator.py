import os
import logging
import time
from typing import Optional, List, Any, Dict
import math


class ChapterLengthError(Exception):
    """章节字数偏差过大时抛出的异常"""
    def __init__(self, message: str, actual: int, target: int, content: str = ""):
        super().__init__(message)
        self.actual = actual
        self.target = target
        self.content = content  # 保留已生成的内容，用于缩写/扩写
from .consistency_checker import ConsistencyChecker
from .validators import LogicValidator, DuplicateValidator
from ..common.data_structures import ChapterOutline
from ..common.utils import load_json_file, save_json_file, validate_directory
import re
from logging.handlers import RotatingFileHandler
import sys
import json
from ..prompts import (
    get_chapter_prompt,
    get_sync_info_prompt,
    get_knowledge_search_prompt
)
import numpy as np
import functools

# Get a logger specific to this module
logger = logging.getLogger(__name__)

class ContentGenerator:
    def __init__(self, config, content_model, knowledge_base, finalizer: Optional[Any] = None):
        self.config = config
        self.content_model = content_model
        self.knowledge_base = knowledge_base
        self.output_dir = config.output_config["output_dir"]
        self.chapter_outlines = []
        self.current_chapter = 0
        self.finalizer = finalizer
        self.cancel_checker = None  # 可选：外部注入的取消检查回调，返回 True 表示应取消
        
        # 新增：缓存计数器和同步信息生成器
        self.chapters_since_last_cache = 0
        self.content_kb_dir = os.path.join(self.output_dir, "content_kb")
        self.sync_info_file = os.path.join(self.output_dir, "sync_info.json")
        
        # 验证并创建缓存目录
        os.makedirs(self.content_kb_dir, exist_ok=True)
        
        # 初始化重生成相关的属性
        self.target_chapter = None
        self.external_prompt = None
        
        # 初始化验证器和检查器
        self.consistency_checker = ConsistencyChecker(content_model, self.output_dir)
        self.logic_validator = LogicValidator(content_model)
        self.duplicate_validator = DuplicateValidator(content_model)
        
        # 验证并创建输出目录
        validate_directory(self.output_dir)
        # 加载现有大纲和进度
        self._load_progress()
        
        # 初始化知识库
        self._init_knowledge_base()

        self.imitation_config = getattr(config, 'imitation_config', {})
        self.default_style = '古风雅致'  # 默认风格

    def _load_outline(self):
        """加载大纲文件，构建位置对齐的稀疏列表

        约定（与 outline_generator 一致）:
        - ``self.chapter_outlines[i]`` 对应 chapter_number = i+1；
        - 缺失槽位填 None，保证 ``[chapter_num - 1]`` 索引访问语义稳定；
        - 重复 chapter_number 仅保留**首次出现**版本；
        - len(self.chapter_outlines) == max(chapter_number)，与 target_chapters 比较时语义一致；
        - 若存在缺失槽位，``self._outline_discontinuous`` 记录缺失编号列表。
        """
        outline_file = os.path.join(self.output_dir, "outline.json")
        outline_data = load_json_file(outline_file, default_value=[])

        if not outline_data:
            logger.info("未找到大纲文件或文件为空。")
            self.chapter_outlines = []
            self._outline_discontinuous = []
            return

        chapters_list = outline_data.get("chapters", outline_data) if isinstance(outline_data, dict) else outline_data
        if not isinstance(chapters_list, list):
            logger.error("大纲文件格式无法识别，应为列表或包含 'chapters' 键的字典。")
            self.chapter_outlines = []
            self._outline_discontinuous = []
            return

        try:
            # 阶段1：解析并按 chapter_number 去重（保留首次）
            seen_nums: set = set()
            loaded_outlines: list = []
            duplicate_skipped = 0
            non_dict_skipped = 0

            for idx, chapter_data in enumerate(chapters_list):
                if not isinstance(chapter_data, dict):
                    non_dict_skipped += 1
                    continue
                try:
                    outline = ChapterOutline(**chapter_data)
                except TypeError as e:
                    logger.warning(f"加载大纲时第 {idx+1} 个条目字段不匹配: {e} - 数据: {chapter_data} - 已跳过")
                    continue
                if outline.chapter_number in seen_nums:
                    duplicate_skipped += 1
                    logger.warning(
                        f"加载大纲时检测到重复 chapter_number={outline.chapter_number} (file index={idx})，"
                        f"已跳过（保留首次出现版本）"
                    )
                    continue
                seen_nums.add(outline.chapter_number)
                loaded_outlines.append(outline)

            if non_dict_skipped:
                logger.warning(f"大纲文件中包含 {non_dict_skipped} 个非字典元素，已跳过。")

            # 阶段2：构建位置对齐的稀疏列表
            if not loaded_outlines:
                self.chapter_outlines = []
                self._outline_discontinuous = []
                logger.info("从文件加载了 0 章大纲")
                return

            max_num = max(o.chapter_number for o in loaded_outlines)
            positioned = [None] * max_num
            for o in loaded_outlines:
                if 1 <= o.chapter_number <= max_num:
                    positioned[o.chapter_number - 1] = o
            self.chapter_outlines = positioned

            # 阶段3：检测缺失槽位（不连续性）
            missing = [
                idx + 1 for idx, slot in enumerate(self.chapter_outlines) if slot is None
            ]
            self._outline_discontinuous = missing

            valid_count = max_num - len(missing)
            if duplicate_skipped:
                logger.warning(
                    f"大纲去重：原始 {len(loaded_outlines) + duplicate_skipped} 条 → 去重后 {len(loaded_outlines)} 条"
                )
            if missing:
                logger.error(
                    f"大纲章节号不连续！缺失: {missing}。"
                    f"请重新生成大纲或手动修复 outline.json。"
                )
            logger.info(f"从文件加载了 {valid_count} 章大纲（位置对齐到 max_chapter_number={max_num}）")

        except Exception as e:
            logger.error(f"加载大纲时发生未知错误: {e}", exc_info=True)
            self.chapter_outlines = []
            self._outline_discontinuous = []

    def _load_progress(self):
        """加载生成进度：综合 summary.json 与磁盘上已存在的章节正文文件。

        过去仅看 summary.json 的最大键，但当 finalize 失败时，正文已落盘却未进入
        summary.json，导致重启后误判这些章节"未生成"并从头覆盖生成。
        现在改为：
          - 同时扫描 output_dir 下 `第NNN章_*.txt`（排除 `_imitated`、`_摘要` 后缀）；
          - 取 summary.json 键集合与磁盘章节集合的并集；
          - 进度=并集中的最大章节号；
          - 同时记录"正文已存在但缺 summary.json 条目"的章节，
            供 _generate_remaining_chapters 在循环时单独补 finalize。
        """
        # ── 1. 读取 summary.json ──
        summary_keys: set = set()
        summary_file = os.path.join(self.output_dir, "summary.json")
        try:
            if os.path.exists(summary_file):
                with open(summary_file, 'r', encoding='utf-8') as f:
                    summary_data = json.load(f)
                    if isinstance(summary_data, dict):
                        summary_keys = {
                            int(k) for k in summary_data.keys() if str(k).isdigit()
                        }
        except Exception as e:
            logger.error(f"读取 summary.json 失败: {e}")
            summary_keys = set()

        # ── 2. 扫描磁盘正文文件 ──
        disk_keys: set = set()
        try:
            if os.path.isdir(self.output_dir):
                # 匹配形如 "第123章_xxx.txt" 的正文，排除 "_imitated" / "_摘要"
                content_pattern = re.compile(r'^第(\d+)章_')
                for name in os.listdir(self.output_dir):
                    if not name.endswith('.txt'):
                        continue
                    if '_摘要' in name or '_imitated' in name:
                        continue
                    m = content_pattern.match(name)
                    if m:
                        disk_keys.add(int(m.group(1)))
        except Exception as e:
            logger.error(f"扫描磁盘章节文件失败: {e}")
            disk_keys = set()

        summary_max = max(summary_keys) if summary_keys else 0
        disk_max = max(disk_keys) if disk_keys else 0

        # ── 3. 进度指针 = 最长连续前缀 N（1..N 都已存在于并集中）──
        # 这样后续循环会从第一个"洞"开始扫，逐章决定生成 / 补 finalize / 跳过。
        union_keys = summary_keys | disk_keys
        consecutive_prefix = 0
        while (consecutive_prefix + 1) in union_keys:
            consecutive_prefix += 1
        self.current_chapter = consecutive_prefix

        # ── 4. 记录差异，供 _generate_remaining_chapters 补 finalize ──
        self._chapters_in_summary = summary_keys
        self._chapters_on_disk = disk_keys
        self._chapters_pending_finalize = sorted(disk_keys - summary_keys)
        self._chapters_missing_content = sorted(
            n for n in range(1, max(summary_max, disk_max) + 1)
            if n not in disk_keys
        )

        if self._chapters_pending_finalize:
            preview = self._chapters_pending_finalize[:20]
            ellipsis = ' ...' if len(self._chapters_pending_finalize) > 20 else ''
            logger.warning(
                f"发现 {len(self._chapters_pending_finalize)} 个章节正文已存在但缺 summary.json 条目: "
                f"{preview}{ellipsis}（生成循环将自动补 finalize）"
            )
        if self._chapters_missing_content:
            preview = self._chapters_missing_content[:20]
            ellipsis = ' ...' if len(self._chapters_missing_content) > 20 else ''
            logger.warning(
                f"检测到 {len(self._chapters_missing_content)} 个"
                f"章节号洞（无正文）: {preview}{ellipsis}（将在生成循环到达时重新生成）"
            )

        logger.info(
            f"Loaded progress: summary_max={summary_max}, disk_max={disk_max}, "
            f"consecutive_prefix={consecutive_prefix}, current_chapter={self.current_chapter}"
        )

    def _save_progress(self):
        """保存生成进度到 summary.json"""
        # 不再需要单独保存 progress.json
        # 因为进度信息已经包含在 summary.json 中的最大章节号中
        logger.info(f"进度已更新，下一个待处理章节索引: {self.current_chapter}")

    def get_style_prompt(self, style_name: Optional[str] = None) -> str:
        """
        根据风格名获取extra_prompt，若未指定则用默认风格。
        """
        imitation = self.imitation_config.get('auto_imitation', {})
        style_sources = imitation.get('style_sources', [])
        # 优先用参数，否则用imitation_config.default_style，否则用self.default_style
        style = style_name or imitation.get('default_style') or self.default_style
        for s in style_sources:
            if s.get('name') == style:
                return s.get('extra_prompt', '')
        # 未找到则返回空
        return ''

    def get_style_reference(self, style_name: Optional[str] = None, max_length: int = 3000) -> (str, str):
        """
        获取风格extra_prompt和file_path指定的风格示例文本内容。
        Args:
            style_name: 风格名
            max_length: 示例文本最大长度（字符）
        Returns:
            (extra_prompt, style_example_text)
        """
        imitation = self.imitation_config.get('auto_imitation', {})
        style_sources = imitation.get('style_sources', [])
        style = style_name or imitation.get('default_style') or self.default_style
        for s in style_sources:
            if s.get('name') == style:
                extra_prompt = s.get('extra_prompt', '')
                file_path = s.get('file_path')
                style_example = ''
                if file_path:
                    abs_path = file_path if os.path.isabs(file_path) else os.path.join(self.config.base_dir, file_path)
                    try:
                        with open(abs_path, 'r', encoding='utf-8') as f:
                            style_example = f.read()
                            if max_length > 0 and len(style_example) > max_length:
                                style_example = style_example[:max_length] + '\n...（示例已截断）'
                    except Exception as e:
                        logger.warning(f"读取风格示例文本失败: {abs_path} - {e}")
                        style_example = ''
                return extra_prompt, style_example
        return '', ''

    def generate_content(
        self,
        target_chapter: Optional[int] = None,
        external_prompt: Optional[str] = None,
        style_name: Optional[str] = None,
        is_target_chapter: bool = False,
    ) -> bool:
        """生成章节内容，支持传入风格名

        Args:
            target_chapter: 指定要生成的单一章节号；None 时走"续写剩余章节"路径。
            external_prompt: 额外提示词。
            style_name: 仿写风格名。
            is_target_chapter: 是否为"重新生成既有章节"语义；
                - False (默认): 首次生成,会更新 summary.json 与 第NNN章_摘要.txt;
                - True: 重生成已 finalize 的章节,跳过摘要更新以保留既有上下文。
                调用方需显式区分,避免连续生成被误判为重生成而漏写摘要。
        """
        self._load_outline()
        if not self.chapter_outlines:
            logger.error("无法生成内容：大纲未加载或为空。请先生成大纲。")
            return False
        if getattr(self, '_outline_discontinuous', []):
            missing = self._outline_discontinuous
            logger.error(
                f"大纲章节号不连续，缺失: {missing}。"
                f"无法在不完整的大纲上生成内容，请先使用「强制重生成大纲」修复。"
            )
            return False
        try:
            if target_chapter is not None:
                if 1 <= target_chapter <= len(self.chapter_outlines):
                    return self._process_single_chapter(
                        target_chapter,
                        external_prompt,
                        style_name=style_name,
                        is_target_chapter=is_target_chapter,
                    )
                else:
                    logger.error(f"目标章节 {target_chapter} 超出大纲范围 (1-{len(self.chapter_outlines)})。")
                    return False
            else:
                return self._generate_remaining_chapters(style_name=style_name)
        except Exception as e:
            logger.error(f"生成章节内容时发生未预期错误: {str(e)}", exc_info=True)
            return False

    def _check_cancelled(self):
        """检查是否收到取消请求"""
        if self.cancel_checker and self.cancel_checker():
            raise InterruptedError("用户取消生成")

    def _get_chapter_retry_settings(self, max_retries: Optional[int] = None) -> tuple[int, float]:
        """获取单章生成的重试配置，支持显式覆盖默认值"""
        generation_config = getattr(self.config, "generation_config", {}) or {}
        raw_max_retries = generation_config.get("max_retries", 3) if max_retries is None else max_retries
        raw_retry_delay = generation_config.get("retry_delay", 10)

        try:
            effective_max_retries = max(1, int(raw_max_retries))
        except (TypeError, ValueError):
            logger.warning(f"无效的章节重试次数配置: {raw_max_retries}，将回退到默认值 3。")
            effective_max_retries = 3

        try:
            effective_retry_delay = max(0.0, float(raw_retry_delay))
        except (TypeError, ValueError):
            logger.warning(f"无效的章节重试间隔配置: {raw_retry_delay}，将回退到默认值 10 秒。")
            effective_retry_delay = 10.0

        return effective_max_retries, effective_retry_delay

    def _process_single_chapter(self, chapter_num: int, external_prompt: Optional[str] = None, max_retries: Optional[int] = None, style_name: Optional[str] = None, is_target_chapter: bool = False) -> bool:
        """
        处理单个章节的生成、验证、保存和定稿，支持风格名
        Args:
            is_target_chapter: 是否为指定重新生成的章节，如果是则不更新sync_info
        """
        if not (1 <= chapter_num <= len(self.chapter_outlines)):
            logger.error(f"无效的章节号: {chapter_num}")
            return False
        chapter_outline = self.chapter_outlines[chapter_num - 1]
        if chapter_outline.chapter_number != chapter_num:
            logger.error(
                f"大纲编号不匹配：请求生成第 {chapter_num} 章，"
                f"但索引位置的大纲编号为 {chapter_outline.chapter_number}（{chapter_outline.title}）。"
                f"请检查 outline.json 是否存在缺失或错乱的章节号。"
            )
            return False
        logger.info(f"[Chapter {chapter_num}] 开始处理章节: {chapter_outline.title}")
        max_retries, retry_delay = self._get_chapter_retry_settings(max_retries)
        success = False
        length_hint = ""  # 字数约束提示，重试时追加到 prompt
        pending_adjustment = None  # 待调整的内容 (content, actual, target)
        for attempt in range(max_retries):
            logger.info(f"[Chapter {chapter_num}] 尝试 {attempt + 1}/{max_retries}")
            try:
                self._check_cancelled()

                if pending_adjustment:
                    # 基于上次生成的内容做字数调整，而非重新生成
                    prev_content, prev_actual, prev_target = pending_adjustment
                    pending_adjustment = None
                    logger.info(
                        f"[Chapter {chapter_num}] 基于已有内容进行字数调整 "
                        f"({prev_actual} → {prev_target})"
                    )
                    raw_content = self._adjust_chapter_length(
                        prev_content, prev_actual, prev_target, chapter_outline
                    )
                    if not raw_content:
                        raise Exception("字数调整失败，返回为空，将重新生成。")
                else:
                    # 正常生成：拼接风格示例和风格要求
                    extra_prompt, style_example = self.get_style_reference(style_name)
                    style_block = ''
                    if style_example:
                        style_block += f"【风格示例】\n{style_example}\n"
                    if extra_prompt:
                        style_block += f"【风格要求】{extra_prompt}\n"
                    merged_prompt = style_block + (external_prompt or '') + length_hint
                    raw_content = self._generate_chapter_content(chapter_outline, merged_prompt)
                    if not raw_content:
                        raise Exception("原始内容生成失败，返回为空。")

                # 1.5. 字数检测
                target_length = self.config.generator_config.get("chapter_length", 0)
                if target_length > 0:
                    actual_length = len(raw_content)
                    deviation = abs(actual_length - target_length) / target_length

                    if deviation > 0.5:
                        direction = "偏少" if actual_length < target_length else "偏多"
                        logger.warning(
                            f"[Chapter {chapter_num}] 字数严重{direction}: "
                            f"实际 {actual_length} / 目标 {target_length}（偏差 {deviation:.0%}），触发字数调整"
                        )
                        raise ChapterLengthError(
                            f"字数{direction}（{actual_length}/{target_length}，偏差 {deviation:.0%}）",
                            actual=actual_length, target=target_length, content=raw_content
                        )
                    elif deviation > 0.2:
                        direction = "偏少" if actual_length < target_length else "偏多"
                        logger.warning(
                            f"[Chapter {chapter_num}] 字数{direction}: "
                            f"实际 {actual_length} / 目标 {target_length}（偏差 {deviation:.0%}）"
                        )
                    else:
                        logger.info(
                            f"[Chapter {chapter_num}] 字数检测通过: "
                            f"实际 {actual_length} / 目标 {target_length}（偏差 {deviation:.0%}）"
                        )

                self._check_cancelled()
                # 2. 加载同步信息
                sync_info = self._load_sync_info()
                
                # 3. 逻辑验证
                logic_report, needs_logic_revision = self.logic_validator.check_logic(
                    raw_content, 
                    chapter_outline.__dict__,
                    sync_info
                )
                logger.info(
                    f"[Chapter {chapter_num}] 逻辑验证报告 (摘要): {logic_report[:200]}..."
                    f"\n需要修改: {'是' if needs_logic_revision else '否'}"
                )

                self._check_cancelled()
                # 4. 一致性验证
                logger.info(f"[Chapter {chapter_num}] 开始一致性检查...")
                final_content = self.consistency_checker.ensure_chapter_consistency(
                    chapter_content=raw_content,
                    chapter_outline=chapter_outline.__dict__,
                    sync_info=sync_info,
                    chapter_idx=chapter_num - 1
                )
                logger.info(f"[Chapter {chapter_num}] 一致性检查完成")

                self._check_cancelled()
                # 5. 重复文字验证
                duplicate_report, needs_duplicate_revision = self.duplicate_validator.check_duplicates(
                    final_content,
                    self._load_adjacent_chapter(chapter_num - 1),
                    self._load_adjacent_chapter(chapter_num + 1) if chapter_num < len(self.chapter_outlines) else ""
                )
                logger.info(
                    f"[Chapter {chapter_num}] 重复文字验证报告 (摘要): {duplicate_report[:200]}..."
                    f"\n需要修改: {'是' if needs_duplicate_revision else '否'}"
                )

                # 6. 保存最终内容
                if self._save_chapter_content(chapter_num, final_content):
                    logger.info(f"[Chapter {chapter_num}] 内容保存成功")

                    # 7. 调用 Finalizer (如果提供了)
                    if self.finalizer:
                        logger.info(f"[Chapter {chapter_num}] 开始调用 Finalizer 进行定稿...")
                        # 重新生成单章（is_target_chapter=True）时跳过 summary 更新，
                        # 避免覆盖既有上下文摘要导致与 sync_info 不一致。
                        finalize_success = self.finalizer.finalize_chapter(
                            chapter_num=chapter_num,
                            update_summary=not is_target_chapter,
                        )
                        if finalize_success:
                            logger.info(f"[Chapter {chapter_num}] 定稿成功")
                            self.current_chapter = chapter_num
                            # 仅在实际写入了 summary.json 时,才把章节加入"已 finalize 集合",
                            # 否则会与磁盘 summary.json 脱节(下次重启 _load_progress 又会
                            # 把该章列入 _chapters_pending_finalize)。
                            if not is_target_chapter and hasattr(self, '_chapters_in_summary'):
                                self._chapters_in_summary.add(chapter_num)
                            if hasattr(self, '_chapters_on_disk'):
                                self._chapters_on_disk.add(chapter_num)
                        else:
                            # 定稿失败时不能将 success 置 True，否则上层会把进度推到下一章，
                            # 导致 summary.json 与磁盘脱节。抛异常以触发 except 分支的重试。
                            raise Exception(f"第 {chapter_num} 章 finalize 失败")
                    else:
                        logger.warning(f"[Chapter {chapter_num}] Finalizer 未提供，跳过定稿步骤。")
                        self.current_chapter = chapter_num
                        if hasattr(self, '_chapters_on_disk'):
                            self._chapters_on_disk.add(chapter_num)

                    # content模式不触发同步信息更新，只有auto模式和finalize模式才更新；
                    # 此外 target_chapter（重生成单章）模式额外不刷新 summary。
                    logger.info(f"[Chapter {chapter_num}] content模式不触发同步信息更新，仅保存章节内容")
                    success = True
                    break
                else:
                    raise Exception("保存最终内容失败")
            except ChapterLengthError as e:
                # 字数偏差已在上面记录，不重复打 traceback
                # 保存内容用于下次迭代做缩写/扩写调整
                if e.content:
                    pending_adjustment = (e.content, e.actual, e.target)
                success = False
                if attempt >= max_retries - 1:
                    logger.error(f"[Chapter {chapter_num}] 字数调整 {max_retries} 次仍不达标，放弃")
                    return False
            except Exception as e:
                logger.error(f"[Chapter {chapter_num}] 处理出错: {str(e)}", exc_info=True)
                success = False
                if attempt >= max_retries - 1:
                    logger.error(f"[Chapter {chapter_num}] 达到最大重试次数")
                    return False
                time.sleep(retry_delay)
        return success

    def _load_adjacent_chapter(self, chapter_num: int) -> str:
        """加载相邻章节内容（用于重复验证）"""
        try:
            if 1 <= chapter_num <= len(self.chapter_outlines):
                filename = f"第{chapter_num}章_{self._clean_filename(self.chapter_outlines[chapter_num-1].title)}.txt"
                filepath = os.path.join(self.output_dir, filename)
                if os.path.exists(filepath):
                    with open(filepath, 'r', encoding='utf-8') as f:
                        return f.read()
        except Exception as e:
            logger.warning(f"加载第 {chapter_num} 章内容失败: {str(e)}")
        return ""

    def _chapter_content_exists(self, chapter_num: int) -> Optional[str]:
        """检测第 chapter_num 章的正文文件是否存在，返回路径或 None。

        优先按当前 outline 的标题构造预期路径；找不到时回退到模糊扫描，
        匹配 `第{chapter_num}章_*.txt`（排除 `_imitated` / `_摘要` 后缀），
        以容忍历史改名。
        """
        if not (1 <= chapter_num <= len(self.chapter_outlines)):
            return None
        try:
            cleaned_title = self._clean_filename(self.chapter_outlines[chapter_num - 1].title)
            expected = os.path.join(self.output_dir, f"第{chapter_num}章_{cleaned_title}.txt")
            if os.path.exists(expected):
                return expected
        except Exception:
            pass
        # 后备：扫描目录
        try:
            prefix = f"第{chapter_num}章_"
            for name in os.listdir(self.output_dir):
                if not name.endswith('.txt'):
                    continue
                if '_摘要' in name or '_imitated' in name:
                    continue
                if name.startswith(prefix):
                    return os.path.join(self.output_dir, name)
        except Exception:
            pass
        return None

    def _chapter_imitated_exists(self, chapter_num: int) -> Optional[str]:
        """检测第 chapter_num 章的仿写文件是否存在，返回路径或 None。

        命名规则：`第{n}章_{title}_imitated.txt`。先按当前 outline 标题构造，
        缺则模糊扫描目录（容忍历史改名）。
        """
        if not (1 <= chapter_num <= len(self.chapter_outlines)):
            return None
        try:
            cleaned_title = self._clean_filename(self.chapter_outlines[chapter_num - 1].title)
            expected = os.path.join(
                self.output_dir, f"第{chapter_num}章_{cleaned_title}_imitated.txt"
            )
            if os.path.exists(expected):
                return expected
        except Exception:
            pass
        # 后备：扫描目录，匹配 `第{n}章_*_imitated.txt`
        try:
            prefix = f"第{chapter_num}章_"
            for name in os.listdir(self.output_dir):
                if not name.endswith("_imitated.txt"):
                    continue
                if name.startswith(prefix):
                    return os.path.join(self.output_dir, name)
        except Exception:
            pass
        return None

    def _generate_remaining_chapters(self, style_name: Optional[str] = None) -> bool:
        """
        生成所有剩余章节，支持风格名。

        循环时对每个 current_chapter_num 单独判断：
          1. 若磁盘已有正文且 summary.json 已含该章 → 跳过、推进进度
          2. 若磁盘已有正文但缺 summary.json 条目 → 调 finalizer 补摘要
          3. 若磁盘无正文 → 正常调 _process_single_chapter
        """
        logger.info(
            f"开始生成剩余章节，从第 {self.current_chapter + 1} 章开始（"
            f"对已存在但缺摘要的章节会自动补 finalize）..."
        )
        initial_start_chapter_index = self.current_chapter
        while self.current_chapter < len(self.chapter_outlines):
            current_chapter_num = self.current_chapter + 1

            # 已存在于磁盘上的章节：跳过或补 finalize
            existing_path = self._chapter_content_exists(current_chapter_num)
            if existing_path:
                in_summary = current_chapter_num in getattr(self, '_chapters_in_summary', set())
                if in_summary:
                    logger.info(
                        f"第 {current_chapter_num} 章正文与摘要均已存在，跳过生成。"
                    )
                    self.current_chapter = current_chapter_num
                    self._save_progress()
                    continue
                if self.finalizer:
                    logger.warning(
                        f"第 {current_chapter_num} 章正文已存在但缺 summary.json 条目，补跑 finalize..."
                    )
                    finalize_ok = False
                    try:
                        finalize_ok = self.finalizer.finalize_chapter(
                            chapter_num=current_chapter_num,
                            update_summary=True,
                        )
                    except Exception as fe:
                        logger.error(
                            f"第 {current_chapter_num} 章补 finalize 异常: {fe}",
                            exc_info=True,
                        )
                    if finalize_ok:
                        if hasattr(self, '_chapters_in_summary'):
                            self._chapters_in_summary.add(current_chapter_num)
                        self.current_chapter = current_chapter_num
                        self._save_progress()
                        continue
                    logger.error(
                        f"第 {current_chapter_num} 章补 finalize 失败，中止剩余章节生成。"
                    )
                    return False
                # 无 finalizer 但正文已存在：仅推进进度
                logger.warning(
                    f"第 {current_chapter_num} 章正文已存在但 finalizer 未提供，仅推进进度。"
                )
                self.current_chapter = current_chapter_num
                self._save_progress()
                continue

            # 无正文：正常生成
            success = self._process_single_chapter(current_chapter_num, style_name=style_name, is_target_chapter=False)
            if not success:
                logger.error(f"处理第 {current_chapter_num} 章失败，中止剩余章节生成。")
                return False
            self._save_progress()
        if self.current_chapter > initial_start_chapter_index:
            logger.info("所有剩余章节处理完成。")
            return True
        elif self.current_chapter == len(self.chapter_outlines):
            logger.info("所有章节均已处理完成。")
            return True
        else:
            logger.info(f"没有需要生成的剩余章节（当前进度索引: {self.current_chapter}）。")
            return True

    def merge_all_chapters(self, output_filename: Optional[str] = None) -> Optional[str]:
        """
        将所有已生成的章节合并为一个完整的 txt 文件。

        Args:
            output_filename: 原版输出文件名（不含路径），默认使用小说标题。
                             仿写版文件名固定为 `{novel_title}_仿写版.txt`，
                             不受该参数影响。

        Returns:
            合并后的原版文件路径，失败返回 None。
            仿写版路径仅在日志中体现。
        """
        try:
            self._load_outline()
            if not self.chapter_outlines:
                logger.warning("大纲为空，无法合并章节。")
                return None

            novel_title = getattr(self.config, 'novel_config', {}).get('title', '未命名小说')
            # 确定输出文件名
            if not output_filename:
                output_filename = f"{novel_title}_完整版.txt"
            imitated_filename = f"{novel_title}_仿写版.txt"

            original_parts: List[str] = []
            imitated_parts: List[str] = []
            original_count = 0
            imitated_real_count = 0  # 真正用了仿写文件（非 fallback）的章数
            imitated_fallback_count = 0  # 仿写版用了原文 fallback 的章数
            has_imitated = False

            # 大纲不连续时存在 None 槽位（位置对齐策略，参见 _load_outline）：
            # 若直接访问 outline.chapter_number 会触发 AttributeError；这里跳过空槽并记录，
            # 让合并在不完整大纲下仍可输出可用部分而非整体失败。
            missing_outline_slots: list[int] = []
            for slot_idx, outline in enumerate(self.chapter_outlines):
                if outline is None:
                    missing_outline_slots.append(slot_idx + 1)
                    continue
                chapter_num = outline.chapter_number
                cleaned_title = self._clean_filename(outline.title)
                # 原文查找复用 _chapter_content_exists（带模糊扫描兜底，
                # 容忍"大纲标题已改、磁盘文件名仍是旧标题"的历史情况）
                filepath = self._chapter_content_exists(chapter_num)

                # ── 原版片段 ──
                original_content = ""
                if filepath:
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            original_content = f.read().strip()
                    except Exception as e:
                        logger.warning(f"读取原文失败 {filepath}: {e}")
                        original_content = ""
                    if original_content:
                        original_parts.append(original_content)
                        original_count += 1
                else:
                    expected_filename = f"第{chapter_num}章_{cleaned_title}.txt"
                    logger.warning(f"章节文件不存在，跳过: {expected_filename}")

                # ── 仿写版片段（每章独立判断）──
                imitated_path = self._chapter_imitated_exists(chapter_num)
                if imitated_path:
                    has_imitated = True
                    imitated_content = ""
                    try:
                        with open(imitated_path, 'r', encoding='utf-8') as f:
                            imitated_content = f.read().strip()
                    except Exception as e:
                        logger.warning(f"读取仿写文件失败 {imitated_path}: {e}")
                        imitated_content = ""
                    if imitated_content:
                        imitated_parts.append(imitated_content)
                        imitated_real_count += 1
                    elif original_content:
                        imitated_parts.append(original_content)
                        imitated_fallback_count += 1
                elif original_content:
                    # 没仿写文件 → 用原文 fallback
                    imitated_parts.append(original_content)
                    imitated_fallback_count += 1
                # 原文与仿写都缺 → 跳过该章

            if missing_outline_slots:
                preview = missing_outline_slots[:20]
                ellipsis = ' ...' if len(missing_outline_slots) > 20 else ''
                logger.warning(
                    f"合并时检测到 {len(missing_outline_slots)} 个大纲缺失槽位"
                    f"（已跳过）: {preview}{ellipsis}。建议重新生成大纲修复 outline.json。"
                )

            if not original_parts:
                logger.error("未找到任何章节文件，无法合并。")
                return None

            # ── 写原版 ──
            merged_content = "\n\n".join(original_parts)
            output_path = os.path.join(self.output_dir, output_filename)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(merged_content)
            valid_outline_count = len(self.chapter_outlines) - len(missing_outline_slots)
            logger.info(
                f"已合并 {original_count}/{valid_outline_count} 章到 "
                f"{output_path}，总字数: {len(merged_content)}"
            )

            # ── 写仿写版（仅当存在任何仿写文件时）──
            if has_imitated and imitated_parts:
                try:
                    imitated_merged = "\n\n".join(imitated_parts)
                    imitated_output_path = os.path.join(self.output_dir, imitated_filename)
                    with open(imitated_output_path, 'w', encoding='utf-8') as f:
                        f.write(imitated_merged)
                    logger.info(
                        f"已合并仿写版 {imitated_real_count} 仿写 + "
                        f"{imitated_fallback_count} 原文 fallback / "
                        f"{valid_outline_count} 章到 "
                        f"{imitated_output_path}，总字数: {len(imitated_merged)}"
                    )
                except Exception as e:
                    # 仿写版失败不影响原版返回
                    logger.error(f"写入仿写版失败: {e}", exc_info=True)
            elif not has_imitated:
                logger.info("未检测到任何 _imitated.txt 文件，跳过仿写版输出。")

            return output_path

        except Exception as e:
            logger.error(f"合并章节时出错: {str(e)}", exc_info=True)
            return None

    def _generate_chapter_content(self, chapter_outline: ChapterOutline, extra_prompt: Optional[str] = None) -> Optional[str]:
        """生成单章的原始内容"""
        try:
            chapter_num = chapter_outline.chapter_number
            logger.info(f"开始为第 {chapter_num} 章生成原始内容...")
            context = self._get_context_for_chapter(chapter_num)
            references = self._get_references_for_chapter(chapter_outline)
            
            # 获取故事设定和同步信息
            story_config = self.config.novel_config if hasattr(self.config, 'novel_config') else None
            sync_info = self._load_sync_info()

            # 使用 prompts.py 中的方法
            humanization_config = self.config.generation_config.get("humanization", {}) if hasattr(self.config, 'generation_config') else {}
            chapter_length = self.config.generator_config.get("chapter_length", 0)
            prompt = get_chapter_prompt(
                outline=chapter_outline.__dict__,
                references=references,
                extra_prompt=extra_prompt or "",
                context_info=context,
                story_config=story_config,  # 新增：传递故事设定
                sync_info=sync_info,  # 新增：传递同步信息
                humanization_config=humanization_config,
                chapter_length=chapter_length
            )
            logger.debug(f"完整提示词: {prompt}")

            # 从人性化配置中提取采样参数，传递给模型
            gen_kwargs = {}
            hum_temperature = humanization_config.get("temperature")
            hum_top_p = humanization_config.get("top_p")
            if hum_temperature is not None:
                gen_kwargs["temperature"] = float(hum_temperature)
            if hum_top_p is not None:
                gen_kwargs["top_p"] = float(hum_top_p)
            if gen_kwargs:
                logger.info(f"第 {chapter_num} 章：应用人性化采样参数 {gen_kwargs}")

            # 调用模型生成内容
            content = self.content_model.generate(prompt, **gen_kwargs)
            if not content or not content.strip():
                logger.error(f"第 {chapter_num} 章：模型返回内容为空或仅包含空白字符。")
                return None

            logger.info(f"第 {chapter_num} 章：原始内容生成成功，字数: {len(content)}")
            return content

        except Exception as e:
            logger.error(f"生成第 {chapter_outline.chapter_number} 章原始内容时出错: {str(e)}", exc_info=True)
            return None

    def _adjust_chapter_length(
        self,
        content: str,
        actual_length: int,
        target_length: int,
        chapter_outline: ChapterOutline
    ) -> Optional[str]:
        """基于已有内容进行字数缩写或扩写调整

        Args:
            content: 已生成的章节内容
            actual_length: 当前字数
            target_length: 目标字数
            chapter_outline: 章节大纲

        Returns:
            调整后的内容，失败返回 None
        """
        try:
            min_len = int(target_length * 0.8)
            max_len = int(target_length * 1.2)

            if actual_length > target_length:
                # 缩写
                action = "精简缩写"
                instruction = (
                    f"当前内容 {actual_length} 字，目标 {target_length} 字（允许 {min_len}~{max_len}）。\n"
                    "请对以下章节内容进行精简缩写，要求：\n"
                    "1. 保留所有关键剧情点、人物对话的核心内容和重要转折\n"
                    "2. 删减冗余的环境描写、重复的心理活动、过度的修饰语\n"
                    "3. 压缩过长的动作描写和场景过渡\n"
                    "4. 保持故事连贯性和人物性格一致性\n"
                    "5. 直接输出缩写后的完整章节内容，不要添加任何说明"
                )
            else:
                # 扩写
                action = "扩展充实"
                instruction = (
                    f"当前内容 {actual_length} 字，目标 {target_length} 字（允许 {min_len}~{max_len}）。\n"
                    "请对以下章节内容进行扩展充实，要求：\n"
                    "1. 围绕现有剧情点增加细节描写、人物对话和心理活动\n"
                    "2. 补充环境氛围描写和角色互动\n"
                    "3. 不要改变原有剧情走向和人物设定\n"
                    "4. 新增内容要自然融入，不能有拼凑感\n"
                    "5. 直接输出扩写后的完整章节内容，不要添加任何说明"
                )

            prompt = (
                f"【章节信息】第{chapter_outline.chapter_number}章：{chapter_outline.title}\n"
                f"【任务】{action}\n"
                f"{instruction}\n\n"
                f"【原始内容】\n{content}"
            )

            logger.info(f"[Chapter {chapter_outline.chapter_number}] 开始{action}，prompt 长度: {len(prompt)}")
            adjusted = self.content_model.generate(prompt)

            if adjusted and adjusted.strip():
                new_length = len(adjusted.strip())
                logger.info(
                    f"[Chapter {chapter_outline.chapter_number}] {action}完成: "
                    f"{actual_length} → {new_length} 字"
                )
                return adjusted.strip()
            else:
                logger.warning(f"[Chapter {chapter_outline.chapter_number}] {action}返回为空")
                return None

        except Exception as e:
            logger.error(f"[Chapter {chapter_outline.chapter_number}] 字数调整出错: {str(e)}")
            return None

    def _clean_filename(self, filename: str) -> str:
        """清理字符串，使其适合作为文件名"""
        # 移除常见非法字符
        cleaned = re.sub(r'[\\/*?:"<>|]', "", filename)
        # 替换空格为下划线（可选）
        # cleaned = cleaned.replace(" ", "_")
        # 移除可能导致问题的首尾空格或点
        cleaned = cleaned.strip(". ")
        # 防止文件名过长 (可选)
        # max_len = 100
        # if len(cleaned) > max_len:
        #     name_part, ext = os.path.splitext(cleaned)
        #     cleaned = name_part[:max_len-len(ext)-3] + "..." + ext
        # 如果清理后为空，提供默认名称
        if not cleaned:
            return "untitled_chapter"
        return cleaned

    def _save_chapter_content(self, chapter_num: int, content: str) -> bool:
        """保存章节内容，使用 '第X章_标题.txt' 格式"""
        try:
            # 检查 chapter_num 是否在有效范围内
            if not (1 <= chapter_num <= len(self.chapter_outlines)):
                logger.error(f"无法保存章节 {chapter_num}：无效的章节号。")
                return False

            # 获取章节大纲和标题
            chapter_outline = self.chapter_outlines[chapter_num - 1]
            title = chapter_outline.title

            # 清理标题作为文件名的一部分
            cleaned_title = self._clean_filename(title)

            # 构建新的文件名格式
            filename = f"第{chapter_num}章_{cleaned_title}.txt"
            chapter_file = os.path.join(self.output_dir, filename)

            with open(chapter_file, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info(f"已保存第 {chapter_num} 章内容到 {chapter_file}")
            return True

        except IndexError:
             logger.error(f"无法获取第 {chapter_num} 章的大纲信息来生成文件名。")
             return False
        except Exception as e:
            logger.error(f"保存第 {chapter_num} 章内容时出错: {str(e)}")
            return False

    def _get_context_for_chapter(self, chapter_num: int) -> str:
        """获取章节的上下文信息

        采集前3章摘要 + 前一章结尾正文 + 后3章大纲预览，
        为模型提供充分的前后文衔接信息。
        """
        context_parts = []
        max_summary_len = 500

        # ── 1. 前3章摘要（从远到近排列，让模型看到情节发展脉络） ──
        summaries_collected = 0
        for prev_ch in range(max(1, chapter_num - 3), chapter_num):
            try:
                summary = self.consistency_checker._get_previous_summary(prev_ch)
                if summary:
                    if len(summary) > max_summary_len:
                        summary = summary[:max_summary_len] + "..."
                    context_parts.append(f"第{prev_ch}章摘要：{summary}")
                    summaries_collected += 1
            except Exception as e:
                logger.warning(f"获取第{prev_ch}章摘要时出错: {e}")
        if summaries_collected > 0:
            logger.debug(f"获取到前 {summaries_collected} 章摘要")

        # ── 2. 前一章结尾正文（直接衔接用） ──
        if chapter_num > 1:
            try:
                prev_ch = chapter_num - 1
                if 0 <= prev_ch - 1 < len(self.chapter_outlines):
                    prev_title = self.chapter_outlines[prev_ch - 1].title
                    prev_file = os.path.join(
                        self.output_dir,
                        f"第{prev_ch}章_{self._clean_filename(prev_title)}.txt",
                    )
                    if os.path.exists(prev_file):
                        with open(prev_file, "r", encoding="utf-8") as f:
                            prev_content = f.read()
                        max_tail = 2000
                        if len(prev_content) > max_tail:
                            context_parts.append(f"前一章结尾：\n{prev_content[-max_tail:]}")
                        else:
                            context_parts.append(f"前一章内容：\n{prev_content}")
                    else:
                        logger.warning(f"未找到前一章文件: {prev_file}")
            except Exception as e:
                logger.warning(f"读取前一章内容时出错: {e}")

        # ── 3. 后3章大纲预览（让模型知道后续走向，合理铺垫伏笔） ──
        next_previews = []
        for next_ch in range(chapter_num + 1, min(chapter_num + 4, len(self.chapter_outlines) + 1)):
            try:
                idx = next_ch - 1
                if idx < len(self.chapter_outlines) and self.chapter_outlines[idx] is not None:
                    outline = self.chapter_outlines[idx]
                    preview = f"第{next_ch}章「{outline.title}」: {', '.join(outline.key_points[:3])}"
                    next_previews.append(preview)
            except Exception as e:
                logger.warning(f"获取第{next_ch}章大纲预览时出错: {e}")
        if next_previews:
            context_parts.append("后续章节预览（用于伏笔铺垫，不要提前剧透）：\n" + "\n".join(next_previews))

        # ── 4. 组装并限制总长度 ──
        if not context_parts:
            return "（这是第一章，无前文）" if chapter_num <= 1 else "（无法获取前后章节信息）"

        combined = "\n\n".join(context_parts)
        max_total = 5000
        if len(combined) > max_total:
            combined = combined[-max_total:]
            combined = "...(前文已省略)\n" + combined
        return combined

    def _get_references_for_chapter(self, chapter_outline: ChapterOutline) -> dict:
        """获取章节的参考信息（从知识库），使用优化后的检索逻辑"""
        references = {
            "plot_references": [],
            "character_references": [],
            "setting_references": []
        }

        try:
            # 检查知识库状态
            if not hasattr(self.knowledge_base, 'is_built') or not self.knowledge_base.is_built:
                logging.warning("知识库未构建，跳过检索")
                return references
                
            if not hasattr(self.knowledge_base, 'index') or self.knowledge_base.index is None:
                logging.warning("知识库索引不存在，跳过检索")
                return references
            
            # 生成检索关键词
            search_prompt = get_knowledge_search_prompt(
                chapter_number=chapter_outline.chapter_number,
                chapter_title=chapter_outline.title,
                characters_involved=chapter_outline.characters,
                key_items=chapter_outline.key_points,  # 假设关键点可作为检索项
                scene_location=", ".join(chapter_outline.settings),
                chapter_role="发展",  # 可根据实际需求调整
                chapter_purpose="推动主线",  # 可根据实际需求调整
                foreshadowing="",  # 可根据实际需求补充
                short_summary="",  # 可根据实际需求补充
            )

            # 添加日志，记录搜索提示词
            logger.info(f"搜索提示词: {search_prompt[:100]}...，长度: {len(search_prompt)}")
            
            # 检查知识库对象
            logger.info(f"知识库对象类型: {type(self.knowledge_base)}")
            logger.info(f"知识库是否已构建: {getattr(self.knowledge_base, 'is_built', False)}")
            logger.info(f"知识库索引类型: {type(getattr(self.knowledge_base, 'index', None))}")
            
            # 调用知识库检索
            logger.info("开始调用知识库搜索方法...")
            relevant_knowledge = self.knowledge_base.search(search_prompt, k=15)
            
            # 检查返回结果
            logger.info(f"知识库搜索返回结果类型: {type(relevant_knowledge)}")
            logger.info(f"知识库搜索返回结果长度: {len(relevant_knowledge) if relevant_knowledge else 0}")
            
            if relevant_knowledge and isinstance(relevant_knowledge, list):
                # 按比例分配：plot 占 40%，character 占 30%，setting 占 30%
                total = len(relevant_knowledge)
                plot_end = max(1, int(total * 0.4))
                char_end = plot_end + max(1, int(total * 0.3))
                references["plot_references"] = relevant_knowledge[:plot_end]
                references["character_references"] = relevant_knowledge[plot_end:char_end]
                references["setting_references"] = relevant_knowledge[char_end:]
                logger.info(f"成功分配参考信息，共 {total} 项（情节:{plot_end} 人物:{char_end - plot_end} 场景:{total - char_end}）")
            else:
                logger.warning(f"知识库返回结果无效或为空: {relevant_knowledge}")

        except Exception as e:
            logger.error(f"优化检索章节参考信息时出错: {str(e)}", exc_info=True)  # 添加exc_info获取完整堆栈

        return references

    def _init_knowledge_base(self):
        """初始化知识库，确保在使用前已构建"""
        try:
            if not hasattr(self.knowledge_base, 'is_built') or not self.knowledge_base.is_built:
                kb_files = self.config.knowledge_base_config.get("reference_files", [])
                if not kb_files:
                    logger.warning("配置中未找到知识库参考文件路径")
                    return
                
                # 检查文件是否存在
                existing_files = []
                for file_path in kb_files:
                    if os.path.exists(file_path):
                        existing_files.append(file_path)
                    else:
                        logger.warning(f"参考文件不存在: {file_path}")
                
                if existing_files:
                    logger.info("开始构建知识库...")
                    self.knowledge_base.build_from_files(existing_files)
                    logger.info("知识库构建完成")
                else:
                    logger.error("没有找到任何可用的参考文件")
        except Exception as e:
            logger.error(f"初始化知识库时出错: {str(e)}")

    def _check_and_update_cache(self, chapter_num: int) -> None:
        """检查是否需要更新缓存，每5章更新一次"""
        # 修改判断逻辑，检查是否是第5/10/15...章
        logger.info(f"检查是否需要更新缓存，最后更新章节: {chapter_num}, 缓存条件: (chapter_num % 5) == 0, 结果: {(chapter_num % 5) == 0}")
        if (chapter_num % 5) == 0:  # 正好是5的倍数章节
            # 先更新最后更新章节进度，确保包含最后更新章节
            self.current_chapter = chapter_num
            logger.info(f"已完成第 {chapter_num} 章，开始更新缓存...")
            self._update_content_cache()
            logger.info(f"开始更新同步信息文件: {self.sync_info_file}")
            self._trigger_sync_info_update(self.content_model)
            self.chapters_since_last_cache = 0
        else:
            self.chapters_since_last_cache += 1
            logger.info(f"最后更新章节 {chapter_num} 不需要更新缓存，距离上次更新已经处理了 {self.chapters_since_last_cache} 章。")

    def _update_content_cache(self) -> None:
        """更新正文知识库缓存（流式构建合并文本，避免同时持有所有章节内容）"""
        try:
            # 直接流式拼接，避免 list + combined_text 双倍内存峰值
            combined_text = ""
            chapter_count = 0
            for chapter_num in range(1, self.current_chapter + 1):
                filename = f"第{chapter_num}章_{self._clean_filename(self.chapter_outlines[chapter_num-1].title)}.txt"
                filepath = os.path.join(self.output_dir, filename)
                if os.path.exists(filepath):
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                    combined_text += f"第{chapter_num}章\n{content}\n\n"
                    chapter_count += 1
                    logger.debug(f"已读取第 {chapter_num} 章内容，长度: {len(content)}")

            if chapter_count > 0:
                # 直接调用 build()，跳过 build_from_texts 的额外拼接
                old_cache_dir = self.knowledge_base.cache_dir
                self.knowledge_base.cache_dir = self.content_kb_dir
                os.makedirs(self.content_kb_dir, exist_ok=True)
                try:
                    self.knowledge_base.build(combined_text)
                finally:
                    self.knowledge_base.cache_dir = old_cache_dir
                logger.info(f"正文知识库缓存更新完成，共处理 {chapter_count} 章内容")
            else:
                logger.warning("未找到任何已完成的章节内容")

        except Exception as e:
            logger.error(f"更新正文知识库缓存时出错: {str(e)}")

    def _trigger_sync_info_update(self, sync_model=None) -> None:
        """触发同步信息更新"""
        os.makedirs(os.path.dirname(self.sync_info_file), exist_ok=True)
        # 使用 self.current_chapter 而不是其他变量
        logger.info(f"准备更新同步信息，最后更新章节进度: {self.current_chapter}，同步信息文件: {self.sync_info_file}")
        try:
            all_content = ""
            # 只读取最近5章的内容来更新同步信息
            num_chapters_to_include = 5
            start_chapter_for_sync = max(1, self.current_chapter - num_chapters_to_include + 1)

            logger.info(f"将读取第 {start_chapter_for_sync} 章到第 {self.current_chapter} 章的内容来生成同步信息。")

            for chapter_num in range(start_chapter_for_sync, self.current_chapter + 1):
                if chapter_num - 1 < len(self.chapter_outlines):
                    filename = f"第{chapter_num}章_{self._clean_filename(self.chapter_outlines[chapter_num-1].title)}.txt"
                    filepath = os.path.join(self.output_dir, filename)
                    logger.debug(f"尝试读取章节文件: {filepath}")
                    if os.path.exists(filepath):
                        with open(filepath, 'r', encoding='utf-8') as f:
                            chapter_text = f.read()
                            # 每章限制最多 6000 字符，保留首尾各 3000
                            max_per_chapter = 6000
                            if len(chapter_text) > max_per_chapter:
                                half = max_per_chapter // 2
                                chapter_text = chapter_text[:half] + "\n...(中间省略)...\n" + chapter_text[-half:]
                            all_content += chapter_text + "\n\n"
                    else:
                        logger.warning(f"文件不存在，无法读取: {filepath}")
                else:
                    logger.warning(f"章节大纲中不存在章节 {chapter_num}，跳过读取。")


            if all_content:
                logger.info(f"成功读取最近章节内容，总字数: {len(all_content)}，开始生成同步信息")
                prompt = self._create_sync_info_prompt(all_content)
                
                # 使用指定的模型或默认使用content_model
                model_to_use = sync_model if sync_model is not None else self.content_model
                
                # 增加重试机制和错误处理
                max_retries = 5  # 增加重试次数
                sync_info = None
                
                for attempt in range(max_retries):
                    try:
                        sync_info = model_to_use.generate(prompt)
                        if sync_info:
                            break
                        else:
                            logger.warning(f"模型返回空的同步信息，尝试 {attempt + 1}/{max_retries}")
                            if attempt == max_retries - 1:
                                logger.warning("模型返回空的同步信息，使用降级方案")
                                self._fallback_sync_info_update()
                                return
                    except Exception as e:
                        logger.error(f"模型调用失败 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
                        if attempt == max_retries - 1:
                            logger.error("所有重试都失败了，使用降级方案")
                            self._fallback_sync_info_update()
                            return
                        # 等待一段时间后重试
                        time.sleep(10 * (attempt + 1))  # 递增等待时间
                
                if not sync_info:
                    logger.warning("模型返回空的同步信息，使用降级方案")
                    self._fallback_sync_info_update()
                    return
                
                try:
                    # 尝试提取JSON部分 - 有时模型会生成额外文本
                    json_start = sync_info.find('{')
                    json_end = sync_info.rfind('}') + 1
                    
                    if json_start >= 0 and json_end > json_start:
                        json_content = sync_info[json_start:json_end]
                        logger.info(f"提取到JSON内容，长度: {len(json_content)}")
                        sync_info_dict = json.loads(json_content)
                        
                        # 应用进度保护逻辑
                        sync_info_dict = self._apply_progress_protection(sync_info_dict, self.current_chapter)
                        
                        logger.info(f"成功解析同步信息JSON，准备写入文件: {self.sync_info_file}")
                        with open(self.sync_info_file, 'w', encoding='utf-8') as f:
                            json.dump(sync_info_dict, f, ensure_ascii=False, indent=2)
                        logger.info(f"同步信息更新完成，文件大小: {os.path.getsize(self.sync_info_file)} 字节")
                    else:
                        logger.error(f"无法在生成的内容中找到JSON格式数据，原始内容前200个字符: {sync_info[:200]}...")
                        # 保存原始输出以供调试
                        debug_file = os.path.join(os.path.dirname(self.sync_info_file), "sync_info_raw.txt")
                        with open(debug_file, 'w', encoding='utf-8') as f:
                            f.write(sync_info)
                        logger.info(f"已保存原始输出到 {debug_file} 以供调试")
                        self._fallback_sync_info_update()
                except json.JSONDecodeError as e:
                    logger.error(f"生成的同步信息不是有效的JSON格式: {e}")
                    logger.debug(f"无效的JSON内容前200个字符: {sync_info[:200]}...")
                    # 保存原始输出以供调试
                    debug_file = os.path.join(os.path.dirname(self.sync_info_file), "sync_info_raw.txt")
                    with open(debug_file, 'w', encoding='utf-8') as f:
                        f.write(sync_info)
                    logger.info(f"已保存原始输出到 {debug_file} 以供调试")
                    self._fallback_sync_info_update()
            else:
                logger.warning("未找到任何已完成的章节内容，使用降级方案")
                self._fallback_sync_info_update()
        except Exception as e:
            logger.error(f"更新同步信息时出错: {str(e)}", exc_info=True)
            self._fallback_sync_info_update()

    def _should_protect_progress(self, current_generating_chapter: int, existing_progress: int) -> bool:
        """
        判断是否需要保护现有进度
        
        Args:
            current_generating_chapter: 当前正在生成的章节号
            existing_progress: 现有同步信息中的进度
        
        Returns:
            bool: True表示需要保护现有进度，False表示可以更新进度
        """
        # 处理各种边界情况
        if existing_progress is None:
            # 如果现有进度为空，则不需要保护
            logger.info(f"现有进度为空，正常更新进度为 {current_generating_chapter}")
            return False
        
        # 确保输入参数为整数类型，处理更多异常情况
        try:
            # 处理字符串类型的章节号
            if isinstance(current_generating_chapter, str):
                current_generating_chapter = current_generating_chapter.strip()
                if not current_generating_chapter:
                    logger.warning("最后更新章节号为空字符串，无法比较进度，不保护现有进度")
                    return False
            
            if isinstance(existing_progress, str):
                existing_progress = existing_progress.strip()
                if not existing_progress:
                    logger.warning("现有进度为空字符串，正常更新进度")
                    return False
            
            current_generating_chapter = int(current_generating_chapter)
            existing_progress = int(existing_progress)
            
            # 验证章节号的合理性
            if current_generating_chapter < 0:
                logger.warning(f"最后更新章节号无效 ({current_generating_chapter})，不保护现有进度")
                return False
            
            if existing_progress < 0:
                logger.warning(f"现有进度无效 ({existing_progress})，正常更新进度")
                return False
                
        except (ValueError, TypeError) as e:
            logger.warning(f"章节号格式错误，无法比较进度: current={current_generating_chapter}, existing={existing_progress}, error={e}，不保护现有进度")
            return False
        
        # 如果当前生成章节小于现有进度，则需要保护现有进度
        should_protect = current_generating_chapter < existing_progress
        
        if should_protect:
            logger.info(f"进度保护触发：当前生成章节 {current_generating_chapter} < 现有进度 {existing_progress}，保护现有进度")
        else:
            logger.info(f"进度正常更新：当前生成章节 {current_generating_chapter} >= 现有进度 {existing_progress}，更新进度")
        
        return should_protect

    def _apply_progress_protection(self, sync_info_dict: dict, current_chapter: int) -> dict:
        """
        应用进度保护到同步信息字典
        
        Args:
            sync_info_dict: 同步信息字典（可能来自模型生成）
            current_chapter: 当前生成的章节号
        
        Returns:
            dict: 应用进度保护后的同步信息字典
        """
        try:
            # 确保sync_info_dict是字典类型
            if not isinstance(sync_info_dict, dict):
                logger.warning(f"sync_info_dict不是字典类型: {type(sync_info_dict)}，创建新字典")
                sync_info_dict = {}
            
            # 加载现有同步信息以获取真实的当前进度
            existing_sync_info = self._load_sync_info()
            # 处理现有进度的各种异常情况，兼容旧版字段
            existing_progress = existing_sync_info.get("最后更新章节", existing_sync_info.get("当前章节"))
            
            # 处理现有进度的各种异常情况
            if existing_progress is not None:
                try:
                    # 尝试将现有进度转换为整数
                    if isinstance(existing_progress, str):
                        existing_progress = existing_progress.strip()
                        if not existing_progress:
                            logger.warning("现有进度为空字符串，视为无现有进度")
                            existing_progress = None
                        else:
                            existing_progress = int(existing_progress)
                    elif not isinstance(existing_progress, int):
                        logger.warning(f"现有进度类型异常: {type(existing_progress)}，尝试转换为整数")
                        existing_progress = int(existing_progress)
                    
                    # 验证现有进度的合理性
                    if existing_progress is not None and existing_progress < 0:
                        logger.warning(f"现有进度值无效 ({existing_progress})，视为无现有进度")
                        existing_progress = None
                        
                except (ValueError, TypeError) as e:
                    logger.warning(f"现有进度格式错误，无法解析: {existing_sync_info.get('最后更新章节')} - {e}，视为无现有进度")
                    existing_progress = None
            
            # 判断是否需要保护进度
            if self._should_protect_progress(current_chapter, existing_progress):
                # 保护现有进度，使用现有同步信息中的进度
                sync_info_dict["最后更新章节"] = existing_progress
                logger.info(f"应用进度保护：保持现有进度 {existing_progress}，不更新为 {current_chapter}")
            else:
                # 正常更新进度
                sync_info_dict["最后更新章节"] = current_chapter
                logger.info(f"正常更新进度：从 {existing_progress} 更新为 {current_chapter}")
            
            # 始终更新"最后更新时间"字段
            sync_info_dict["最后更新时间"] = time.strftime("%Y-%m-%d %H:%M:%S")
            
            # 确保向后兼容性：保留其他现有字段（如果存在）
            if existing_sync_info:
                for key, value in existing_sync_info.items():
                    if key not in sync_info_dict and key != "最后更新章节":
                        # 保留现有字段，但不覆盖新生成的字段
                        sync_info_dict[key] = value
                        logger.debug(f"保留现有字段: {key}")
            
            return sync_info_dict
            
        except Exception as e:
            logger.error(f"应用进度保护时出错: {str(e)}", exc_info=True)
            # 出错时确保返回有效的字典，并设置基本字段
            if not isinstance(sync_info_dict, dict):
                sync_info_dict = {}
            
            # 尝试保留原有的sync_info_dict内容
            try:
                # 确保至少有基本字段
                sync_info_dict["最后更新章节"] = current_chapter
                sync_info_dict["最后更新时间"] = time.strftime("%Y-%m-%d %H:%M:%S")
                
                # 尝试从现有文件中恢复其他字段以保持向后兼容性
                existing_sync_info = self._load_sync_info()
                if existing_sync_info:
                    for key, value in existing_sync_info.items():
                        if key not in sync_info_dict and key != "最后更新章节":
                            sync_info_dict[key] = value
                            
            except Exception as recovery_error:
                logger.error(f"恢复同步信息字段时也出错: {recovery_error}")
                # 最后的保底措施
                sync_info_dict = {
                    "最后更新章节": current_chapter,
                    "最后更新时间": time.strftime("%Y-%m-%d %H:%M:%S")
                }
            
            return sync_info_dict

    def _fallback_sync_info_update(self) -> None:
        """
        降级方案：手动更新同步信息
        处理各种异常情况以确保向后兼容性
        """
        try:
            logger.info("使用降级方案更新同步信息")
            
            # 使用已有的_load_sync_info方法加载现有同步信息
            # 这个方法已经处理了各种异常情况
            existing_sync_info = self._load_sync_info()
            
            # 如果加载失败，创建基本的同步信息结构
            if not existing_sync_info:
                logger.info("创建新的同步信息结构")
                existing_sync_info = {
                    "最后更新章节": None,
                    "最后更新时间": None,
                    "世界观": {},
                    "人物设定": {},
                    "剧情发展": {},
                    "前情提要": []
                }
            
            # 应用进度保护逻辑
            existing_sync_info = self._apply_progress_protection(existing_sync_info, self.current_chapter)
            
            # 确保必要字段存在
            if "前情提要" not in existing_sync_info:
                existing_sync_info["前情提要"] = []
            elif not isinstance(existing_sync_info["前情提要"], list):
                logger.warning(f"'前情提要'字段类型异常: {type(existing_sync_info['前情提要'])}，重置为空列表")
                existing_sync_info["前情提要"] = []
            
            # 获取最近完成的章节信息
            recent_chapters = []
            try:
                for chapter_num in range(max(1, self.current_chapter - 4), self.current_chapter + 1):
                    if chapter_num - 1 < len(self.chapter_outlines):
                        outline = self.chapter_outlines[chapter_num - 1]
                        if outline and hasattr(outline, 'title'):
                            recent_chapters.append(f"第{chapter_num}章：{outline.title}")
                        else:
                            logger.warning(f"第{chapter_num}章大纲信息缺失或无效")
            except Exception as e:
                logger.warning(f"获取最近章节信息时出错: {e}")
            
            # 添加新的前情提要
            if recent_chapters:
                summary = f"最近完成章节：{', '.join(recent_chapters)}"
                try:
                    if summary not in existing_sync_info["前情提要"]:
                        existing_sync_info["前情提要"].append(summary)
                        logger.debug(f"添加前情提要: {summary}")
                except Exception as e:
                    logger.warning(f"添加前情提要时出错: {e}")
            
            # 确保其他基本字段存在
            basic_fields = {
                "世界观": {},
                "人物设定": {},
                "剧情发展": {}
            }
            
            for field, default_value in basic_fields.items():
                if field not in existing_sync_info:
                    existing_sync_info[field] = default_value
                    logger.debug(f"添加缺失字段: {field}")
            
            # 保存更新后的同步信息
            try:
                # 确保输出目录存在
                os.makedirs(os.path.dirname(self.sync_info_file), exist_ok=True)
                
                # 先写入临时文件，然后重命名，避免写入过程中出错导致文件损坏
                temp_file = self.sync_info_file + ".tmp"
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(existing_sync_info, f, ensure_ascii=False, indent=2)
                
                # 原子性地替换文件
                if os.path.exists(temp_file):
                    if os.path.exists(self.sync_info_file):
                        # 备份原文件
                        backup_file = self.sync_info_file + ".backup"
                        try:
                            import shutil
                            shutil.copy2(self.sync_info_file, backup_file)
                            logger.debug(f"已备份原同步信息文件到 {backup_file}")
                        except Exception as backup_error:
                            logger.warning(f"备份原文件失败: {backup_error}")
                    
                    # 替换文件
                    os.replace(temp_file, self.sync_info_file)
                    logger.info(f"降级方案同步信息更新完成，文件大小: {os.path.getsize(self.sync_info_file)} 字节")
                else:
                    logger.error("临时文件创建失败，无法保存同步信息")
                    
            except OSError as e:
                logger.error(f"保存同步信息文件时发生系统错误: {e}")
                # 尝试直接写入（不使用临时文件）
                try:
                    with open(self.sync_info_file, 'w', encoding='utf-8') as f:
                        json.dump(existing_sync_info, f, ensure_ascii=False, indent=2)
                    logger.info("使用直接写入方式保存同步信息成功")
                except Exception as direct_write_error:
                    logger.error(f"直接写入也失败: {direct_write_error}")
                    raise
            
        except Exception as e:
            logger.error(f"降级方案也失败了: {str(e)}", exc_info=True)
            
            # 最后的保底措施：创建最基本的同步信息文件
            try:
                minimal_sync_info = {
                    "最后更新章节": self.current_chapter,
                    "最后更新时间": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "前情提要": [f"降级方案生成 - 最后更新章节: {self.current_chapter}"]
                }
                
                os.makedirs(os.path.dirname(self.sync_info_file), exist_ok=True)
                with open(self.sync_info_file, 'w', encoding='utf-8') as f:
                    json.dump(minimal_sync_info, f, ensure_ascii=False, indent=2)
                
                logger.info("已创建最基本的同步信息文件作为保底措施")
                
            except Exception as final_error:
                logger.error(f"保底措施也失败了: {final_error}")
                # 此时已经无法创建同步信息文件，但不应该影响主要功能

    def _create_sync_info_prompt(self, story_content: str) -> str:
        """创建生成同步信息的提示词"""
        existing_sync_info = ""
        if os.path.exists(self.sync_info_file):
            try:
                with open(self.sync_info_file, 'r', encoding='utf-8') as f:
                    existing_sync_info = f.read()
            except Exception as e:
                logger.warning(f"读取现有同步信息时出错: {str(e)}")

        # 限制各部分长度，防止 prompt 超过模型输入限制
        max_sync_info_len = 8000
        max_story_len = 30000
        if len(existing_sync_info) > max_sync_info_len:
            logger.warning(f"现有同步信息过长 ({len(existing_sync_info)} 字符)，截断到 {max_sync_info_len}")
            existing_sync_info = existing_sync_info[:max_sync_info_len] + "\n...(已截断)"
        if len(story_content) > max_story_len:
            logger.warning(f"故事内容过长 ({len(story_content)} 字符)，截断到 {max_story_len}")
            story_content = story_content[:max_story_len] + "\n...(已截断)"

        return get_sync_info_prompt(
            story_content=story_content,
            existing_sync_info=existing_sync_info,
            current_chapter=self.current_chapter
        )

    def _load_sync_info(self) -> dict:
        """
        加载同步信息并解析为字典
        处理各种异常情况以确保向后兼容性
        """
        # 处理同步信息文件不存在的情况
        if not os.path.exists(self.sync_info_file):
            logger.info(f"同步信息文件 {self.sync_info_file} 不存在，返回空字典（首次运行或文件被删除）")
            return {}
        
        try:
            # 检查文件权限
            if not os.access(self.sync_info_file, os.R_OK):
                logger.error(f"同步信息文件 {self.sync_info_file} 无读取权限，返回空字典")
                return {}
            
            with open(self.sync_info_file, 'r', encoding='utf-8') as f:
                content = f.read()
                
                # 处理空文件的情况
                if not content.strip():
                    logger.warning(f"同步信息文件 {self.sync_info_file} 为空，返回空字典")
                    return {}
                
                # 尝试解析 JSON 内容
                try:
                    sync_info = json.loads(content)
                    
                    # 验证解析结果是否为字典
                    if not isinstance(sync_info, dict):
                        logger.error(f"同步信息文件内容不是字典格式: {type(sync_info)}，返回空字典")
                        return {}
                    
                    # 处理"最后更新章节"字段的各种异常情况（兼容旧版"当前章节"）
                    if "最后更新章节" in sync_info or "当前章节" in sync_info:
                        current_chapter = sync_info.get("最后更新章节", sync_info.get("当前章节"))
                        
                        # 处理字段值为None的情况
                        if current_chapter is None:
                            logger.warning("同步信息中'最后更新章节'字段为None，保持原样")
                        
                        # 处理字段值为空字符串的情况
                        elif isinstance(current_chapter, str) and not current_chapter.strip():
                            logger.warning("同步信息中'最后更新章节'字段为空字符串，设置为None")
                            sync_info["最后更新章节"] = None
                        
                        # 处理字段值为非数字字符串的情况
                        elif isinstance(current_chapter, str):
                            try:
                                # 尝试转换为整数
                                chapter_num = int(current_chapter.strip())
                                if chapter_num < 0:
                                    logger.warning(f"同步信息中'最后更新章节'字段值无效 ({chapter_num})，设置为None")
                                    sync_info["最后更新章节"] = None
                                else:
                                    sync_info["最后更新章节"] = chapter_num
                                    logger.debug(f"成功将'最后更新章节'字段从字符串转换为整数: {chapter_num}")
                            except ValueError:
                                logger.warning(f"同步信息中'最后更新章节'字段无法转换为整数: '{current_chapter}'，设置为None")
                                sync_info["最后更新章节"] = None
                        
                        # 处理字段值为浮点数的情况
                        elif isinstance(current_chapter, float):
                            if current_chapter.is_integer() and current_chapter >= 0:
                                sync_info["最后更新章节"] = int(current_chapter)
                                logger.debug(f"将'最后更新章节'字段从浮点数转换为整数: {int(current_chapter)}")
                            else:
                                logger.warning(f"同步信息中'最后更新章节'字段为无效浮点数: {current_chapter}，设置为None")
                                sync_info["最后更新章节"] = None
                        
                        # 处理字段值为布尔类型的情况
                        elif isinstance(current_chapter, bool):
                            logger.warning(f"同步信息中'最后更新章节'字段为布尔类型: {current_chapter}，设置为None")
                            sync_info["最后更新章节"] = None
                        
                        # 处理字段值为其他类型的情况
                        elif not isinstance(current_chapter, int):
                            logger.warning(f"同步信息中'最后更新章节'字段类型异常: {type(current_chapter)}，设置为None")
                            sync_info["最后更新章节"] = None
                        
                        # 处理字段值为负数的情况
                        elif isinstance(current_chapter, int) and current_chapter < 0:
                            logger.warning(f"同步信息中'最后更新章节'字段值无效: {current_chapter}，设置为None")
                            sync_info["最后更新章节"] = None
                    
                    logger.debug(f"成功加载同步信息，包含 {len(sync_info)} 个字段")
                    return sync_info
                    
                except json.JSONDecodeError as e:
                    # 处理 JSON 解析错误
                    logger.error(f"解析同步信息文件 {self.sync_info_file} 失败: {e}")
                    
                    # 保存错误内容以便调试（可选）
                    try:
                        error_file = self.sync_info_file + ".error"
                        with open(error_file, 'w', encoding='utf-8') as f_err:
                            f_err.write(content)
                        logger.info(f"已保存损坏的同步信息内容到 {error_file} 以供调试")
                    except Exception as write_err:
                        logger.warning(f"无法保存错误内容到调试文件: {write_err}")
                    
                    return {}
                    
        except UnicodeDecodeError as e:
            # 处理文件编码错误
            logger.error(f"同步信息文件 {self.sync_info_file} 编码错误: {e}，返回空字典")
            return {}
            
        except PermissionError as e:
            # 处理权限错误
            logger.error(f"读取同步信息文件 {self.sync_info_file} 权限不足: {e}，返回空字典")
            return {}
            
        except OSError as e:
            # 处理其他系统级错误（如磁盘空间不足、文件系统错误等）
            logger.error(f"读取同步信息文件 {self.sync_info_file} 时发生系统错误: {e}，返回空字典")
            return {}
            
        except Exception as e:
            # 处理其他未预期的错误
            logger.error(f"读取同步信息文件 {self.sync_info_file} 时发生未知错误: {e}，返回空字典", exc_info=True)
            return {}

if __name__ == "__main__":
    import argparse
    # Import necessary modules, handling potential ImportErrors for standalone testing
    try:
        from src.config.config import Config # Config is usually needed
        # Need re for MockConsistencyChecker's parsing of score
        import re
        # Need json for MockConsistencyChecker's _get_previous_summary
        import json
    except ImportError:
        logger.warning("无法导入实际的 Config 类，将使用占位符。")
        class Config: pass
        # Define re and json locally if import fails (less likely but for completeness)
        import re
        import json

    # --- Mock Class Definitions ---
    class MockModel:
        # Correct indentation for methods
        def generate(self, prompt):
            logger.debug(f"[MockModel] Generating based on prompt starting with: {prompt[:100]}...")
            if "一致性检查" in prompt:
                logger.debug("[MockModel] Simulating consistency check report generation.")
                # Simulate a report that passes
                return "一致性检查报告：\n[主题]：符合\n[情节]：连贯\n[角色]：一致\n[世界观]：符合\n[逻辑]：无明显问题\n[总体评分]：85\n结论：无需修改"
            elif "修正章节内容" in prompt:
                logger.debug("[MockModel] Simulating chapter revision generation.")
                return f"[Mock] 这是模拟修正后的内容，基于报告：{prompt[:100]}..."
            else:
                logger.debug("[MockModel] Simulating raw content generation.")
                return f"[Mock] 这是模拟生成的章节内容，基于提示：{prompt[:100]}..."

    class MockKB:
        # Correct indentation for methods
        def search(self, query: str, k: int = 5) -> List[str]:
            """搜索相关内容"""
            logger.debug(f"[MockKB] Searching for: {query}")
            
            if not self.index:
                logger.error("知识库索引未构建")
                raise ValueError("Knowledge base not built yet")
            
            # 安全地记录索引类型，不访问.d属性
            logger.info(f"知识库索引类型: {type(self.index)}")
            
            query_vector = self.embedding_model.embed(query)
            
            if query_vector is None:
                logger.error("嵌入模型返回空向量")
                return []
            
            logger.info(f"查询向量类型: {type(query_vector)}, 长度: {len(query_vector)}")
            
            # 搜索最相似的文本块
            query_vector_array = np.array([query_vector]).astype('float32')
            logger.info(f"处理后的查询向量数组形状: {query_vector_array.shape}")
            
            try:
                logger.info(f"调用faiss搜索，参数: 向量形状={query_vector_array.shape}, k={k}")
                distances, indices = self.index.search(query_vector_array, k)
                logger.info(f"搜索结果: 距离形状={distances.shape}, 索引形状={indices.shape}")
            except Exception as e:
                logger.error(f"faiss搜索失败: {str(e)}", exc_info=True)
                raise
            
            # 返回相关文本内容
            results = []
            for idx in indices[0]:
                if idx < len(self.chunks):
                    results.append(self.chunks[idx].content)
                else:
                    logger.warning(f"索引越界: idx={idx}, chunks长度={len(self.chunks)}")
            
            logger.info(f"返回结果数量: {len(results)}")
            return results

    class MockConsistencyChecker:
        # Correct indentation for methods
        def __init__(self, model, output_dir):
            logger.info(f"[MockConsistencyChecker] Initialized with model {type(model)} and output_dir {output_dir}.")
            self.model = model
            self.output_dir = output_dir

        # Correct indentation for methods
        def ensure_chapter_consistency(self, chapter_content, chapter_outline, chapter_idx, characters=None):
            logger.info(f"[MockConsistencyChecker] Ensuring consistency for chapter_idx {chapter_idx}")
            # Simulate check
            check_prompt = f"模拟一致性检查提示 for chapter {chapter_idx+1}"
            consistency_report = self.model.generate(check_prompt)
            logger.info(f"[MockConsistencyChecker] Received report:\n{consistency_report}")

            # 使用正则提取 [修改必要性] 结构化字段，精确匹配，避免子串误判
            revision_match = re.search(r'\[修改必要性\]\s*[：:]\s*(.+?)(?:\n|$)', consistency_report)
            if revision_match:
                val = revision_match.group(1).strip().strip('""\'\'')
                needs_revision = val == "需要修改"
            else:
                needs_revision = True
            score_match = re.search(r'\[总体评分\]\s*:\s*(\d+)', consistency_report)
            score = int(score_match.group(1)) if score_match else 0

            if not needs_revision or score >= 75:
                logger.info(f"[MockConsistencyChecker] Chapter {chapter_idx+1} passed consistency check (Score: {score}).")
                return chapter_content
            else:
                logger.warning(f"[MockConsistencyChecker] Chapter {chapter_idx+1} needs revision (Score: {score}). Simulating revision...")
                revise_prompt = f"模拟修正提示 for chapter {chapter_idx+1} based on report: {consistency_report[:50]}..."
                revised_content = self.model.generate(revise_prompt)
                logger.info(f"[MockConsistencyChecker] Simulated revision complete for chapter {chapter_idx+1}.")
                return revised_content

        # Correct indentation for methods
        def _get_previous_summary(self, chapter_idx):
            logger.debug(f"[MockConsistencyChecker] Getting previous summary for chapter_idx {chapter_idx}")
            summary_file = os.path.join(self.output_dir, "summary.json")
            if chapter_idx >= 0 and os.path.exists(summary_file):
                try:
                    with open(summary_file, 'r', encoding='utf-8') as f:
                        summaries = json.load(f)
                        # Summaries keys are chapter numbers (1-based string)
                        return summaries.get(str(chapter_idx + 1 - 1), f"[Mock] Default Summary for Ch {chapter_idx}") # Get previous chapter's summary key is chapter_idx
                except Exception as e:
                    logger.error(f"[MockConsistencyChecker] Error reading summary file {summary_file}: {e}")
                    return f"[Mock] Error reading summary for Ch {chapter_idx}"
            return "" # No previous chapter or file not found

    class MockLogicValidator:
        # Correct indentation for methods
        def __init__(self, model):
            logger.info(f"[MockLogicValidator] Initialized with model {type(model)}.")
            self.model = model

        # Correct indentation for methods
        def check_logic(self, content, outline):
            logger.info(f"[MockLogicValidator] Checking logic for content starting with: {content[:50]}...")
            # Simulate check
            check_prompt = f"模拟逻辑检查提示 for content: {content[:50]}"
            report = self.model.generate(check_prompt)
            # 使用正则提取 [修改必要性] 结构化字段，精确匹配，避免子串误判
            revision_match = re.search(r'\[修改必要性\]\s*[：:]\s*(.+?)(?:\n|$)', report)
            if revision_match:
                val = revision_match.group(1).strip().strip('""\'\'')
                needs_revision = val == "需要修改"
            else:
                needs_revision = True
            logger.info(f"[MockLogicValidator] Logic check report generated. Needs revision: {needs_revision}")
            return report, needs_revision
    # --- Mock 类定义结束 ---

    parser = argparse.ArgumentParser(description='生成小说章节内容（带验证）')
    parser.add_argument('--config', type=str, default='config.json', help='配置文件路径')
    parser.add_argument('--target-chapter', type=int, help='指定要重新生成的章节号')
    parser.add_argument('--start-chapter', type=int, help='指定开始生成的章节号 (注意: main.py 中处理)')
    parser.add_argument('--extra-prompt', type=str, help='额外提示词')

    args = parser.parse_args()

    # 加载配置
    try:
        config = Config(args.config)
    except NameError:
         print("错误：Config 类未定义（可能由于导入失败）。无法加载配置。")
         exit(1)
    except FileNotFoundError:
        print(f"错误：找不到配置文件 {args.config}")
        exit(1)
    except Exception as e:
        print(f"加载配置 '{args.config}' 时出错: {e}")
        exit(1)

    # 设置日志 (Main block uses basicConfig for simplicity in test)
    log_dir = "data/logs" # Default log dir
    if hasattr(config, 'log_config') and isinstance(config.log_config, dict) and "log_dir" in config.log_config:
         log_dir = config.log_config["log_dir"]
    else:
         logging.warning("log_config 或 log_dir 未在配置中找到，将使用默认目录 'data/logs'") # Basic config will handle this logger call

    os.makedirs(log_dir, exist_ok=True)
    # Use basicConfig for standalone test - note this configures the root logger
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s',
                        handlers=[logging.FileHandler(os.path.join(log_dir, "content_gen_test.log"), encoding='utf-8', mode='w'),
                                  logging.StreamHandler()])
    
    # Get the named logger AFTER basicConfig is called
    logger = logging.getLogger(__name__) 
    
    logger.info(f"--- 开始独立测试 content_generator.py ---") # Now uses the configured logger
    logger.info(f"命令行参数: {args}") # Now uses the configured logger

    # 初始化 Mock 对象
    logger.info("使用 Mock 对象进行独立测试...") # Now uses the configured logger
    mock_content_model = MockModel()
    mock_knowledge_base = MockKB()

    # 创建 ContentGenerator 实例 (传入 Mock Model/KB)
    logger.info("创建 ContentGenerator 实例 (使用 Mock Model/KB)...") # Now uses the configured logger
    try:
        # Need to ensure the config object has 'output_config' attribute needed by ContentGenerator.__init__
        if not hasattr(config, 'output_config') or not isinstance(config.output_config, dict) or "output_dir" not in config.output_config:
             logger.error("配置文件缺少必要的 'output_config' 或 'output_dir'。") # Now uses the configured logger
             # Assign a default if possible for testing, or exit
             config.output_config = {"output_dir": "data/output_test"} # Example default
             logger.warning(f"使用默认 output_dir: {config.output_config['output_dir']}") # Now uses the configured logger
             os.makedirs(config.output_config['output_dir'], exist_ok=True)
             # exit(1) # Or exit if config is unusable

        generator = ContentGenerator(config, mock_content_model, mock_knowledge_base)
    except Exception as e:
        logger.error(f"创建 ContentGenerator 实例时出错: {e}", exc_info=True) # Now uses the configured logger
        exit(1)

    # 替换内部检查器为 Mock 版本
    logger.info("将生成器内部的检查器替换为 Mock 版本...") # Now uses the configured logger
    generator.consistency_checker = MockConsistencyChecker(mock_content_model, generator.output_dir)
    generator.logic_validator = MockLogicValidator(mock_content_model)

    # 检查大纲加载
    if not generator.chapter_outlines:
         logger.error("未能加载大纲，无法继续生成。请确保 outline.json 文件存在于 %s 且格式正确。", generator.output_dir) # Now uses the configured logger
    else:
        logger.info(f"成功加载 {len(generator.chapter_outlines)} 章大纲。") # Now uses the configured logger
        # 模拟设置起始章节
        if args.start_chapter and args.target_chapter is None:
             if 1 <= args.start_chapter <= len(generator.chapter_outlines) + 1:
                  generator.current_chapter = args.start_chapter - 1
                  logger.info(f"测试：模拟设置起始章节索引为 {generator.current_chapter}") # Now uses the configured logger
             else:
                  logger.error(f"测试：无效的起始章节 {args.start_chapter}，将使用加载的进度 {generator.current_chapter}") # Now uses the configured logger

        # 调用生成内容方法
        logger.info("调用 generator.generate_content...") # Now uses the configured logger
        try:
            success = generator.generate_content(
                target_chapter=args.target_chapter,
                external_prompt=args.extra_prompt
            )
        except Exception as e:
             logger.error(f"调用 generate_content 时发生错误: {e}", exc_info=True) # Now uses the configured logger
             success = False # Mark as failed

        # Standard print for final output
        print("\n内容生成流程结束。")
        print("结果：", "成功！" if success else "失败。")
        print(f'请查看日志文件 "{os.path.join(log_dir, "content_gen_test.log")}" 了解详细信息。')

    logger.info("--- 独立测试 content_generator.py 结束 ---") # Now uses the configured logger 
