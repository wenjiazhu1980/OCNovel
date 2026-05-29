# -*- coding: utf-8 -*-
"""WritingGuideWorker JSON 渐进式解析测试

针对小米 mimo-v2.5-pro 等模型经常返回的不规范 JSON
(尾随逗号、markdown 包裹、前后解释文字、内嵌换行),
验证 WritingGuideWorker 能够渐进式地清洗并解析为 dict,
而不会因 `Expecting value` 之类异常直接报错给用户。
"""

import json

import pytest


_VALID_GUIDE = {
    "world_building": {
        "magic_system": "心相显化",
        "social_system": "异常事务局",
        "background": "灵气微复苏的现代都市",
    },
    "character_guide": {
        "protagonist": {
            "background": "中年小吃店老板",
            "initial_personality": "随性、嘴硬心软",
            "growth_path": "由被动应付走向主动守护",
        },
        "supporting_roles": [
            {"name": "陈嘉豪", "gender": "男", "role_type": "灵宠", "personality": "傲娇", "relationship": "系统化身"},
        ],
        "antagonists": [
            {"name": "黑雾", "gender": "其他", "role_type": "诡异源头", "personality": "贪婪", "conflict_point": "侵蚀人心"},
        ],
    },
    "plot_structure": {
        "act_one": {"setup": "开店", "inciting_incident": "诡异出没", "first_plot_point": "签约系统"},
        "act_two": {"rising_action": "破案累积", "midpoint": "幕后浮现", "complications": "亲友被卷入", "darkest_moment": "本体重伤", "second_plot_point": "下定决心"},
        "act_three": {"climax": "决战诡异王", "resolution": "守护城市", "denouement": "继续开店"},
        "disasters": {
            "first_disaster": "好友被诡异附身",
            "second_disaster": "店铺被毁",
            "third_disaster": "系统失控",
        },
    },
    "style_guide": {
        "tone": "热血搞笑",
        "pacing": "明快",
        "description_focus": [
            "诡异显化的视觉冲击与都市烟火气的反差",
            "战斗中嘉豪的吐槽与主角随机应变的市井智慧",
            "配角群像的羁绊与异能觉醒的成长弧光",
        ],
    },
}


def _to_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


class TestParseGuideJson:
    """围绕 WritingGuideWorker._parse_guide_json 的契约测试"""

    def test_parse_clean_json_returns_dict(self):
        from src.gui.workers.writing_guide_worker import WritingGuideWorker

        text = _to_json(_VALID_GUIDE)
        result = WritingGuideWorker._parse_guide_json(text)

        assert isinstance(result, dict)
        assert result["world_building"]["magic_system"] == "心相显化"

    def test_parse_strips_markdown_fence_with_language(self):
        """LLM 习惯包裹 ```json ... ```"""
        from src.gui.workers.writing_guide_worker import WritingGuideWorker

        text = "```json\n" + _to_json(_VALID_GUIDE) + "\n```"
        result = WritingGuideWorker._parse_guide_json(text)

        assert isinstance(result, dict)
        assert result["style_guide"]["tone"] == "热血搞笑"

    def test_parse_strips_markdown_fence_without_language(self):
        from src.gui.workers.writing_guide_worker import WritingGuideWorker

        text = "```\n" + _to_json(_VALID_GUIDE) + "\n```"
        result = WritingGuideWorker._parse_guide_json(text)

        assert isinstance(result, dict)

    def test_parse_with_explanation_prefix(self):
        """mimo 等模型偶尔会在 JSON 前补一段说明"""
        from src.gui.workers.writing_guide_worker import WritingGuideWorker

        text = "好的，下面是根据您的故事创意生成的写作指南：\n\n" + _to_json(_VALID_GUIDE)
        result = WritingGuideWorker._parse_guide_json(text)

        assert isinstance(result, dict)
        assert "world_building" in result

    def test_parse_with_explanation_suffix(self):
        from src.gui.workers.writing_guide_worker import WritingGuideWorker

        text = _to_json(_VALID_GUIDE) + "\n\n以上为完整写作指南，欢迎进一步定制。"
        result = WritingGuideWorker._parse_guide_json(text)

        assert isinstance(result, dict)
        assert result["plot_structure"]["act_three"]["climax"] == "决战诡异王"

    def test_parse_with_trailing_comma_in_object(self):
        """LLM 经常在最后一个字段后误加逗号"""
        from src.gui.workers.writing_guide_worker import WritingGuideWorker

        text = """{
  "world_building": {
    "magic_system": "心相显化",
    "social_system": "异常事务局",
    "background": "灵气微复苏的现代都市",
  },
  "style_guide": {
    "tone": "热血搞笑",
    "pacing": "明快",
    "description_focus": [
      "诡异显化的视觉冲击",
      "战斗吐槽与市井智慧",
      "配角群像的羁绊",
    ]
  }
}"""
        result = WritingGuideWorker._parse_guide_json(text)

        assert isinstance(result, dict)
        assert result["world_building"]["magic_system"] == "心相显化"
        assert len(result["style_guide"]["description_focus"]) == 3

    def test_parse_with_trailing_comma_in_array(self):
        from src.gui.workers.writing_guide_worker import WritingGuideWorker

        text = """{"style_guide": {"description_focus": ["A", "B", "C",]}}"""
        result = WritingGuideWorker._parse_guide_json(text)

        assert isinstance(result, dict)
        assert result["style_guide"]["description_focus"] == ["A", "B", "C"]

    def test_parse_returns_none_for_complete_garbage(self):
        """完全无法识别为 JSON 时返回 None 而非抛异常"""
        from src.gui.workers.writing_guide_worker import WritingGuideWorker

        result = WritingGuideWorker._parse_guide_json("这是一段完全不是 JSON 的中文文本。")

        assert result is None

    def test_parse_returns_none_for_empty_string(self):
        from src.gui.workers.writing_guide_worker import WritingGuideWorker

        result = WritingGuideWorker._parse_guide_json("")

        assert result is None

    def test_parse_handles_unescaped_newlines_in_strings(self):
        """LLM 在长字符串值中有时直接写入裸换行(原生 JSON 不允许)"""
        from src.gui.workers.writing_guide_worker import WritingGuideWorker

        text = """{
  "world_building": {
    "magic_system": "第一行说明
第二行延续说明",
    "social_system": "异常事务局",
    "background": "现代都市"
  }
}"""
        result = WritingGuideWorker._parse_guide_json(text)

        # 应渐进式回退到激进策略并解析成功
        assert isinstance(result, dict)
        assert "world_building" in result
        assert result["world_building"]["social_system"] == "异常事务局"

    def test_parse_rejects_non_object_root(self):
        """根节点必须是 object,数组要返回 None(否则上层 isinstance(result, dict) 会失败)"""
        from src.gui.workers.writing_guide_worker import WritingGuideWorker

        result = WritingGuideWorker._parse_guide_json("[1, 2, 3]")

        assert result is None
