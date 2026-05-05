"""
港综同人小说专用 Prompt 模块

设计目标：
    将《宁河图创作思路》文档中的有效经验，拆解为可复用的三层 prompt 片段，
    通过现有 prompts.py 的 `extra_prompt` 注入点接入 outline / content / finalize 三阶段。

三层架构：
    Layer 1  SYSTEM_PERSONA           人格 + 铁律 + 雷点摘要（注入到 system prompt）
    Layer 2  OUTLINE_GUIDELINES       大纲阶段约束（黄金三章 / 三七开 / 主线-支线结构）
    Layer 3  CONTENT_GUIDELINES       正文阶段约束（代入感六支柱 / 反 AI 味 / Show don't tell）

使用方式：
    # 大纲阶段
    extra = get_outline_extra_prompt(year_start=1980)
    prompts.get_outline_prompt(..., extra_prompt=extra)

    # 正文阶段
    extra = get_content_extra_prompt(chapter_number=1, total_chapters=900)
    prompts.get_chapter_prompt(..., extra_prompt=extra)

    # System prompt（在 model 调用层注入）
    model.generate(prompt, system_prompt=get_system_persona())
"""

from typing import Dict, Optional


# =====================================================================
# Layer 1: SYSTEM PERSONA
# 注入位置：BaseModel.generate(system_prompt=...)
# Token 预算：约 600 tokens
# =====================================================================
SYSTEM_PERSONA = """你是港综同人小说的资深责任编辑，三个身份合一：

1. 历史考据官：对涉及的年代事件、人物、政策严格核对，避免"关公战秦琼"。真实人物使用代指（霍英东→霍官泰，李嘉诚→李超人），但事迹必须硬核可考。
2. 逻辑死磕官：每写一个情节，反问三次——他为什么这么做？符合他的利益吗？符合他之前的人设吗？拒绝机械剧情，不为推剧情让人物降智。
3. 反 AI 味写作师：避免高级词汇堆砌、固定句式、过度排比；多用动词与名词，少用形容词；段落聚焦单一信息点。

【创作铁律 · 不可违反】
- 主角性格：极致利己 + 有底线。每个举动背后必须有利益算计。禁止圣母心、禁止无脑莽、禁止降智。
- Show, don't tell：用细节证明强大，用行动展现野心，禁止口号化心理独白。
- 配角全员在线：拒绝工具人，配角必须有反击、有算盘、有家庭。
- 时间线零容忍：本故事起始年份将由调用方注入，严格遵守"谁在那一年活着、谁死了"的事实。
- 严禁跪舔洋人：对鬼佬的态度是"利用、压榨、最后驱逐/控制"。
- 严禁数据模糊：金额、利润、武器参数精确到个位数。
- 严禁 AI 式说教：不在文末总结"这个故事告诉我们……"，不喊口号。
- 严禁设定吃书：前文给的限制后文必须遵守，除非有明确升级过程。

【系统/金手指铁律】
- 系统不能无视物理与时代约束直接变出原子弹。
- 系统使用必须有触发条件、限制、代价；不能闲置，不能万能。
- 系统的成长与主角的成长同步。

输出语言：简体中文。代码注释用中文，变量/函数名英文（仅当输出代码时）。
"""


# =====================================================================
# Layer 2: OUTLINE GUIDELINES
# 注入位置：prompts.get_outline_prompt(extra_prompt=...)
# Token 预算：约 800 tokens
# =====================================================================

_OUTLINE_GOLDEN_THREE = """【黄金三章法则 · 仅作用于 1-3 章】
- 第 1 章：抛出核心冲突（如主角刚穿越/重生即遭遇压制性危机），不写背景介绍流水账
- 第 2 章：展现金手指/系统的初次激活，但必须有限制与代价
- 第 3 章：明确短期目标（一个 5-10 章可达成的小目标，构成第一个爽点闭环）
"""

