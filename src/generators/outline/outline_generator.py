import os
import json
import logging
import time
from typing import List, Tuple, Optional
from ..common.data_structures import ChapterOutline
from ..common.utils import load_json_file, save_json_file, validate_directory
from ..prompts import get_outline_prompt, get_sync_info_prompt, get_core_seed_prompt

class OutlineGenerator:
    def __init__(self, config, outline_model, knowledge_base, content_model=None):
        self.config = config
        self.outline_model = outline_model
        self.content_model = content_model  # 添加备用模型
        self.knowledge_base = knowledge_base
        self.output_dir = config.output_config["output_dir"]
        self.chapter_outlines = []
        self.cancel_checker = None  # 可选：外部注入的取消检查回调，返回 True 表示应取消
        
        # 同步信息相关
        self.sync_info_file = os.path.join(self.output_dir, "sync_info.json")
        self.sync_info = self._load_sync_info()
        
        # 验证并创建输出目录
        validate_directory(self.output_dir)
        # 加载现有大纲
        self._load_outline()

    def _get_hashable_item(self, item):
        """Returns a hashable representation of an item for uniqueness checks."""
        if isinstance(item, dict):
            # For dictionaries, we'll try to find a '名称' key, otherwise use its string representation
            return item.get('名称', str(item))
        return item

    @staticmethod
    def _normalize_extended_outline_fields(chapter_data: dict) -> dict:
        """[H5] 归一化雪花写作法扩展字段,确保类型符合 ChapterOutline 定义

        Prompt 要求模型输出 emotion_tone / character_goals / scene_sequence /
        foreshadowing / pov_character 字段,但模型可能:
        - 返回 None / 缺字段 → 使用默认值
        - 返回错误类型(如 list 当 dict)→ 兜底为默认值并记录 warning
        """
        def _as_str(value, field_name):
            if value is None:
                return ""
            if isinstance(value, str):
                return value.strip()
            logging.warning(f"扩展字段 {field_name} 类型异常({type(value).__name__}),已兜底为空字符串")
            return ""

        def _as_list_str(value, field_name):
            if value is None:
                return []
            if isinstance(value, list):
                return [str(item).strip() for item in value if item is not None]
            logging.warning(f"扩展字段 {field_name} 类型异常({type(value).__name__}),已兜底为空列表")
            return []

        def _as_dict_str(value, field_name):
            if value is None:
                return {}
            if isinstance(value, dict):
                return {str(k): str(v) for k, v in value.items()}
            logging.warning(f"扩展字段 {field_name} 类型异常({type(value).__name__}),已兜底为空字典")
            return {}

        return {
            "emotion_tone": _as_str(chapter_data.get("emotion_tone"), "emotion_tone"),
            "character_goals": _as_dict_str(chapter_data.get("character_goals"), "character_goals"),
            "scene_sequence": _as_list_str(chapter_data.get("scene_sequence"), "scene_sequence"),
            "foreshadowing": _as_list_str(chapter_data.get("foreshadowing"), "foreshadowing"),
            "pov_character": _as_str(chapter_data.get("pov_character"), "pov_character"),
        }

    @staticmethod
    def _looks_like_chapter_outline(obj: dict) -> bool:
        """[5.5] 校验 dict 是否疑似章节大纲对象,用于 JSON 流式恢复时过滤嵌套字典

        判断标准: 至少包含 chapter_number 字段,或者同时包含 title 与
        以下任一关键字段: key_points / characters / settings / conflicts。
        这样可以排除 character_goals / foreshadowing 等嵌套结构被误捕为章节。
        """
        if not isinstance(obj, dict):
            return False
        # 优先信号: chapter_number 字段存在(雪花法/数据结构强约束)
        if "chapter_number" in obj:
            return True
        # 次级信号: 必须有 title 且至少一个章节关键字段
        if "title" not in obj:
            return False
        chapter_keys = {"key_points", "characters", "settings", "conflicts"}
        return any(k in obj for k in chapter_keys)

    def _merge_list_unique(self, target_list: list, source_list: list):
        """将 source_list 中的唯一元素添加到 target_list 中"""
        existing_elements_set = set(self._get_hashable_item(i) for i in target_list)
        for item in source_list:
            hashable_item = self._get_hashable_item(item)
            if hashable_item not in existing_elements_set:
                target_list.append(item)
                existing_elements_set.add(hashable_item)

    def _load_outline(self):
        """加载大纲文件，构建位置对齐的稀疏列表

        约定: ``self.chapter_outlines[i]`` 对应 chapter_number = i+1。
        - 缺失槽位填 None，保证按 chapter_num-1 索引访问安全；
        - 重复 chapter_number 仅保留**首次出现**版本，跳过后续重复条目；
        - len(self.chapter_outlines) == max(chapter_number)，与 target_chapters 比较时语义一致。
        """
        outline_file = os.path.join(self.output_dir, "outline.json")
        outline_data = load_json_file(outline_file, default_value=[])

        if not outline_data:
            logging.info("未找到大纲文件或文件为空。")
            self.chapter_outlines = []
            return

        # 处理可能的旧格式（包含元数据）和新格式（仅含章节列表）
        chapters_list = outline_data.get("chapters", outline_data) if isinstance(outline_data, dict) else outline_data
        if not isinstance(chapters_list, list):
            logging.error("Unrecognized outline file format, should be a list or dict with 'chapters' key.")
            self.chapter_outlines = []
            return

        # 阶段1：解析为 ChapterOutline 对象，按 chapter_number 去重（保留首次）
        seen_nums: set = set()
        loaded_outlines: List[ChapterOutline] = []
        duplicate_skipped = 0
        for idx, chapter_data in enumerate(chapters_list):
            if not isinstance(chapter_data, dict):
                logging.warning(f"加载大纲时跳过非字典条目 index={idx}: {chapter_data}")
                continue
            try:
                outline = ChapterOutline(**chapter_data)
            except TypeError as e:
                logging.warning(f"加载大纲时，第 {idx+1} 个章节字段不匹配或类型错误: {e} - 数据: {chapter_data} - 已跳过")
                continue
            except Exception as e:
                logging.warning(f"Error loading outline chapter {idx+1}: {e} - Data: {chapter_data} - Skipped")
                continue

            if outline.chapter_number in seen_nums:
                duplicate_skipped += 1
                logging.warning(
                    f"加载大纲时检测到重复 chapter_number={outline.chapter_number} (file index={idx})，"
                    f"已跳过（保留首次出现版本）"
                )
                continue
            seen_nums.add(outline.chapter_number)
            loaded_outlines.append(outline)

        # 阶段2：构建位置对齐的稀疏列表
        if not loaded_outlines:
            self.chapter_outlines = []
            logging.info("Loaded 0 valid chapter outlines from file")
            return

        max_num = max(o.chapter_number for o in loaded_outlines)
        positioned: List[Optional[ChapterOutline]] = [None] * max_num
        for o in loaded_outlines:
            if 1 <= o.chapter_number <= max_num:
                positioned[o.chapter_number - 1] = o
        self.chapter_outlines = positioned

        valid_count = sum(1 for o in self.chapter_outlines if o is not None)
        none_count = max_num - valid_count
        if duplicate_skipped or none_count:
            logging.warning(
                f"大纲加载完成：{valid_count} 章有效 / {none_count} 个空槽 / "
                f"max_chapter_number={max_num}"
                + (f"，跳过 {duplicate_skipped} 个重复条目" if duplicate_skipped else "")
            )
        logging.info(f"Loaded {valid_count} valid chapter outlines from file")

    def _save_outline(self) -> bool:
        """保存大纲到文件

        防御性约定：
        - None 槽位跳过（保留稀疏列表的位置语义）；
        - 同一 chapter_number 若意外重复，仅保留**首次出现**版本（与 _load_outline 一致）；
        - 写入按 chapter_number 升序，便于人工审阅与外部工具消费。
        """
        outline_file = os.path.join(self.output_dir, "outline.json")
        try:
            outline_data = []
            seen_nums: set = set()
            duplicate_skipped = 0

            for outline in self.chapter_outlines:
                if outline is None:
                    continue

                if not isinstance(outline, ChapterOutline):
                    logging.warning(f"尝试保存非 ChapterOutline 对象: {type(outline)} - {outline}")
                    continue

                if outline.chapter_number in seen_nums:
                    duplicate_skipped += 1
                    logging.warning(
                        f"保存大纲时检测到内存中重复 chapter_number={outline.chapter_number}，"
                        f"已跳过后续重复（保留首次）"
                    )
                    continue
                seen_nums.add(outline.chapter_number)

                outline_dict = {
                    "chapter_number": outline.chapter_number,
                    "title": outline.title,
                    "key_points": outline.key_points,
                    "characters": outline.characters,
                    "settings": outline.settings,
                    "conflicts": outline.conflicts,
                }
                # 保存扩展字段（仅当非空时写入，保持向后兼容）
                if outline.emotion_tone:
                    outline_dict["emotion_tone"] = outline.emotion_tone
                if outline.character_goals:
                    outline_dict["character_goals"] = outline.character_goals
                if outline.scene_sequence:
                    outline_dict["scene_sequence"] = outline.scene_sequence
                if outline.foreshadowing:
                    outline_dict["foreshadowing"] = outline.foreshadowing
                if outline.pov_character:
                    outline_dict["pov_character"] = outline.pov_character
                outline_data.append(outline_dict)

            # 按 chapter_number 升序输出
            outline_data.sort(key=lambda d: d["chapter_number"])

            if not outline_data:
                logging.warning("没有有效的大纲数据可以保存。")
                return False

            logging.info(
                f"尝试保存 {len(outline_data)} 章大纲到 {outline_file}"
                + (f"（跳过 {duplicate_skipped} 个内存重复）" if duplicate_skipped else "")
            )
            if outline_data:
                logging.info(f"即将保存的大纲前5章示例: {outline_data[:5]}")

            return save_json_file(outline_file, outline_data)
        except Exception as e:
            logging.error(f"保存大纲文件时出错: {str(e)}", exc_info=True)
            return False

    def _generate_core_seed(self) -> str:
        """生成或加载故事核心种子（雪花写作法步骤1：一句话概括）

        如果 core_seed.txt 已存在则直接复用，否则调用模型生成。

        Returns:
            核心种子文本，失败返回空字符串
        """
        core_seed_file = os.path.join(self.output_dir, "core_seed.txt")

        # 如果已存在则复用
        if os.path.exists(core_seed_file):
            try:
                with open(core_seed_file, 'r', encoding='utf-8') as f:
                    seed = f.read().strip()
                if seed:
                    logging.info(f"复用已有核心种子：{seed[:80]}...")
                    return seed
            except Exception as e:
                logging.warning(f"读取核心种子文件失败: {e}")

        # 从配置中提取参数
        novel_config = self.config.novel_config if hasattr(self.config, 'novel_config') else {}
        topic = novel_config.get("theme", "")
        genre = novel_config.get("type", "")
        number_of_chapters = self.config.generator_config.get("target_chapters", 100) if hasattr(self.config, 'generator_config') else 100
        word_number = novel_config.get("chapter_length", 3000)

        if not topic or not genre:
            logging.warning("缺少 theme 或 type 配置，跳过核心种子生成")
            return ""

        prompt = get_core_seed_prompt(topic, genre, number_of_chapters, word_number)
        logging.info("正在生成故事核心种子（雪花写作法步骤1）...")

        try:
            seed = self.outline_model.generate(prompt)
            if seed and seed.strip():
                seed = seed.strip()
                # 持久化
                with open(core_seed_file, 'w', encoding='utf-8') as f:
                    f.write(seed)
                logging.info(f"核心种子生成成功：{seed[:80]}...")
                return seed
            else:
                logging.warning("核心种子生成结果为空")
                return ""
        except Exception as e:
            logging.error(f"核心种子生成失败: {e}")
            return ""

    def _wait_retry_delay(self, delay_seconds: float) -> bool:
        """等待重试间隔，期间持续响应取消信号。"""
        remaining = max(0.0, float(delay_seconds))
        poll_interval = 0.2

        while remaining > 0:
            if self.cancel_checker and self.cancel_checker():
                logging.info("重试等待期间收到取消信号，中止后续重试。")
                return False

            sleep_time = min(poll_interval, remaining)
            time.sleep(sleep_time)
            remaining -= sleep_time

            if self.cancel_checker and self.cancel_checker():
                logging.info("重试等待期间收到取消信号，中止后续重试。")
                return False

        return True

    def generate_outline(self, novel_type: str, theme: str, style: str,
                        mode: str = 'replace', replace_range: Tuple[int, int] = None,
                        extra_prompt: Optional[str] = None,
                        force_regenerate: bool = False) -> bool:
        """生成指定范围的章节大纲

        当批次生成失败时，会自动重试。重试次数由配置项
        outline_batch_max_retries 控制，表示总共最多尝试次数，默认 3 次。

        Args:
            force_regenerate: 强制重生成。若为 True，会先清空 replace_range 范围内已有大纲，
                              避免子批次跳过逻辑（修复 2）误以为该范围已成功而跳过。
        """
        try:
            if mode != 'replace' or not replace_range:
                logging.error(f"不支持的生成模式 '{mode}' 或缺少章节范围 'replace_range'")
                return False

            start_chapter, end_chapter = replace_range
            if start_chapter < 1 or end_chapter < start_chapter:
                logging.error(f"无效的章节范围: start={start_chapter}, end={end_chapter}")
                return False

            total_chapters_to_generate = end_chapter - start_chapter + 1
            # 确保大纲列表至少有 end_chapter 的长度，如果不够则填充 None 或空 ChapterOutline
            # 这对于替换逻辑很重要
            if len(self.chapter_outlines) < end_chapter:
                self.chapter_outlines.extend([None] * (end_chapter - len(self.chapter_outlines)))
                logging.info(f"扩展大纲列表以容纳目标章节 {end_chapter}")

            # 强制重生成：清空目标范围的旧大纲，让子批次跳过逻辑（修复 2）失效
            if force_regenerate:
                cleared = 0
                for idx in range(start_chapter - 1, end_chapter):
                    if self.chapter_outlines[idx] is not None:
                        self.chapter_outlines[idx] = None
                        cleared += 1
                logging.info(
                    f"强制重生成模式已启用，已清空章节 {start_chapter}-{end_chapter} 范围内 {cleared} 章旧大纲"
                )

            batch_size = self.config.generation_config.get("outline_batch_size", 100)  # 主批次大小，支持超长大纲
            raw_total_attempts = self.config.generation_config.get("outline_batch_max_retries", 3)
            raw_retry_delay = self.config.generation_config.get("outline_batch_retry_delay", 5)

            try:
                total_attempts = max(1, int(raw_total_attempts))
            except (TypeError, ValueError):
                logging.warning(
                    f"无效的 outline_batch_max_retries 配置: {raw_total_attempts}，将回退到默认值 3。"
                )
                total_attempts = 3

            try:
                batch_retry_delay = max(0.0, float(raw_retry_delay))
            except (TypeError, ValueError):
                logging.warning(
                    f"无效的 outline_batch_retry_delay 配置: {raw_retry_delay}，将回退到默认值 5 秒。"
                )
                batch_retry_delay = 5.0

            successful_outlines_in_run = [] # 存储本次运行成功生成的

            num_batches = (total_chapters_to_generate + batch_size - 1) // batch_size
            all_batches_successful = True # 跟踪所有批次是否都成功
            for batch_idx in range(num_batches):
                # 检查取消信号
                if self.cancel_checker and self.cancel_checker():
                    logging.info("大纲生成收到取消信号，中止。")
                    self._save_outline()  # 保存已生成的部分
                    raise InterruptedError("用户取消大纲生成")

                batch_start_num = start_chapter + (batch_idx * batch_size)
                # 确保批次结束不超过总的结束章节
                batch_end_num = min(batch_start_num + batch_size - 1, end_chapter)
                
                batch_success = False
                last_error_msg = ""
                for attempt_idx in range(total_attempts):
                    attempt_no = attempt_idx + 1
                    # 重试前检查取消信号
                    if self.cancel_checker and self.cancel_checker():
                        logging.info("大纲批次重试前收到取消信号，中止。")
                        self._save_outline()
                        raise InterruptedError("用户取消大纲生成")

                    batch_success = self._generate_batch(batch_start_num, batch_end_num,
                                                        novel_type, theme, style, extra_prompt, successful_outlines_in_run)
                    
                    if batch_success:
                        logging.info(
                            f"批次 {batch_idx + 1} (章节 {batch_start_num}-{batch_end_num}) "
                            f"在第 {attempt_no}/{total_attempts} 次尝试成功，正在保存当前大纲..."
                        )
                        if not self._save_outline():
                             logging.error(f"在批次 {batch_idx + 1} 后保存大纲失败。")
                        break  # 批次成功，跳出重试循环

                    last_error_msg = (
                        f"批次 {batch_idx + 1} (章节 {batch_start_num}-{batch_end_num}) "
                        f"第 {attempt_no}/{total_attempts} 次尝试失败"
                    )
                    if attempt_no < total_attempts:
                        logging.warning(
                            f"{last_error_msg}，将在 {batch_retry_delay:g} 秒后进行下一次尝试。"
                        )
                        if not self._wait_retry_delay(batch_retry_delay):
                            self._save_outline()
                            return False
                    else:
                        logging.error(
                            f"批次 {batch_idx + 1} (章节 {batch_start_num}-{batch_end_num}) "
                            f"在 {total_attempts} 次尝试后仍不成功，终止大纲生成。"
                        )

                if not batch_success:
                    # 保存部分成功的结果
                    self._save_outline()
                    all_batches_successful = False
                    break  # 重试耗尽后停止

            logging.info(f"所有批次的大纲生成尝试完成，本次运行共生成 {len(successful_outlines_in_run)} 章")

            # ---- 缺失章节补生成 ----
            missing_chapters = [
                start_chapter + i
                for i in range(end_chapter - start_chapter + 1)
                if self.chapter_outlines[start_chapter - 1 + i] is None
            ]

            if missing_chapters:
                # [5.1] DRY 整合: 调用 patch_missing_chapters 单一实现,
                # 不再在此处复制粘贴重试循环 / 一致性检查 / 落盘逻辑
                logging.info(
                    f"检测到 {len(missing_chapters)} 个缺失章节: {missing_chapters},"
                    f"调用 patch_missing_chapters 补齐"
                )
                succeeded, still_missing = self.patch_missing_chapters(
                    missing_chapters,
                    novel_type=novel_type,
                    theme=theme,
                    style=style,
                    extra_prompt=extra_prompt,
                )
                if still_missing:
                    logging.warning(
                        f"补生成结束,仍有 {len(still_missing)} 个章节缺失: {still_missing}。"
                        f"已保存当前结果,ContentGenerator 可能会因大纲不连续而拒绝生成。"
                    )
                    all_batches_successful = False
                else:
                    logging.info(f"所有 {len(succeeded)} 个缺失章节已补生成完毕!")
                    if not all_batches_successful:
                        all_batches_successful = True

            return all_batches_successful

        except InterruptedError:
            logging.info("大纲生成已取消。")
            return False
        except Exception as e:
            logging.error(f"生成大纲主流程发生未预期错误：{str(e)}", exc_info=True)
            return False

    def _generate_batch(self, batch_start_num: int, batch_end_num: int, 
                       novel_type: str, theme: str, style: str,
                       extra_prompt: Optional[str], 
                       successful_outlines_in_run: List[ChapterOutline]) -> bool:
        """生成一个批次的大纲"""
        current_batch_size = batch_end_num - batch_start_num + 1
        logging.info(f"开始生成第 {batch_start_num} 到 {batch_end_num} 章的大纲（共 {current_batch_size} 章）")

        # 获取当前批次的上下文
        existing_context = self._get_context_for_batch(batch_start_num)
        
        # 获取前文大纲用于一致性检查
        previous_outlines = [o for o in self.chapter_outlines[:batch_start_num-1] if isinstance(o, ChapterOutline)]

        # 生成或加载核心种子（雪花写作法步骤1）
        core_seed = self._generate_core_seed()

        # 抽取未回收伏笔，注入 prompt 以强制本批次处理
        pending_foreshadowing: List[str] = []
        try:
            plot_dev = (
                self.sync_info.get("剧情发展", {})
                if isinstance(self.sync_info, dict) else {}
            )
            raw_fs = plot_dev.get("悬念伏笔", []) if isinstance(plot_dev, dict) else []
            raw_resolved = plot_dev.get("已回收伏笔", []) if isinstance(plot_dev, dict) else []

            def _to_text(item) -> str:
                if isinstance(item, str):
                    return item
                if isinstance(item, dict):
                    return str(
                        item.get("内容") or item.get("描述") or item.get("名称")
                        or item.get("content") or item.get("desc") or item
                    )
                return str(item)

            # 构建已回收集合用于差集过滤，避免把历史已回收伏笔再次当作未回收注入
            resolved_set = {_to_text(r) for r in raw_resolved if r}

            seen = set()
            for item in raw_fs:
                text = _to_text(item).strip()
                if not text or text in resolved_set or text in seen:
                    continue
                seen.add(text)
                pending_foreshadowing.append(text)

            # 取最早埋设的若干条，避免 prompt 过长
            pending_foreshadowing = pending_foreshadowing[:10]
        except Exception as e:
            logging.warning(f"抽取未回收伏笔失败，忽略此次注入: {e}")
            pending_foreshadowing = []

        # 生成提示词
        prompt = get_outline_prompt(
            novel_type=novel_type,
            theme=theme,
            style=style,
            current_start_chapter_num=batch_start_num,
            current_batch_size=current_batch_size,
            existing_context=existing_context,
            extra_prompt=extra_prompt,
            novel_config=self.config.novel_config,
            total_chapters=self.config.generator_config.get("target_chapters", 0),
            current_end_chapter_num=batch_end_num,
            core_seed=core_seed,
            pending_foreshadowing=pending_foreshadowing,
            arc_config=self.config.novel_config.get("arc_config"),
        )

        # 新增：打印大纲生成提示词长度
        logging.info(f"本次大纲生成prompt长度为: {len(prompt)} 字符")

        batch_size = self.config.generation_config.get("batch_size", 5)  # 每次API调用生成的章节数

        if current_batch_size > batch_size:
            logging.info(f"批次大小 ({current_batch_size}) 超过限制 ({batch_size})，将分批处理")
            success = True
            for sub_batch_start in range(batch_start_num, batch_end_num + 1, batch_size):
                # 检查取消信号
                if self.cancel_checker and self.cancel_checker():
                    logging.info("大纲子批次生成收到取消信号，中止。")
                    raise InterruptedError("用户取消大纲生成")
                sub_batch_end = min(sub_batch_start + batch_size - 1, batch_end_num)

                # ----- 修复 2：跳过已全部生成有效大纲的子批次 -----
                # 这避免了"整批失败重试导致已成功子批被反复覆盖"的浪费。
                sub_existing = self.chapter_outlines[sub_batch_start - 1:sub_batch_end]
                if (len(sub_existing) == (sub_batch_end - sub_batch_start + 1)
                        and all(isinstance(o, ChapterOutline) for o in sub_existing)):
                    logging.info(
                        f"子批次 {sub_batch_start}-{sub_batch_end} 已存在有效大纲，跳过重生成"
                    )
                    # 仍要纳入本次 run 的成功记录，便于上下文与统计
                    for o in sub_existing:
                        if o not in successful_outlines_in_run:
                            successful_outlines_in_run.append(o)
                    continue

                if not self._generate_batch(sub_batch_start, sub_batch_end, novel_type, theme, style, extra_prompt, successful_outlines_in_run):
                    success = False
                    # 不再 break：继续尝试后续子批次，避免一旦某子批失败就阻塞后面所有子批
                    # 后续未生成的章节会保持 None，由外层 generate_outline 的"补生成"流程兜底
                    logging.warning(
                        f"子批次 {sub_batch_start}-{sub_batch_end} 失败，继续尝试后续子批次"
                    )
            return success

        try:
            logging.info(f"调用模型生成大纲...") 
            
            response = self.outline_model.generate(prompt, max_tokens=self.config.generation_config.get("max_tokens"))
            if not response:
                raise Exception("模型返回为空")

            outline_data = self._parse_model_response(response)
            if not outline_data:
                raise Exception("解析模型响应失败")

            # ----- 按章节号匹配模型返回内容（修复 4：替代纯位置映射）-----
            # 优先使用模型返回的 chapter_number 字段；没有合法编号的项按顺序回填到剩余空位
            returned_by_num: Dict[int, Dict] = {}
            unindexed_items: List[Dict] = []
            for item in outline_data:
                if not isinstance(item, dict):
                    continue
                raw_num = item.get('chapter_number')
                ch_num: Optional[int] = None
                if isinstance(raw_num, int):
                    ch_num = raw_num
                elif isinstance(raw_num, str) and raw_num.strip().isdigit():
                    ch_num = int(raw_num.strip())

                if (ch_num is not None
                        and batch_start_num <= ch_num <= batch_end_num
                        and ch_num not in returned_by_num):
                    returned_by_num[ch_num] = item
                else:
                    unindexed_items.append(item)

            if unindexed_items:
                empty_slots = [n for n in range(batch_start_num, batch_end_num + 1) if n not in returned_by_num]
                for item, slot in zip(unindexed_items, empty_slots):
                    returned_by_num[slot] = item
                if len(unindexed_items) > len(empty_slots):
                    logging.warning(
                        f"模型返回 {len(unindexed_items)} 个无编号项，"
                        f"超出本批次 {len(empty_slots)} 个空位，丢弃多余 {len(unindexed_items) - len(empty_slots)} 项"
                    )

            new_outlines_batch: List[Optional[ChapterOutline]] = []
            valid_count = 0
            none_count = 0
            consistency_fail_count = 0
            construct_fail_count = 0
            missing_from_model = 0

            for expected_chapter_num in range(batch_start_num, batch_end_num + 1):
                chapter_data = returned_by_num.get(expected_chapter_num)
                if chapter_data is None:
                    logging.warning(f"模型遗漏第 {expected_chapter_num} 章，标记为 None 占位")
                    new_outlines_batch.append(None)
                    none_count += 1
                    missing_from_model += 1
                    continue

                try:
                    new_outline = ChapterOutline(
                        chapter_number=expected_chapter_num,
                        title=chapter_data.get('title', f'第{expected_chapter_num}章'),
                        key_points=chapter_data.get('key_points', []),
                        characters=chapter_data.get('characters', []),
                        settings=chapter_data.get('settings', []),
                        conflicts=chapter_data.get('conflicts', []),
                        # [H5] 透传雪花写作法扩展字段(经类型归一化)
                        **self._normalize_extended_outline_fields(chapter_data),
                    )

                    if self._check_outline_consistency(new_outline, previous_outlines):
                        new_outlines_batch.append(new_outline)
                        valid_count += 1
                        previous_outlines.append(new_outline)
                    else:
                        logging.warning(f"第 {expected_chapter_num} 章大纲未通过一致性检查")
                        new_outlines_batch.append(None)
                        none_count += 1
                        consistency_fail_count += 1

                except Exception as e:
                    logging.error(f"处理章节 {expected_chapter_num} 大纲时出错: {str(e)}")
                    new_outlines_batch.append(None)
                    none_count += 1
                    construct_fail_count += 1

            # 输出详细的失败原因统计
            if none_count > 0:
                logging.warning(
                    f"批次 {batch_start_num}-{batch_end_num} 失败统计: "
                    f"一致性检查失败={consistency_fail_count}, "
                    f"数据构造异常={construct_fail_count}, "
                    f"模型返回不足={missing_from_model}"
                )

            start_index = batch_start_num - 1
            end_index = batch_end_num
            self.chapter_outlines[start_index:end_index] = new_outlines_batch
            
            if not self._save_outline():
                logging.error(f"在生成批次 {batch_start_num}-{batch_end_num} 后保存大纲失败。")
                return False 

            successful_outlines_in_run.extend([o for o in new_outlines_batch if isinstance(o, ChapterOutline)])
            logging.info(f"outline模式不触发同步信息更新，仅保存大纲")

            if valid_count < current_batch_size:
                logging.warning(
                    f"批次生成的大纲中只有 {valid_count}/{current_batch_size} 个通过验证"
                    f"（含 {none_count} 个空位），"
                    f"如需提高质量，可尝试减小每批生成章节数（当前: {current_batch_size}）。"
                )

            # 当有效章节低于“至少半数（奇数向上取整）”时视为批次失败，触发上层重试
            required_valid_count = max(1, (current_batch_size + 1) // 2)
            if valid_count < required_valid_count:
                logging.warning(
                    f"有效大纲数 ({valid_count}) 低于批次成功阈值 "
                    f"({required_valid_count}/{current_batch_size})，"
                    f"视为批次失败以触发自动重试。"
                )
                return False

            return True

        except Exception as e:
            logging.error(f"生成批次大纲时出错: {str(e)}", exc_info=True)
            self._save_outline()
            return False

    def patch_missing_chapters(
        self,
        missing_chapters: List[int],
        novel_type: str,
        theme: str,
        style: str,
        extra_prompt: Optional[str] = None,
        max_rounds: Optional[int] = None,
        retry_delay: Optional[float] = None,
    ) -> Tuple[List[int], List[int]]:
        """补齐 outline.json 中已知缺失的章节（不触碰其它条目）。

        与 generate_outline(force_regenerate=True, replace_range=(1, N)) 不同，
        本方法只针对调用方传入的稀疏章节号清单逐章补生成，相邻已存在大纲条目原样保留，
        不会改写已有正文对应的大纲。

        复用 _generate_single_chapter_outline 的单章生成器 + 多轮重试 + 每章成功即保存
        的现有模式（与 generate_outline 末尾的 [补生成] 逻辑同源），保证：
          - 每章生成时使用 ``_get_context_for_batch`` 拉取前文上下文，相邻章节作为锚点；
          - 每补一章立即 _save_outline()，崩溃时已补章节不会丢；
          - 一致性检查不通过时仍记为失败，避免将不兼容大纲写入。

        Args:
            missing_chapters: 待补章节号列表（1-based），调用方通常从 ContentGenerator
                ``_outline_discontinuous`` 直接转入。
            max_rounds: 最大补洞轮数，None 时回退到 generation_config["outline_gap_max_retries"]。
            retry_delay: 单章失败后退避秒数，None 时回退到 ["outline_gap_retry_delay"]。

        Returns:
            (succeeded, still_missing): 已补齐章节号列表 与 经过 max_rounds 仍未补上的章节号列表。
        """
        # 入参清洗：去重 + 排序 + 过滤越界
        if not missing_chapters:
            return [], []
        deduped = sorted({int(n) for n in missing_chapters if isinstance(n, int) and n >= 1})
        if not deduped:
            return [], []

        # 配置回退
        gen_cfg = getattr(self.config, "generation_config", {}) or {}
        if max_rounds is None:
            try:
                max_rounds = max(1, int(gen_cfg.get("outline_gap_max_retries", 2)))
            except (TypeError, ValueError):
                max_rounds = 2
        if retry_delay is None:
            try:
                retry_delay = max(0.0, float(gen_cfg.get("outline_gap_retry_delay", 3)))
            except (TypeError, ValueError):
                retry_delay = 3.0

        # 确保 outline_list 至少能放下最大目标章节
        target_max = max(deduped)
        if len(self.chapter_outlines) < target_max:
            self.chapter_outlines.extend([None] * (target_max - len(self.chapter_outlines)))
            logging.info(f"[补洞] 扩展大纲列表至 {target_max} 以容纳目标章节")

        pending = list(deduped)
        succeeded: List[int] = []

        logging.info(
            f"[补洞] 开始补齐 {len(pending)} 个缺失章节（最多 {max_rounds} 轮）: {pending}"
        )

        for round_idx in range(max_rounds):
            if not pending:
                break
            if self.cancel_checker and self.cancel_checker():
                logging.info("[补洞] 收到取消信号，中止。")
                self._save_outline()
                raise InterruptedError("用户取消大纲补洞")

            round_no = round_idx + 1
            logging.info(f"[补洞] 第 {round_no}/{max_rounds} 轮，待补: {pending}")

            for ch_num in list(pending):
                if self.cancel_checker and self.cancel_checker():
                    logging.info("[补洞] 收到取消信号，中止。")
                    self._save_outline()
                    raise InterruptedError("用户取消大纲补洞")

                # 已被早前轮补上（一致性检查通过后写入了对应槽位）→ 直接出列
                slot = self.chapter_outlines[ch_num - 1] if ch_num - 1 < len(self.chapter_outlines) else None
                if isinstance(slot, ChapterOutline) and slot.chapter_number == ch_num:
                    pending.remove(ch_num)
                    if ch_num not in succeeded:
                        succeeded.append(ch_num)
                    continue

                ok = self._generate_single_chapter_outline(
                    ch_num, novel_type, theme, style, extra_prompt
                )
                if ok:
                    pending.remove(ch_num)
                    succeeded.append(ch_num)
                    self._save_outline()
                elif retry_delay > 0:
                    if not self._wait_retry_delay(retry_delay):
                        # 等待期间收到取消
                        self._save_outline()
                        return sorted(succeeded), sorted(pending)

            if pending:
                logging.warning(
                    f"[补洞] 第 {round_no} 轮结束，仍剩 {len(pending)} 个未补: {pending}"
                )

        # 最后再 save 一次，覆盖最后一轮成功的章节（_generate_single_chapter_outline
        # 内部不 save，只有调用方落盘——这里收尾）
        self._save_outline()

        if pending:
            logging.error(
                f"[补洞] 完成 {max_rounds} 轮后仍有 {len(pending)} 个章节未补齐: {pending}"
            )
        else:
            logging.info(f"[补洞] 全部 {len(succeeded)} 个章节补齐完成: {sorted(succeeded)}")

        return sorted(succeeded), sorted(pending)

    def _generate_single_chapter_outline(
        self,
        chapter_num: int,
        novel_type: str,
        theme: str,
        style: str,
        extra_prompt: Optional[str] = None,
    ) -> bool:
        """为单个缺失章节生成大纲（用于批次完成后的补生成）

        成功时将结果填入 self.chapter_outlines[chapter_num-1]，失败则保持 None。
        """
        try:
            if self.cancel_checker and self.cancel_checker():
                raise InterruptedError("用户取消大纲生成")

            existing_context = self._get_context_for_batch(chapter_num)
            previous_outlines = [
                o for o in self.chapter_outlines[:chapter_num - 1]
                if isinstance(o, ChapterOutline)
            ]

            core_seed = self._generate_core_seed()

            prompt = get_outline_prompt(
                novel_type=novel_type,
                theme=theme,
                style=style,
                current_start_chapter_num=chapter_num,
                current_batch_size=1,
                existing_context=existing_context,
                extra_prompt=extra_prompt,
                novel_config=self.config.novel_config,
                total_chapters=self.config.generator_config.get("target_chapters", 0),
                current_end_chapter_num=chapter_num,
                core_seed=core_seed,
                arc_config=self.config.novel_config.get("arc_config"),
            )

            logging.info(f"[补生成] 第 {chapter_num} 章大纲 prompt 长度: {len(prompt)} 字符")

            response = self.outline_model.generate(
                prompt,
                max_tokens=self.config.generation_config.get("max_tokens"),
            )
            if not response:
                logging.warning(f"[补生成] 第 {chapter_num} 章模型返回为空")
                return False

            outline_data = self._parse_model_response(response)
            if not outline_data:
                logging.warning(f"[补生成] 第 {chapter_num} 章解析模型响应失败")
                return False

            # 模型可能返回列表或单个对象
            if isinstance(outline_data, list):
                if len(outline_data) == 0:
                    logging.warning(f"[补生成] 第 {chapter_num} 章模型返回空列表")
                    return False
                chapter_data = outline_data[0]
            else:
                chapter_data = outline_data

            new_outline = ChapterOutline(
                chapter_number=chapter_num,
                title=chapter_data.get("title", f"第{chapter_num}章"),
                key_points=chapter_data.get("key_points", []),
                characters=chapter_data.get("characters", []),
                settings=chapter_data.get("settings", []),
                conflicts=chapter_data.get("conflicts", []),
                # [H5] 透传雪花写作法扩展字段(经类型归一化)
                **self._normalize_extended_outline_fields(chapter_data),
            )

            if not self._check_outline_consistency(new_outline, previous_outlines):
                logging.warning(f"[补生成] 第 {chapter_num} 章大纲未通过一致性检查")
                return False

            self.chapter_outlines[chapter_num - 1] = new_outline
            logging.info(f"[补生成] 第 {chapter_num} 章大纲生成成功: {new_outline.title}")
            return True

        except InterruptedError:
            raise
        except Exception as e:
            logging.error(f"[补生成] 第 {chapter_num} 章大纲生成异常: {e}", exc_info=True)
            return False

    def _parse_model_response(self, response: str):
        """解析模型返回的 JSON 响应，采用渐进式解析策略：优先直接解析，逐步降级清理"""
        import json
        import re

        def _strip_markdown_wrapper(text: str) -> str:
            """去除 markdown 代码块包裹"""
            text = text.strip()
            if text.startswith('```'):
                text = re.sub(r'^```[a-zA-Z]*\n?', '', text)
                text = text.strip('`\n')
            return text

        def _extract_json_boundaries(text: str) -> str:
            """提取最外层的 JSON 数组或对象"""
            json_start_square = text.find('[')
            json_end_square = text.rfind(']') + 1
            json_start_curly = text.find('{')
            json_end_curly = text.rfind('}') + 1

            if json_start_square != -1 and json_end_square > json_start_square and \
               (json_start_curly == -1 or json_start_square < json_start_curly):
                return text[json_start_square:json_end_square]
            elif json_start_curly != -1 and json_end_curly > json_start_curly:
                return text[json_start_curly:json_end_curly]
            return text

        try:
            cleaned = _strip_markdown_wrapper(response)

            # === 策略1：直接解析（最安全，无数据损失） ===
            try:
                extracted = _extract_json_boundaries(cleaned)
                result = json.loads(extracted)
                logging.info("JSON 解析成功（直接解析）")
                return result
            except json.JSONDecodeError:
                pass

            # === 策略2：仅修复常见的尾部逗号和多余逗号（低风险清理） ===
            try:
                light_cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)  # 去尾逗号
                light_cleaned = re.sub(r',+', ',', light_cleaned)  # 去重复逗号
                extracted = _extract_json_boundaries(light_cleaned)
                result = json.loads(extracted)
                logging.info("JSON 解析成功（轻度清理）")
                return result
            except json.JSONDecodeError:
                pass

            # === 策略3：转义字符串内容后移除非字符串中的换行符（中等风险） ===
            try:
                def escape_inner_content_for_json(match):
                    inner_content = match.group(0)[1:-1]
                    escaped_inner_content = json.dumps(inner_content)[1:-1]
                    return f'"{escaped_inner_content}"'

                escaped = re.sub(r'(\"[^\"\\\\]*(?:\\\\.[^\"\\\\]*)*\")', escape_inner_content_for_json, cleaned)
                # 现在字符串内的换行已被转义为 \\n，可以安全移除原始换行
                flattened = escaped.replace('\n', ' ').replace('\r', '')
                flattened = re.sub(r',+', ',', flattened)
                flattened = re.sub(r',\s*([}\]])', r'\1', flattened)
                extracted = _extract_json_boundaries(flattened)
                result = json.loads(extracted)
                logging.info("JSON 解析成功（转义+扁平化）")
                return result
            except json.JSONDecodeError:
                pass

            # === 策略4：最激进的清理（最后手段，可能有数据损失） ===
            try:
                aggressive_cleaned = cleaned.replace('\n', '').replace('\r', '')
                aggressive_cleaned = re.sub(r',+', ',', aggressive_cleaned)
                aggressive_cleaned = re.sub(r',\s*([}\]])', r'\1', aggressive_cleaned)
                aggressive_cleaned = re.sub(r'([}\]])\s*(?!,)(?=[\\[{\"-0123456789tfnal])', r'\1,', aggressive_cleaned)
                extracted = _extract_json_boundaries(aggressive_cleaned)
                result = json.loads(extracted)
                logging.warning("JSON 解析成功（激进清理模式），字符串内容中的换行符可能已丢失")
                return result
            except json.JSONDecodeError:
                pass

            # === 策略5：流式逐对象解析（修复中段语法损坏，最大限度回收有效章节）===
            # 当 LLM 输出在数组中段漏字符（如缺逗号、缺引号），整体解析必然失败。
            # 用 raw_decode 逐对象提取，跳过损坏的对象，保住其余有效数据。
            try:
                stream_cleaned = _strip_markdown_wrapper(response)
                # 定位数组开头
                arr_start = stream_cleaned.find('[')
                if arr_start == -1:
                    raise json.JSONDecodeError("未找到 JSON 数组起始 '['", stream_cleaned, 0)

                decoder = json.JSONDecoder()
                pos = arr_start + 1
                n = len(stream_cleaned)
                recovered: list = []
                skipped = 0
                while pos < n:
                    # 跳过分隔符与空白
                    while pos < n and stream_cleaned[pos] in ', \n\r\t':
                        pos += 1
                    if pos >= n:
                        break
                    # 遇到数组结束符 ']'
                    if stream_cleaned[pos] == ']':
                        break
                    # 必须从 '{' 开始一个对象，否则跳到下一个 '{'
                    if stream_cleaned[pos] != '{':
                        next_brace = stream_cleaned.find('{', pos)
                        if next_brace == -1:
                            break
                        pos = next_brace
                        continue
                    try:
                        obj, end = decoder.raw_decode(stream_cleaned, pos)
                        # [5.5] schema 校验:仅接受疑似章节对象,避免误捕嵌套字典
                        # (如 character_goals 也是 dict,但不是章节)
                        if isinstance(obj, dict) and self._looks_like_chapter_outline(obj):
                            recovered.append(obj)
                        elif isinstance(obj, dict):
                            # 是 dict 但不像章节 → 视为损坏跳过
                            skipped += 1
                        pos = end
                    except json.JSONDecodeError:
                        # 当前对象损坏，丢弃并跳到下一个 '{'
                        skipped += 1
                        next_brace = stream_cleaned.find('{', pos + 1)
                        if next_brace == -1:
                            break
                        pos = next_brace

                if recovered:
                    logging.warning(
                        f"JSON 解析成功（流式逐对象模式）：恢复 {len(recovered)} 个章节对象，"
                        f"丢弃 {skipped} 个损坏对象"
                    )
                    return recovered
                # 一个都没恢复到 → 让下面 fallback 报错
                raise json.JSONDecodeError("流式解析未恢复任何对象", stream_cleaned, 0)
            except json.JSONDecodeError as e:
                logging.error(f"所有 JSON 解析策略均失败: {e}\n原始内容前500字符: {response[:500]}...")
                return None

        except Exception as e:
            logging.error(f"_parse_model_response: 处理响应时出错: {e}")
            return None

    def _get_default_sync_info(self) -> dict:
        """获取默认的同步信息结构"""
        return {
            "世界观": {
                "世界背景": [],
                "阵营势力": [],
                "重要规则": [],
                "关键场所": []
            },
            "人物设定": {
                "人物信息": [],
                "人物关系": []
            },
            "剧情发展": {
                "主线梗概": "",
                "重要事件": [],
                "悬念伏笔": [],
                "已回收伏笔": [],
                "已解决冲突": [],
                "进行中冲突": []
            },
            "前情提要": [],
            "最后更新章节": 0,
            "最后更新时间": ""
        }

    def _load_sync_info(self) -> dict:
        """加载同步信息文件"""
        try:
            if os.path.exists(self.sync_info_file):
                with open(self.sync_info_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # 向后兼容：旧文件缺失 已回收伏笔 字段时补齐
                if isinstance(data, dict):
                    plot = data.setdefault("剧情发展", {})
                    if isinstance(plot, dict) and "已回收伏笔" not in plot:
                        plot["已回收伏笔"] = []
                return data
            return self._get_default_sync_info()
        except Exception as e:
            logging.error(f"加载同步信息文件时出错: {str(e)}", exc_info=True)
            return self._get_default_sync_info()

    def _save_sync_info(self) -> bool:
        """保存同步信息到文件"""
        try:
            with open(self.sync_info_file, 'w', encoding='utf-8') as f:
                json.dump(self.sync_info, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logging.error(f"保存同步信息文件时出错: {str(e)}", exc_info=True)
            return False

    def _update_sync_info(self, batch_start: int, batch_end: int, sync_model=None) -> bool:
        """更新同步信息"""
        try:
            # 获取本批次的章节内容
            batch_outlines = []
            for chapter_num in range(batch_start, batch_end + 1):
                if chapter_num - 1 < len(self.chapter_outlines):
                    outline = self.chapter_outlines[chapter_num - 1]
                    if outline:
                        batch_outlines.append(outline)

            if not batch_outlines:
                logging.warning("没有找到需要更新的章节大纲")
                return False

            # 构建章节内容文本
            chapter_texts = []
            for outline in batch_outlines:
                chapter_text = f"第{outline.chapter_number}章 {outline.title}\n"
                chapter_text += f"关键情节：{', '.join(outline.key_points)}\n"
                chapter_text += f"涉及角色：{', '.join(outline.characters)}\n"
                chapter_text += f"场景：{', '.join(outline.settings)}\n"
                chapter_text += f"冲突：{', '.join(outline.conflicts)}"
                chapter_texts.append(chapter_text)

            # 生成更新提示词
            prompt = get_sync_info_prompt(
                "\n\n".join(chapter_texts),
                json.dumps(self.sync_info, ensure_ascii=False),
                batch_end
            )

            # 使用指定的模型或默认使用outline_model
            model_to_use = sync_model if sync_model is not None else self.outline_model
            
            # 调用模型更新同步信息
            logging.info(f"调用模型更新同步信息...")
            
            # 尝试使用主要模型
            new_sync_info = self._try_model_generation(model_to_use, prompt, "主要模型")
            
            # 如果主要模型失败，尝试使用备用模型
            if not new_sync_info and hasattr(self, 'content_model'):
                logging.warning("主要模型失败，尝试使用备用模型...")
                new_sync_info = self._try_model_generation(self.content_model, prompt, "备用模型")
            
            # 如果所有模型都失败，使用降级方案
            if not new_sync_info:
                logging.error("所有模型都失败了，使用降级方案")
                return self._fallback_sync_info_update(batch_start, batch_end)
            
            try:
                # 1. 首先尝试直接解析
                updated_sync_info = json.loads(new_sync_info)
            except json.JSONDecodeError:
                # 2. 如果直接解析失败，尝试提取 JSON 部分
                json_start = new_sync_info.find('{')
                json_end = new_sync_info.rfind('}') + 1
                
                if json_start >= 0 and json_end > json_start:
                    json_content = new_sync_info[json_start:json_end]
                    try:
                        updated_sync_info = json.loads(json_content)
                    except json.JSONDecodeError as e:
                        logging.error(f"提取的 JSON 内容解析失败: {str(e)}")
                        # 保存原始输出以供调试
                        debug_file = os.path.join(os.path.dirname(self.sync_info_file), "sync_info_raw.txt")
                        with open(debug_file, 'w', encoding='utf-8') as f:
                            f.write(new_sync_info)
                        logging.info(f"已保存原始输出到 {debug_file} 以供调试")
                        return self._fallback_sync_info_update(batch_start, batch_end)
                else:
                    logging.error("无法在生成的内容中找到 JSON 格式数据")
                    return self._fallback_sync_info_update(batch_start, batch_end)
            
            # 3. 验证 JSON 结构
            required_keys = ["世界观", "人物设定", "剧情发展", "前情提要", "最后更新章节", "最后更新时间"]
            if not all(key in updated_sync_info for key in required_keys):
                logging.warning(f"模型返回的同步信息缺少一些必要顶层键: {[k for k in required_keys if k not in updated_sync_info]}")
            
            # 4. 合并新的同步信息到现有信息中
            
            # 世界观
            if "世界观" in updated_sync_info and isinstance(updated_sync_info["世界观"], dict):
                world_view_updates = updated_sync_info["世界观"]
                self.sync_info.setdefault("世界观", {}) # Ensure "世界观" exists in self.sync_info
                for key in ["世界背景", "阵营势力", "重要规则"]: # Exclude "关键场所" as it's handled in _check_outline_consistency
                    if key in world_view_updates and isinstance(world_view_updates[key], list):
                        self._merge_list_unique(self.sync_info["世界观"].setdefault(key, []), world_view_updates[key])

            # 人物设定
            if "人物设定" in updated_sync_info and isinstance(updated_sync_info["人物设定"], dict):
                character_updates = updated_sync_info["人物设定"]
                self.sync_info.setdefault("人物设定", {}) # Ensure "人物设定" exists
                # "人物信息" 已在 _check_outline_consistency 统一处理，此处不重复添加
                if "人物关系" in character_updates and isinstance(character_updates["人物关系"], list):
                    self._merge_list_unique(self.sync_info["人物设定"].setdefault("人物关系", []), character_updates["人物关系"])

            # 剧情发展
            if "剧情发展" in updated_sync_info and isinstance(updated_sync_info["剧情发展"], dict):
                plot_updates = updated_sync_info["剧情发展"]
                self.sync_info.setdefault("剧情发展", {}) # Ensure "剧情发展" exists
                # 主线梗概：如果模型返回了新的非空梗概，则更新（覆盖）
                if plot_updates.get("主线梗概"): # Check if it's not None or empty string
                    self.sync_info["剧情发展"]["主线梗概"] = plot_updates["主线梗概"]
                
                for key in ["重要事件", "悬念伏笔", "已回收伏笔", "已解决冲突", "进行中冲突"]:
                    if key in plot_updates and isinstance(plot_updates[key], list):
                        self._merge_list_unique(self.sync_info["剧情发展"].setdefault(key, []), plot_updates[key])
            
            # 前情提要
            if "前情提要" in updated_sync_info and isinstance(updated_sync_info["前情提要"], list):
                self._merge_list_unique(self.sync_info.setdefault("前情提要", []), updated_sync_info["前情提要"])

            # 最后更新章节和最后更新时间由内部逻辑设定，不依赖模型输出
            self.sync_info["最后更新章节"] = batch_end
            self.sync_info["最后更新时间"] = time.strftime("%Y-%m-%d %H:%M:%S")
            
            return self._save_sync_info()
            
        except Exception as e:
            logging.error(f"更新同步信息时出错: {str(e)}", exc_info=True)
            return self._fallback_sync_info_update(batch_start, batch_end)

    def _try_model_generation(self, model, prompt: str, model_name: str) -> str:
        """尝试使用指定模型生成内容"""
        max_retries = 3  # 每个模型的重试次数
        new_sync_info = None
        
        for attempt in range(max_retries):
            try:
                logging.info(f"使用{model_name}生成同步信息 (尝试 {attempt + 1}/{max_retries})")
                new_sync_info = model.generate(prompt)
                if new_sync_info:
                    logging.info(f"{model_name}生成成功")
                    break
                else:
                    logging.warning(f"{model_name}返回空的同步信息，尝试 {attempt + 1}/{max_retries}")
                    if attempt == max_retries - 1:
                        logging.warning(f"{model_name}返回空的同步信息")
                        return None
            except Exception as e:
                logging.error(f"{model_name}调用失败 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
                if attempt == max_retries - 1:
                    logging.error(f"{model_name}所有重试都失败了")
                    return None
                # 等待一段时间后重试
                time.sleep(10 * (attempt + 1))  # 递增等待时间
        
        return new_sync_info

    def _fallback_sync_info_update(self, batch_start: int, batch_end: int) -> bool:
        """降级方案：手动更新同步信息"""
        try:
            logging.info("使用降级方案更新同步信息")
            
            # 手动更新最后更新章节进度
            self.sync_info["最后更新章节"] = batch_end
            self.sync_info["最后更新时间"] = time.strftime("%Y-%m-%d %H:%M:%S")
            
            # 添加新的前情提要
            new_summary = f"第{batch_start}章到第{batch_end}章：完成了新章节的大纲生成"
            if "前情提要" not in self.sync_info:
                self.sync_info["前情提要"] = []
            self.sync_info["前情提要"].append(new_summary)
            
            # 添加新的重要事件
            if "剧情发展" not in self.sync_info:
                self.sync_info["剧情发展"] = {}
            if "重要事件" not in self.sync_info["剧情发展"]:
                self.sync_info["剧情发展"]["重要事件"] = []
            
            for chapter_num in range(batch_start, batch_end + 1):
                if chapter_num - 1 < len(self.chapter_outlines):
                    outline = self.chapter_outlines[chapter_num - 1]
                    if outline:
                        event = f"第{chapter_num}章：{outline.title}"
                        if event not in self.sync_info["剧情发展"]["重要事件"]:
                            self.sync_info["剧情发展"]["重要事件"].append(event)
            
            return self._save_sync_info()
            
        except Exception as e:
            logging.error(f"降级方案也失败了: {str(e)}", exc_info=True)
            return False

    def _get_context_for_batch(self, batch_start_num: int) -> str:
        """获取批次的上下文信息"""
        context_parts = []
        
        # 1. 获取前文上下文
        context_chapters_count = self.config.generation_config.get("outline_context_chapters", 10)
        detail_chapters_count = self.config.generation_config.get("outline_detail_chapters", 5)
        start_index = max(0, batch_start_num - 1 - context_chapters_count)
        end_index = max(0, batch_start_num - 1)
        
        # 2. 添加故事发展脉络
        if self.sync_info:
            context_parts.append("[故事发展脉络]")
            # 主线发展
            if self.sync_info.get("剧情发展", {}).get("主线梗概"):
                context_parts.append(f"主线发展：{self.sync_info['剧情发展']['主线梗概']}")
            
            # 重要事件时间线
            if self.sync_info.get("剧情发展", {}).get("重要事件"):
                context_parts.append("重要事件时间线：")
                for event in self.sync_info["剧情发展"]["重要事件"][-context_chapters_count:]:
                    context_parts.append(f"- {event}")
            
            # 进行中的冲突
            if self.sync_info.get("剧情发展", {}).get("进行中冲突"):
                context_parts.append("\n当前主要冲突：")
                for conflict in self.sync_info["剧情发展"]["进行中冲突"]:
                    context_parts.append(f"- {conflict}")
        
        # 3. 获取前文大纲的详细信息与章节目录概要
        # 解绑 context_chapters_count 对大纲目录的限制，获取更长的历史大纲列表
        # 为了防止超长篇（如1000章以上）一次性加载爆 token，这里增加了一个软限制（最大 200 章，可根据模型上下文调整，也可以设为全量获取）
        max_history_chapters = 200 
        outline_start_index = max(0, batch_start_num - 1 - max_history_chapters)
        
        previous_outlines = [o for o in self.chapter_outlines[outline_start_index:end_index] if isinstance(o, ChapterOutline)]
        if previous_outlines:
            context_parts.append(f"\n[大纲历史回顾 (共 {len(previous_outlines)} 章)]")
            
            # 对于更早的章节，只显示章节号和标题
            if len(previous_outlines) > detail_chapters_count:
                context_parts.append("\n[更早章节概要目录]")
                for prev_outline in previous_outlines[:-detail_chapters_count]:
                    context_parts.append(f"第 {prev_outline.chapter_number} 章: {prev_outline.title}")

            # 只显示最近 N 章的详细信息
            context_parts.append("\n[近期详细大纲]")
            for prev_outline in previous_outlines[-detail_chapters_count:]:
                context_parts.append(f"\n第 {prev_outline.chapter_number} 章: {prev_outline.title}")
                context_parts.append(f"关键点: {', '.join(prev_outline.key_points)}")
                context_parts.append(f"涉及角色: {', '.join(prev_outline.characters)}")
                context_parts.append(f"场景: {', '.join(prev_outline.settings)}")
                context_parts.append(f"冲突: {', '.join(prev_outline.conflicts)}")
        
        # 4. 添加人物关系网络
        if self.sync_info.get("人物设定", {}).get("人物关系"):
            context_parts.append("\n[关键人物关系]")
            for relation in self.sync_info["人物设定"]["人物关系"][-context_chapters_count:]:
                context_parts.append(f"- {relation}")
        
        # 5. 添加世界观关键信息
        if self.sync_info.get("世界观"):
            context_parts.append("\n[世界观关键信息]")
            for key, value in self.sync_info["世界观"].items():
                if value:  # 只添加非空信息
                    # 确保所有元素都被转换为字符串，以防列表中包含非字符串元素（如字典）
                    context_parts.append(f"{key}: {', '.join(str(item) for item in value)}")
        
        return "\n\n".join(context_parts)

    def _check_outline_consistency(self, new_outline: ChapterOutline, previous_outlines: List[ChapterOutline]) -> bool:
        """检查新生成的大纲与已有大纲的一致性，仅添加新角色和新场景"""
        try:
            # 1. 检查与前文的关联
            if previous_outlines:
                last_outline = previous_outlines[-1]
                # 检查是否有角色延续
                character_overlap = set(new_outline.characters) & set(last_outline.characters)
                if not character_overlap:
                    logging.warning(f"第 {new_outline.chapter_number} 章与前一章没有共同角色")
                    # return False # 可以考虑在这里返回 False，如果希望严格强制角色延续性
                # 检查场景延续性
                setting_overlap = set(new_outline.settings) & set(last_outline.settings)
                if not setting_overlap:
                    logging.warning(f"第 {new_outline.chapter_number} 章与前一章没有共同场景")
                    # return False # 可以考虑在这里返回 False，如果希望严格强制场景延续性

                # 标题：与全部前文比较（标题应全局唯一）
                for prev_outline in previous_outlines:
                    if new_outline.title == prev_outline.title:
                        logging.warning(
                            f"[一致性] 第 {new_outline.chapter_number} 章标题 '{new_outline.title}' "
                            f"与第 {prev_outline.chapter_number} 章完全重复 → 拒绝"
                        )
                        return False

                # 关键点：仅与最近 100 章比较（超长篇中远距离关键点重合属正常叙事回环）
                recent_outlines = previous_outlines[-100:]
                for prev_outline in recent_outlines:
                    common_key_points = set(new_outline.key_points) & set(prev_outline.key_points)
                    if len(new_outline.key_points) > 0 and len(common_key_points) / len(new_outline.key_points) > 0.5:
                        logging.warning(
                            f"[一致性] 第 {new_outline.chapter_number} 章关键点与第 {prev_outline.chapter_number} 章"
                            f"重复率 {len(common_key_points)}/{len(new_outline.key_points)} > 50% → 拒绝"
                        )
                        return False

            # 2. 检查与同步信息的一致性，仅添加新内容
            if self.sync_info:
                # 检查角色是否在人物设定中
                all_characters = set()
                char_info_list = self.sync_info.get("人物设定", {}).get("人物信息", [])
                for char_info in char_info_list:
                    all_characters.add(char_info.get("名称", ""))
                
                # 只添加新角色
                unknown_characters = set(new_outline.characters) - all_characters
                if unknown_characters:
                    for char_name in unknown_characters:
                        if char_name:
                            # 自动添加新角色，保持其他角色信息不变
                            new_char = {"名称": char_name, "身份": "", "特点": "", "发展历程": "", "当前状态": ""}
                            char_info_list.append(new_char)
                            logging.info(f"自动添加新角色到人物设定: {char_name}")
                    # 更新 sync_info 中的人物信息列表
                    self.sync_info["人物设定"]["人物信息"] = char_info_list
                    self._save_sync_info()

                # 检查场景是否在世界观中
                all_settings = set()
                setting_list = self.sync_info.get("世界观", {}).get("关键场所", [])
                for setting in setting_list:
                    all_settings.add(setting)
                
                # 只添加新场景
                unknown_settings = set(new_outline.settings) - all_settings
                if unknown_settings:
                    for setting_name in unknown_settings:
                        if setting_name:
                            setting_list.append(setting_name)
                            logging.info(f"自动添加新场景到世界观关键场所: {setting_name}")
                    # 更新 sync_info 中的场景列表
                    self.sync_info["世界观"]["关键场所"] = setting_list
                    self._save_sync_info()

            return True
        except Exception as e:
            logging.error(f"检查大纲一致性时出错: {str(e)}")
            return False

    def _get_knowledge_references(self, batch_start: int, batch_end: int, 
                                previous_outlines: List[ChapterOutline]) -> str:
        """从知识库获取相关参考信息"""
        try:
            # 构建搜索查询
            search_queries = []
            
            # 1. 基于前文大纲的关键信息
            for outline in previous_outlines[-5:]:  # 只使用最近5章
                search_queries.extend(outline.key_points)
                search_queries.extend(outline.characters)
                search_queries.extend(outline.settings)
            
            # 2. 基于同步信息的关键信息（限制为最后更新章节前3章内的信息）
            if self.sync_info:
                # 计算需要参考的章节范围：最后更新章节前3章
                reference_start = max(1, batch_start - 3)
                reference_end = batch_start - 1
                
                # 只添加相关章节范围内的世界观信息
                world_building = self.sync_info.get("世界观", {})
                for key, values in world_building.items():
                    if values:
                        # 过滤出与前3章相关的世界观信息
                        filtered_values = self._filter_sync_info_by_chapter_range(
                            values, reference_start, reference_end
                        )
                        search_queries.extend(filtered_values)
                
                # 只添加前3章内出现的人物信息
                character_info = self.sync_info.get("人物设定", {}).get("人物信息", [])
                recent_characters = set()
                
                # 从前3章的大纲中收集角色
                for outline in previous_outlines:
                    if outline and reference_start <= outline.chapter_number <= reference_end:
                        recent_characters.update(outline.characters)
                
                # 只添加在前3章中出现过的角色
                for char in character_info:
                    if isinstance(char, dict):
                        char_name = char.get("名称", "")
                        if char_name in recent_characters:
                            search_queries.append(char_name)
            
            # 3. 基于最后更新章节范围的查询
            search_queries.append(f"第{batch_start}章到第{batch_end}章")
            
            # 去重并过滤空值
            search_queries = list(set(q for q in search_queries if q))
            
            # 从知识库搜索相关信息
            reference_texts = []
            for query in search_queries:
                results = self.knowledge_base.search(query, top_k=3)
                if results:
                    reference_texts.extend(results)
            
            # 格式化参考信息
            if reference_texts:
                return "\n".join([f"- {text}" for text in reference_texts])
            return ""
            
        except Exception as e:
            logging.error(f"获取知识库参考信息时出错: {str(e)}")
            return ""
    
    def _filter_sync_info_by_chapter_range(self, values: list, start_chapter: int, end_chapter: int) -> list:
        """根据章节范围过滤同步信息"""
        try:
            filtered_values = []
            for value in values:
                # 如果值中包含章节信息，检查是否在范围内
                if isinstance(value, str):
                    # 检查是否包含章节号模式（如"第X章"）
                    import re
                    chapter_matches = re.findall(r'第(\d+)章', value)
                    if chapter_matches:
                        # 如果包含章节号，检查是否在范围内
                        for chapter_num_str in chapter_matches:
                            chapter_num = int(chapter_num_str)
                            if start_chapter <= chapter_num <= end_chapter:
                                filtered_values.append(value)
                                break
                    else:
                        # 如果不包含明确的章节号，保留该信息（可能是通用信息）
                        filtered_values.append(value)
                else:
                    # 非字符串类型直接保留
                    filtered_values.append(value)
            
            return filtered_values
        except Exception as e:
            logging.error(f"过滤同步信息时出错: {str(e)}")
            return values  # 出错时返回原始值

if __name__ == "__main__":
    import argparse
    import re # For mock model parsing
    # 假设 Config, OutlineModel, KnowledgeBase 可以正确导入或用 Mock 替代
    try:
        # Change to absolute import assuming script is run from project root
        # or src is in PYTHONPATH
        from src.config.config import Config
        # Mock or import actual models
        class MockModel:
             def generate(self, prompt):
                 logging.info("[MockModel] Generating outline...")
                 # 返回一个符合格式的 JSON 字符串（示例）
                 example_chapter_num = 1 # 需要从 prompt 中解析
                 match = re.search(r'生成从第 (\d+) 章开始', prompt)
                 if match:
                     example_chapter_num = int(match.group(1))
                 
                 match_size = re.search(r'共 (\d+) 个章节的大纲', prompt)
                 batch_size = 1
                 if match_size:
                     batch_size = int(match_size.group(1))

                 outlines = []
                 for i in range(batch_size):
                     num = example_chapter_num + i
                     outlines.append({
                         "chapter_number": num,
                         "title": f"模拟章节 {num}",
                         "key_points": [f"模拟关键点 {num}-1", f"模拟关键点 {num}-2"],
                         "characters": [f"角色A", f"角色B-{num}"],
                         "settings": [f"模拟场景 {num}"],
                         "conflicts": [f"模拟冲突 {num}"]
                     })
                 return json.dumps(outlines, ensure_ascii=False, indent=2)

        class MockKnowledgeBase:
             def search(self, query, top_k=5):
                 logging.info(f"[MockKB] Searching for: {query}")
                 return [f"知识库参考1 for '{query[:20]}...'", f"知识库参考2 for '{query[:20]}...'"]
             def build_from_files(self, files):
                 logging.info(f"[MockKB] Building from files: {files}")
                 self.is_built = True


        OutlineModel = MockModel
        KnowledgeBase = MockKnowledgeBase
        # Setup logging for testing
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    except ImportError as e:
        logging.error(f"无法导入必要的模块: {e}")
        exit(1)


    parser = argparse.ArgumentParser(description='生成小说大纲')
    parser.add_argument('--config', type=str, default='config.json', help='配置文件路径') # Default for testing
    # Make other args optional for simpler testing if needed, or provide defaults
    parser.add_argument('--novel-type', type=str, default='修真玄幻', help='小说类型')
    parser.add_argument('--theme', type=str, default='天庭权谋', help='主题')
    parser.add_argument('--style', type=str, default='热血悬疑', help='写作风格')
    parser.add_argument('--start', type=int, default=1, help='起始章节')
    parser.add_argument('--end', type=int, default=5, help='结束章节') # Small range for test
    parser.add_argument('--extra-prompt', type=str, help='额外提示词')
    
    args = parser.parse_args()
    
    # 加载配置
    try:
        config = Config(args.config)
        # Ensure necessary keys exist for testing
        if "output_config" not in config or "output_dir" not in config.output_config:
             config.output_config = {"output_dir": "data/output_test"}
             os.makedirs(config.output_config["output_dir"], exist_ok=True)
        if "generation_config" not in config:
            config.generation_config = {"max_retries": 1, "retry_delay": 1} # Faster test retries
    except FileNotFoundError:
         logging.error(f"配置文件 {args.config} 未找到。")
         exit(1)
    except Exception as e:
         logging.error(f"加载配置文件 {args.config} 出错: {e}")
         exit(1)

    
    # 初始化模型和知识库 (使用 Mock)
    outline_model = OutlineModel()
    knowledge_base = KnowledgeBase()
    knowledge_base.build_from_files([]) # Simulate build
    
    # 创建大纲生成器
    try:
        generator = OutlineGenerator(config, outline_model, knowledge_base)
    except Exception as e:
         logging.error(f"创建 OutlineGenerator 实例失败: {e}", exc_info=True)
         exit(1)

    
    # 生成大纲
    logging.info("开始生成大纲 (测试模式)...")
    success = generator.generate_outline(
        novel_type=args.novel_type,
        theme=args.theme,
        style=args.style,
        mode='replace',
        replace_range=(args.start, args.end),
        extra_prompt=args.extra_prompt
    )
    
    if success:
        print(f"\n大纲生成成功！(测试范围: {args.start}-{args.end})")
        print(f"大纲文件保存在: {os.path.join(generator.output_dir, 'outline.json')}")
        # Optionally print the generated outline
        # generated_outline = load_json_file(os.path.join(generator.output_dir, 'outline.json'))
        # print("生成的大纲内容:")
        # print(json.dumps(generated_outline, ensure_ascii=False, indent=2))
    else:
        print("\n大纲生成失败，请查看上面的日志了解详细信息。") 
