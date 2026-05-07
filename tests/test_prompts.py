# -*- coding: utf-8 -*-
"""
测试提示词生成模块 - prompts.py 和 humanization_prompts.py
覆盖：大纲提示词、章节提示词、一致性检查、逻辑检查、仿写、知识库检索等
"""

import pytest
from src.generators.prompts import (
    get_outline_prompt,
    get_chapter_prompt,
    get_summary_prompt,
    get_sync_info_prompt,
    get_consistency_check_prompt,
    get_chapter_revision_prompt,
    get_logic_check_prompt,
    get_style_check_prompt,
    get_emotion_check_prompt,
    get_imitation_prompt,
    get_knowledge_search_prompt,
    get_knowledge_filter_prompt,
    get_core_seed_prompt,
    get_recent_chapters_summary_prompt,
)
from src.generators.humanization_prompts import (
    get_humanization_prompt,
    get_chinese_punctuation_rules,
    get_zhuque_optimization_prompt,
    generate_adaptive_humanization_prompt,
    get_rewrite_prompt_for_high_ai_content,
    get_humanizer_zh_core_rules,
    get_ai_writing_patterns_blacklist,
    get_rhythm_variation_rules,
    get_quality_self_check_list,
    get_enhanced_humanization_prompt,
)


# ======================== 大纲提示词 ========================

class TestGetOutlinePrompt:

    def _make_novel_config(self):
        """构造最小化的 novel_config 以避免 description_focus 索引越界"""
        return {
            "writing_guide": {
                "world_building": {},
                "character_guide": {"protagonist": {}, "supporting_roles": [], "antagonists": []},
                "plot_structure": {"act_one": {}, "act_two": {}, "act_three": {}},
                "style_guide": {"tone": "热血", "pacing": "快", "description_focus": ["战斗", "修炼", "内心"]},
            }
        }

    def test_basic_output(self):
        prompt = get_outline_prompt(
            novel_type="东方玄幻",
            theme="修真逆袭",
            style="热血",
            current_start_chapter_num=1,
            current_batch_size=5,
            novel_config=self._make_novel_config(),
        )
        assert "5" in prompt
        assert "JSON" in prompt
        assert "chapter_number" in prompt

    def test_with_existing_context(self):
        prompt = get_outline_prompt(
            novel_type="仙侠",
            theme="问道",
            style="古风",
            current_start_chapter_num=6,
            current_batch_size=5,
            existing_context="前5章主角已经入门修炼",
            novel_config=self._make_novel_config(),
        )
        assert "前5章主角已经入门修炼" in prompt

    def test_with_extra_prompt(self):
        prompt = get_outline_prompt(
            novel_type="武侠",
            theme="江湖",
            style="写实",
            current_start_chapter_num=1,
            current_batch_size=3,
            extra_prompt="增加更多打斗场面",
            novel_config=self._make_novel_config(),
        )
        assert "增加更多打斗场面" in prompt
        assert "额外要求" in prompt

    def test_with_novel_config(self):
        config = {
            "writing_guide": {
                "world_building": {"magic_system": "灵气修炼"},
                "character_guide": {
                    "protagonist": {"background": "废柴少年"},
                    "supporting_roles": [],
                    "antagonists": [],
                },
                "plot_structure": {
                    "act_one": {"setup": "开端", "inciting_incident": "触发", "first_plot_point": "转折"},
                    "act_two": {},
                    "act_three": {},
                },
                "style_guide": {"tone": "热血", "pacing": "快", "description_focus": ["战斗", "修炼", "内心"]},
            }
        }
        prompt = get_outline_prompt(
            novel_type="玄幻", theme="修真", style="热血",
            current_start_chapter_num=1, current_batch_size=5,
            novel_config=config,
        )
        assert "灵气修炼" in prompt
        assert "废柴少年" in prompt

    def test_with_reference_info(self):
        prompt = get_outline_prompt(
            novel_type="玄幻", theme="修真", style="热血",
            current_start_chapter_num=1, current_batch_size=5,
            reference_info="参考：凡人修仙传的修炼体系",
            novel_config=self._make_novel_config(),
        )
        assert "知识库参考信息" in prompt
        assert "凡人修仙传" in prompt


