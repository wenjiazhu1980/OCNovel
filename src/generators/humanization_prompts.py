# -*- coding: utf-8 -*-
"""
人性化提示词生成模块
专门用于生成降低AI浓度的提示词
"""

from typing import Dict, Optional


def get_humanization_prompt(dialogue_ratio_target: float = 0.45) -> str:
    """获取统一的人性化写作提示词（合并了对话增强、简化策略）

    Args:
        dialogue_ratio_target: 目标对话比例，从 config.json 的 humanization.dialogue_ratio 读取
    """
    pct = f"{dialogue_ratio_target:.0%}"
    return f"""
[核心人性化要求]

1. **对话主导**（目标比例：{pct}）：用对话推进剧情，人物有口癖和习惯用语，不同身份说话方式不同，连续叙述不超过100字
2. **对话真实化**：加入停顿词（呃、那个、嗯），允许语法不完整、打断、插话、说错话、欲言又止
3. **叙述精炼化**：严禁停顿词，用词精准节奏明快，突出动作和心理描写，长短句搭配
4. **禁用AI词汇**：伴随着、与此同时、紧接着、毫无疑问、显而易见、不言而喻、众所周知、此外、然而、不仅如此
5. **句式变化**：禁止连续3句相同句式，混合长短句和不完整句，禁止"不仅……而且……"排比，列举避免三段式
6. **情感具象化**：用动作/表情/生理反应表现情绪（非"他很愤怒"而是"他握紧拳头"），情绪变化有过程，加入矛盾心理
7. **生活化细节**：无关紧要的小动作（挠头、叹气、整理衣服），环境干扰（风声、脚步声），生理反应（打哈欠、揉眼睛）
"""


def get_chinese_punctuation_rules() -> str:
    """获取中文标点符号规范化提示词"""
    return """
严格使用中文全角标点：省略号「……」、破折号「——」、引号「""」「''」，禁止英文标点。
"""


def get_zhuque_optimization_prompt(dialogue_ratio_target: float = 0.45) -> str:
    """获取朱雀AI检测优化提示词（已合并到核心人性化要求中，保留接口兼容）"""
    return ""


def generate_adaptive_humanization_prompt(
    ai_score: float,
    dialogue_ratio: float,
    dialogue_ratio_target: float = 0.45,
    content_type: str = "chapter"
) -> str:
    """根据检测结果生成自适应人性化提示词

    Args:
        ai_score: 当前AI检测分数
        dialogue_ratio: 当前对话比例
        dialogue_ratio_target: 目标对话比例，从配置读取
        content_type: 内容类型
    """

    # 根据AI分数确定强化程度
    if ai_score > 60:
        intensity_level = "极强"
        ai_word_action = "全面替换"
    elif ai_score > 40:
        intensity_level = "强"
        ai_word_action = "重点替换"
    elif ai_score > 20:
        intensity_level = "中等"
        ai_word_action = "适度替换"
    else:
        intensity_level = "轻微"
        ai_word_action = "局部优化"

    # 根据对话比例确定对话强化策略
    target_pct = f"{dialogue_ratio_target:.0%}"
    if dialogue_ratio < 0.1:
        dialogue_enhancement = f"急需大幅增加对话至{target_pct}，将80%叙述转为对话"
    elif dialogue_ratio < 0.3:
        dialogue_enhancement = f"需要增加对话至{target_pct}，将60%叙述转为对话"
    else:
        dialogue_enhancement = "适度增加对话，优化对话质量"

    return f"""
[自适应人性化策略]
当前AI分数：{ai_score:.1f}/100
对话比例：{dialogue_ratio:.1%}
人性化强度：{intensity_level}

[针对性优化要求]
1. **对话优化**：{dialogue_enhancement}
2. **AI词汇处理强度**：{ai_word_action}
3. **情感表达**：情绪变化有明显过程，包含犹豫、矛盾、尴尬等复杂情感
"""