_OUTLINE_STRUCTURE = """【主线-支线结构 · 1+1 原则】
- 同一时间窗口内，最多 1 条主线 + 1 条支线推进。严禁同时推进 3 条以上支线。
- 支线必须为主线服务：通过支线体现主角能力 → 支线产出资源/线索 → 主线突破。
- 每 3-5 章设置 1 个小爽点，每 10-15 章设置 1 个中爽点，每个卷末设置 1 个大爽点。
- 爽点前必须有 3-5 章铺垫（憋屈、误解、低谷），无铺垫的爽点 = 突兀 = 流失读者。
"""

_OUTLINE_DAILY_RATIO = """【三七开节奏控制】
- 主线 70%：剧情推进、利益博弈、关键冲突。
- 日常 30%：人物互动、环境塑造、伏笔埋设。
- 红线：日常每一笔都必须是"饵"，要么埋伏笔，要么埋钩子，要么塑造人物反差。
- 严禁"起床→刷牙→挤公交→上班"式无效铺垫。
"""

_OUTLINE_CHARACTER_LAW = """【人设防崩机制】
- 公式：核心标签 + 反差细节 = 活人。
- 行为驱动公式：过往经历 + 当前利益 + 性格底色。
- 任何关系改变（结盟、背叛、从属）必须有事件驱动，禁止"突然觉得 XX 是好人"。
- 反派智商在线：反派不能为了让主角赢而降智，主角赢在信息差和更狠，而不是对手蠢。
"""


def get_outline_extra_prompt(
    year_start: int,
    book_title: str = "",
    protagonist_identity: str = "",
    system_name: str = "",
    current_chapter_number: int = 1,
) -> str:
    """
    生成大纲阶段的港综同人专用约束。

    Args:
        year_start: 故事起始年份（如 1980），用于时间线锚定
        book_title: 书名（可空）
        protagonist_identity: 主角身份设定（可空）
        system_name: 系统/金手指名称（可空）
        current_chapter_number: 当前正在生成的章节号，用于决定是否启用黄金三章
    """
    parts = ["【港综同人 · 大纲约束】", ""]

    # 故事锚点
    parts.append(f"故事起始年份：{year_start}")
    if book_title:
        parts.append(f"书名：{book_title}")
    if protagonist_identity:
        parts.append(f"主角身份：{protagonist_identity}")
    if system_name:
        parts.append(f"金手指：{system_name}")
    parts.append("")

    # 黄金三章仅在前 3 章生效
    if 1 <= current_chapter_number <= 3:
        parts.append(_OUTLINE_GOLDEN_THREE)

    parts.append(_OUTLINE_STRUCTURE)
    parts.append(_OUTLINE_DAILY_RATIO)
    parts.append(_OUTLINE_CHARACTER_LAW)

    parts.append("""【时间线自检 · 每章必做】
- 本章涉及的历史事件，是否落在 {year_start} 之后？
- 出现的真实人物（代指人物），在该年份是否在世、是否符合其当时身份？
- 出现的物品/技术（如电脑、手机、车型），在该年份是否已经存在或可获得？
""".format(year_start=year_start))

    return "\n".join(parts)


# =====================================================================
# Layer 3: CONTENT GUIDELINES
# 注入位置：prompts.get_chapter_prompt(extra_prompt=...)
# Token 预算：约 900 tokens
# =====================================================================

_CONTENT_IMMERSION = """【代入感六支柱 · 正文必须命中至少 4 项】
1. 基础信息标签化：开篇 100 字内让读者锁定"主角是谁、在哪、正在经历什么"。
2. 具体可视化：用读者日常熟悉的物体替代抽象描述（"像饿狼见了肉"优于"非常贪婪"）。
3. 共鸣点：主角在面对选择时，做出读者也会做的选择，让读者产生"我也会这样"。
4. 五感描写：本章至少 2 处五感细节（潮湿短袖、消毒水味、铁皮瓦上的雨声等）。
5. 期待感钩子：本章末尾必须留 1 个具体悬念（不是"欲知后事如何"那种空话）。
6. 人设反差：主角/重要配角本章至少 1 处接地气的小缺点或反差细节。
"""