# ======================== 章节提示词 ========================

class TestGetChapterPrompt:

    def test_basic_output(self):
        outline = {
            "chapter_number": 1,
            "title": "废柴觉醒",
            "key_points": ["被欺负", "获得传承"],
            "characters": ["林小凡"],
            "settings": ["青云宗"],
            "conflicts": ["外门欺压"],
        }
        prompt = get_chapter_prompt(outline=outline, references={})
        assert "第1章" in prompt
        assert "废柴觉醒" in prompt
        assert "林小凡" in prompt
        assert "人性化" in prompt or "对话" in prompt

    def test_with_story_config(self):
        outline = {"chapter_number": 2, "title": "初修", "key_points": ["修炼"], "characters": ["林小凡"], "settings": ["洞府"], "conflicts": ["瓶颈"]}
        story_config = {
            "writing_guide": {
                "world_building": {"magic_system": "灵气体系"},
                "character_guide": {"protagonist": {"background": "废柴"}},
                "style_guide": {"tone": "热血", "pacing": "快", "description_focus": ["战斗", "修炼", "内心"]},
            }
        }
        prompt = get_chapter_prompt(outline=outline, references={}, story_config=story_config)
        assert "灵气体系" in prompt
        assert "故事设定" in prompt

    def test_with_sync_info(self, sample_sync_info):
        outline = {"chapter_number": 3, "title": "危机", "key_points": ["遇敌"], "characters": ["林小凡"], "settings": ["山谷"], "conflicts": ["伏击"]}
        prompt = get_chapter_prompt(outline=outline, references={}, sync_info=sample_sync_info)
        assert "故事进展信息" in prompt
        assert "灵气复苏" in prompt

    def test_with_chapter_length(self):
        outline = {"chapter_number": 1, "title": "测试", "key_points": ["测试"], "characters": ["A"], "settings": ["B"], "conflicts": ["C"]}
        prompt = get_chapter_prompt(outline=outline, references={}, chapter_length=3000)
        assert "2400" in prompt  # 3000 * 0.8
        assert "3600" in prompt  # 3000 * 1.2

    def test_context_truncation(self):
        outline = {"chapter_number": 1, "title": "测试", "key_points": [], "characters": [], "settings": [], "conflicts": []}
        long_context = "A" * 5000
        prompt = get_chapter_prompt(outline=outline, references={}, context_info=long_context)
        assert "省略" in prompt


# ======================== 摘要提示词 ========================

class TestGetSummaryPrompt:

    def test_basic(self):
        prompt = get_summary_prompt("这是一段章节内容，讲述了主角的冒险故事。")
        assert "摘要" in prompt
        assert "200" in prompt

    def test_long_content_truncation(self):
        long_content = "内容" * 5000
        prompt = get_summary_prompt(long_content)
        # 函数内部截取前4000字符
        assert len(prompt) < len(long_content) + 1000


# ======================== 同步信息提示词 ========================

class TestGetSyncInfoPrompt:

    def test_basic(self):
        prompt = get_sync_info_prompt("主角打败了敌人", existing_sync_info="{}", current_chapter=5)
        assert "主角打败了敌人" in prompt
        assert "JSON" in prompt or "json" in prompt.lower()
        assert "5" in prompt

    def test_with_existing_info(self):
        existing = '{"世界观": {"世界背景": ["灵气复苏"]}}'
        prompt = get_sync_info_prompt("新内容", existing_sync_info=existing, current_chapter=10)
        assert "灵气复苏" in prompt


# ======================== 一致性检查提示词 ========================

class TestGetConsistencyCheckPrompt:

    def test_basic(self, sample_sync_info):
        outline = {"chapter_number": 1, "title": "测试", "key_points": ["点1"], "characters": ["林小凡"], "settings": ["青云宗"], "conflicts": ["冲突"]}
        prompt = get_consistency_check_prompt(
            chapter_content="测试内容",
            chapter_outline=outline,
            sync_info=sample_sync_info,
        )
        assert "一致性" in prompt
        assert "100分" in prompt or "100" in prompt
        assert "修改必要性" in prompt