def get_rewrite_prompt_for_high_ai_content(
    original_text: str,
    ai_analysis: Dict
) -> str:
    """为高AI浓度内容生成重写提示词"""

    ai_score = ai_analysis.get('total_score', 0)
    problem_areas = ai_analysis.get('high_risk_features', [])

    return f"""
你是一位经验丰富的网络小说作家，需要将以下AI味过重的文本改写得更加自然人性化。

[当前问题诊断]
- AI浓度分数：{ai_score:.1f}/100（目标：<20）
- 主要问题：{', '.join(problem_areas) if problem_areas else '整体AI化严重'}

[重写策略]
1. 大幅增加对话，对话要有个人特色和口头禅
2. 删除所有"伴随着"、"与此同时"类词汇，用口语化表达替代
3. 人物会说错话、会犹豫，加入无关紧要的小细节
4. 故意使用不完整句子，适当重复和口语化语法

[原始文本]
{original_text}

请按上述策略彻底重写，确保结果像人类自然创作的文本。
"""


def get_humanizer_zh_core_rules() -> str:
    """获取 Humanizer-zh 的核心原则（精简版）"""
    return """
[反AI痕迹规则]
- 删除填充短语（"为了实现这一目标"、"值得注意的是"），直接陈述
- 打破公式结构：禁止"不仅……而且……"、"这不仅仅是……而是……"
- 段落结尾多样化，不要每段都是总结句
- 信任读者，不要手把手引导（"让我们来看看……"）
- 删除金句：听起来像名言的句子必须重写，用具体细节代替抽象概括
"""


def get_ai_writing_patterns_blacklist() -> str:
    """获取中文小说创作场景的 AI 写作模式黑名单"""
    return """
[AI写作模式黑名单]
禁止以下模式：
- 过度比喻："仿佛"、"似乎"、"好像"每段都有 → 直接描写，偶尔比喻
- 频繁环境渲染：每段开头景物描写 → 环境描写服务于情节
- 机械情绪："他感到愤怒" → 通过动作表情表现
- 公式化打斗："身形一闪"、"气势如虹" → 具体动作有策略变化
- 修辞堆砌：连续排比对偶 → 修辞克制
- 系动词回避："作为一名修士" → 直接用"是"
- 章节末尾陈述总结："才刚刚开始"、"拉开帷幕"、"命运齿轮转动" → 在动作/对话/场景中戛然而止
"""


def get_rhythm_variation_rules() -> str:
    """获取节奏变化要求"""
    return """
[节奏变化]
- 句子长度交替：短句（≤10字，强调/转折）、中句（15-25字，主体叙述）、长句（≥30字，环境/心理）
- 段落长度起伏：短段2-3句 vs 长段6-8句交替，适当使用单句段落
- 紧张场景：短句快节奏多动作；平静场景：长句慢节奏重氛围
- 紧张对话短促打断，平静对话完整从容
"""


def get_quality_self_check_list() -> str:
    """获取质量自检清单"""
    return """
[质量自检]（内部检查，不要在输出中体现）
检查并修正：连续相同句式 | AI高频词 | 排比/三段式 | 环境描写过频 | 情绪抽象化 | 对话不自然 | 比喻过多 | 节奏单一 | 章节结尾总结性陈述
"""


def get_enhanced_humanization_prompt(
    dialogue_ratio_target: float = 0.45,
    enable_humanizer_zh: bool = True
) -> str:
    """获取增强版人性化写作提示词（整合 Humanizer-zh 方法论）

    Args:
        dialogue_ratio_target: 目标对话比例
        enable_humanizer_zh: 是否启用 Humanizer-zh 规则
    """
    base_prompt = get_humanization_prompt(dialogue_ratio_target)

    if not enable_humanizer_zh:
        return base_prompt

    # 整合 Humanizer-zh 规则
    enhanced_prompt = base_prompt + "\n" + get_humanizer_zh_core_rules()
    enhanced_prompt += "\n" + get_ai_writing_patterns_blacklist()
    enhanced_prompt += "\n" + get_rhythm_variation_rules()
    enhanced_prompt += "\n" + get_quality_self_check_list()

    return enhanced_prompt