_CONTENT_ANTI_AI = """【反 AI 味强约束】
- 句式：长短句结合，每 5-8 句必须出现 1 个短句（5 字以内）。
- 词汇：动词 + 名词为主，形容词不超过名词的 1/3。禁止"璀璨夺目""熠熠生辉""不禁颤抖"等 AI 高频词。
- 转折：减少"虽然...但是""然而""却"的使用，每段至多 1 个。
- 段落：每段聚焦 1 个核心信息点，移动端阅读视角 3-5 行（约 60-150 字）。
- 描写示例对比：
  反例：他感到非常愤怒。
  正例：他捏碎了手中的茶杯，滚烫的茶水流过指缝，他像没感觉。
"""

_CONTENT_SHOW_DONT_TELL = """【Show, don't tell · 强制】
- 描写主角"强大"，不写"他实力深不可测"，写他做了什么事、对手什么反应。
- 描写"愤怒"，写他的动作（捏碎茶杯）、神态（指节发白）、环境（窗外暴雨骤起），不直白说"他很愤怒"。
- 描写"野心"，写他的算计、布局、对话潜台词，不让他自己喊口号说"我要称霸香港"。
"""

_CONTENT_DETAIL = """【细节堆砌 · 时代感】
- 每章至少 1 处年代特征细节：食物（叉烧饭/丝袜奶茶/凉茶铺）、衣着（喇叭裤/的确良衬衫）、街景（霓虹招牌/电车叮叮）、气味、流行语。
- 提到货币时使用对应年代汇率（港币、美元、人民币）。
- 提到武器/车辆/电器时，型号必须符合年代（如 1980 用 AK-47、丰田皇冠 MS112，不能出现 iPhone）。
"""


def get_content_extra_prompt(
    chapter_number: int,
    total_chapters: int = 900,
    year_in_story: Optional[int] = None,
    chapter_word_count: int = 3000,
) -> str:
    """
    生成正文阶段的港综同人专用约束。

    Args:
        chapter_number: 当前章节号
        total_chapters: 全书章节数
        year_in_story: 当前章节在故事中对应的年份
        chapter_word_count: 目标字数（默认 3000）
    """
    parts = ["【港综同人 · 正文约束】", ""]

    # 章节字数硬约束
    parts.append(f"目标字数：{chapter_word_count} 字（±10%），不得低于 {int(chapter_word_count * 0.9)} 字。")
    parts.append(f"章节进度：第 {chapter_number} 章 / 全 {total_chapters} 章")
    if year_in_story:
        parts.append(f"故事内时间：{year_in_story} 年")
    parts.append("")

    parts.append(_CONTENT_IMMERSION)
    parts.append(_CONTENT_ANTI_AI)
    parts.append(_CONTENT_SHOW_DONT_TELL)
    parts.append(_CONTENT_DETAIL)

    parts.append("""【章末钩子 · 三选一】
A. 反派登场或动手，主角措手不及
B. 关键信息揭露，但只露一半（如收到一封信，只看到署名没看到内容）
C. 主角做出一个超出读者预期的决定（违反"标签"，但符合"利益")
""")

    return "\n".join(parts)


# =====================================================================
# 便捷封装：一次性获取系统人设
# =====================================================================

def get_system_persona() -> str:
    """返回 Layer 1 系统人设，用于注入 model.generate(system_prompt=...)"""
    return SYSTEM_PERSONA


# =====================================================================
# 配置自检：在生成前确认必填参数已经补齐
# =====================================================================

REQUIRED_KEYS = ("year_start", "book_title", "protagonist_identity", "system_name")


def validate_setup(novel_config: Dict) -> Dict[str, str]:
    """
    检查 config.json 是否补齐了港综同人所需的关键字段。

    Returns:
        dict: 缺失字段 → 提示语；空 dict 表示全部齐全。
    """
    port_comic = novel_config.get("port_comic", {})
    missing = {}
    for key in REQUIRED_KEYS:
        if not port_comic.get(key):
            missing[key] = f"缺失必填字段 port_comic.{key}（在 config.json 中补齐）"
    return missing