# ======================== 章节修正提示词 ========================

class TestGetChapterRevisionPrompt:

    def test_basic(self):
        outline = {"chapter_number": 1, "title": "测试", "key_points": ["点1"], "characters": ["A"], "settings": ["B"], "conflicts": ["C"]}
        prompt = get_chapter_revision_prompt(
            original_content="原始内容",
            consistency_report="需要修改人物行为",
            chapter_outline=outline,
        )
        assert "原始内容" in prompt
        assert "需要修改人物行为" in prompt
        assert "修改要求" in prompt


# ======================== 逻辑检查提示词 ========================

class TestGetLogicCheckPrompt:

    def test_basic(self):
        outline = {"chapter_number": 1, "title": "测试", "key_points": ["点1"], "characters": ["A"], "settings": ["B"], "conflicts": ["C"]}
        prompt = get_logic_check_prompt("章节内容", outline)
        assert "逻辑" in prompt
        assert "因果" in prompt
        assert "时间线" in prompt

    def test_with_sync_info(self):
        outline = {"chapter_number": 1, "title": "测试", "key_points": [], "characters": [], "settings": [], "conflicts": []}
        prompt = get_logic_check_prompt("内容", outline, sync_info="同步信息文本")
        assert "同步信息" in prompt


# ======================== 仿写提示词 ========================

class TestGetImitationPrompt:

    def test_basic(self):
        prompt = get_imitation_prompt(
            original_text="原始文本内容",
            style_examples=["范例1的文本", "范例2的文本"],
        )
        assert "原始文本内容" in prompt
        assert "范例1的文本" in prompt
        assert "风格" in prompt

    def test_with_extra_prompt(self):
        prompt = get_imitation_prompt(
            original_text="原始文本",
            style_examples=["范例"],
            extra_prompt="保持古风韵味",
        )
        assert "保持古风韵味" in prompt

    def test_no_extra_prompt(self):
        prompt = get_imitation_prompt("原始", ["范例"])
        assert "无" in prompt  # extra_prompt 默认显示 "无"


# ======================== 知识库检索提示词 ========================

class TestGetKnowledgeSearchPrompt:

    def test_basic(self):
        result = get_knowledge_search_prompt(
            chapter_number=1,
            chapter_title="废柴觉醒",
            characters_involved=["林小凡"],
            key_items=["玉佩"],
            scene_location="青云宗",
            chapter_role="开篇",
            chapter_purpose="引入主角",
            foreshadowing="玉佩的秘密",
            short_summary="主角觉醒",
        )
        # 返回的是检索词组合
        assert isinstance(result, str)
        assert len(result) > 0


# ======================== 人性化提示词 ========================

class TestHumanizationPrompts:

    def test_get_humanization_prompt_default(self):
        prompt = get_humanization_prompt()
        assert "45%" in prompt
        assert "对话" in prompt

    def test_get_humanization_prompt_custom_ratio(self):
        prompt = get_humanization_prompt(dialogue_ratio_target=0.6)
        assert "60%" in prompt

    def test_get_chinese_punctuation_rules(self):
        rules = get_chinese_punctuation_rules()
        assert "省略号" in rules
        assert "破折号" in rules
        assert "引号" in rules

    def test_get_zhuque_optimization_prompt(self):
        prompt = get_zhuque_optimization_prompt(0.5)
        assert "50%" in prompt
        assert "朱雀" in prompt

    def test_generate_adaptive_high_ai_score(self):
        prompt = generate_adaptive_humanization_prompt(ai_score=70, dialogue_ratio=0.05)
        assert "极强" in prompt
        assert "全面替换" in prompt

    def test_generate_adaptive_medium_ai_score(self):
        prompt = generate_adaptive_humanization_prompt(ai_score=30, dialogue_ratio=0.35)
        assert "中等" in prompt

    def test_generate_adaptive_low_ai_score(self):
        prompt = generate_adaptive_humanization_prompt(ai_score=10, dialogue_ratio=0.5)
        assert "轻微" in prompt

    def test_get_rewrite_prompt(self):
        prompt = get_rewrite_prompt_for_high_ai_content(
            original_text="AI味很重的文本",
            ai_analysis={"total_score": 80, "high_risk_features": ["词汇单一", "句式重复"]},
        )
        assert "AI味很重的文本" in prompt
        assert "80" in prompt
        assert "词汇单一" in prompt

    def test_get_humanizer_zh_core_rules(self):
        """测试 Humanizer-zh 核心原则"""
        prompt = get_humanizer_zh_core_rules()
        assert "删除填充短语" in prompt
        assert "打破公式结构" in prompt
        assert "变化节奏" in prompt
        assert "信任读者" in prompt
        assert "删除金句" in prompt

    def test_get_ai_writing_patterns_blacklist(self):
        """测试 AI 写作模式黑名单"""
        prompt = get_ai_writing_patterns_blacklist()
        assert "此外" in prompt
        assert "然而" in prompt
        assert "仿佛" in prompt
        assert "似乎" in prompt
        assert "三段式法则" in prompt

    def test_get_rhythm_variation_rules(self):
        """测试节奏变化要求"""
        prompt = get_rhythm_variation_rules()
        assert "句子长度变化" in prompt
        assert "段落结构变化" in prompt
        assert "叙事节奏" in prompt
        assert "短句" in prompt
        assert "长句" in prompt

    def test_get_quality_self_check_list(self):
        """测试质量自检清单"""
        prompt = get_quality_self_check_list()
        assert "句子长度检查" in prompt
        assert "AI 词汇检查" in prompt
        assert "排比结构检查" in prompt
        assert "三段式检查" in prompt
        assert "环境描写检查" in prompt

    def test_get_enhanced_humanization_prompt_with_humanizer_zh(self):
        """测试启用 Humanizer-zh 的增强版人性化提示词"""
        prompt = get_enhanced_humanization_prompt(dialogue_ratio_target=0.45, enable_humanizer_zh=True)
        assert "对话主导原则" in prompt
        assert "Humanizer-zh 核心原则" in prompt
        assert "AI 写作模式黑名单" in prompt
        assert "节奏变化要求" in prompt
        assert "生成后质量自检" in prompt

    def test_get_enhanced_humanization_prompt_without_humanizer_zh(self):
        """测试禁用 Humanizer-zh 的人性化提示词"""
        prompt = get_enhanced_humanization_prompt(dialogue_ratio_target=0.45, enable_humanizer_zh=False)
        assert "对话主导原则" in prompt
        assert "Humanizer-zh 核心原则" not in prompt
        assert "AI 写作模式黑名单" not in prompt


# ======================== 其他提示词 ========================

class TestOtherPrompts:

    def test_core_seed_prompt(self):
        prompt = get_core_seed_prompt("修真逆袭", "东方玄幻", 100, 3000)
        assert "修真逆袭" in prompt
        assert "100" in prompt

    def test_style_check_prompt(self):
        config = {"writing_guide": {"style_guide": {"tone": "热血", "pov": "第三人称", "narrative_style": "全知", "language_style": "通俗"}}}
        prompt = get_style_check_prompt("章节内容", config)
        assert "热血" in prompt
        assert "风格" in prompt

    def test_emotion_check_prompt(self):
        outline = {"chapter_number": 1, "title": "测试", "emotion": "悲伤", "key_points": ["离别"], "characters": ["A"]}
        prompt = get_emotion_check_prompt("章节内容", outline)
        assert "情感" in prompt
        assert "共鸣" in prompt

    def test_knowledge_filter_prompt(self):
        prompt = get_knowledge_filter_prompt(
            retrieved_texts=["文本片段1", "文本片段2"],
            chapter_info={"chapter_number": 1, "title": "测试"},
        )
        assert "过滤" in prompt
        assert "片段" in prompt
