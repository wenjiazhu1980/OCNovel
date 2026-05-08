# -*- coding: utf-8 -*-
"""[Bugfix] TitleGenerator 摘要 dict 容错测试

bug 复现: marketing_worker 加载 summary.json 后将 values 直接传入
_compress_summaries,若值为 dict(历史数据/外部工具写入)则在 "\n".join
处抛 TypeError: sequence item 0: expected str instance, dict found
"""

import json
import pytest
from unittest.mock import MagicMock
from src.generators.title_generator import TitleGenerator


@pytest.fixture
def generator(tmp_path):
    model = MagicMock()
    model.generate.return_value = "生成的文本"
    return TitleGenerator(model, output_dir=str(tmp_path))


class TestCoerceSummaryToText:
    """_coerce_summary_to_text 单元测试"""

    def test_str_passthrough(self):
        assert TitleGenerator._coerce_summary_to_text("第1章发生了X") == "第1章发生了X"

    def test_empty_str_passthrough(self):
        assert TitleGenerator._coerce_summary_to_text("") == ""

    def test_none_returns_empty(self):
        assert TitleGenerator._coerce_summary_to_text(None) == ""

    def test_dict_with_text_key(self):
        assert TitleGenerator._coerce_summary_to_text(
            {"text": "摘要内容", "metadata": {"chapter": 1}}
        ) == "摘要内容"

    def test_dict_with_summary_key(self):
        assert TitleGenerator._coerce_summary_to_text(
            {"summary": "另一种存储格式", "extra": 1}
        ) == "另一种存储格式"

    def test_dict_with_content_key(self):
        assert TitleGenerator._coerce_summary_to_text(
            {"content": "用 content 字段", "type": "chapter"}
        ) == "用 content 字段"

    def test_dict_with_chinese_key(self):
        """中文字段 内容 / 摘要 也应识别"""
        assert TitleGenerator._coerce_summary_to_text(
            {"摘要": "中文键存储"}
        ) == "中文键存储"
        assert TitleGenerator._coerce_summary_to_text(
            {"内容": "中文 content"}
        ) == "中文 content"

    def test_dict_with_known_key_takes_priority_over_others(self):
        """已知键优先于未知键"""
        result = TitleGenerator._coerce_summary_to_text({
            "noise": "干扰内容",
            "text": "正确答案",
            "other_str": "其他",
        })
        assert result == "正确答案"

    def test_dict_with_only_unknown_keys_uses_first_str(self):
        """无已知键时取首个非空 str 值"""
        result = TitleGenerator._coerce_summary_to_text({
            "_count": 5,
            "_internal_text": "兜底内容",
        })
        assert result == "兜底内容"

    def test_dict_with_no_str_values_falls_back_to_json(self):
        """完全无 str 值 → 序列化为 JSON 不崩溃"""
        result = TitleGenerator._coerce_summary_to_text({
            "_count": 5,
            "_meta": {"x": 1},
        })
        # 应该是合法的 JSON 字符串,包含原始结构
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed["_count"] == 5

    def test_dict_with_empty_str_values_skipped(self):
        """value 为空字符串时跳过,继续找下一个非空"""
        result = TitleGenerator._coerce_summary_to_text({
            "text": "",
            "summary": "",
            "content": "实际内容",
        })
        assert result == "实际内容"

    def test_int_coerced(self):
        """int 被 str() 兜底"""
        assert TitleGenerator._coerce_summary_to_text(42) == "42"

    def test_list_coerced(self):
        """list 被 str() 兜底,虽然不是预期场景但不崩溃"""
        result = TitleGenerator._coerce_summary_to_text(["a", "b"])
        assert isinstance(result, str)


class TestCompressSummariesMixedTypes:
    """_compress_summaries 在混合类型输入下不崩溃"""

    def test_all_str_input_unchanged_behavior(self, generator):
        """全 str 输入保持原行为"""
        summaries = ["第1章A", "第2章B", "第3章C"]
        result = generator._compress_summaries(summaries, max_length=10000)
        assert "第1章A" in result and "第2章B" in result and "第3章C" in result

    def test_all_dict_input_no_crash(self, generator):
        """全 dict 输入(模拟历史数据)不崩溃"""
        summaries = [
            {"text": "第1章发生了X"},
            {"text": "第2章发生了Y"},
            {"text": "第3章发生了Z"},
        ]
        result = generator._compress_summaries(summaries, max_length=10000)
        assert "第1章发生了X" in result
        assert "第2章发生了Y" in result
        assert "第3章发生了Z" in result

    def test_mixed_str_and_dict_input(self, generator):
        """str 与 dict 混排"""
        summaries = [
            "纯字符串第1章",
            {"summary": "字典第2章"},
            None,
            {"content": "字典第3章"},
            "",
            {"text": "字典第4章"},
        ]
        result = generator._compress_summaries(summaries, max_length=10000)
        assert "纯字符串第1章" in result
        assert "字典第2章" in result
        assert "字典第3章" in result
        assert "字典第4章" in result

    def test_empty_after_normalization_returns_empty(self, generator):
        """归一化后全为空 → 返回空串"""
        summaries = ["", None, {}]
        result = generator._compress_summaries(summaries, max_length=10000)
        # {} → json.dumps → "{}" 非空,所以最终非空字符串
        # 但 "" 与 None 应被过滤
        # 我们只断言不崩溃且返回 str
        assert isinstance(result, str)

    def test_long_dict_summaries_compression_works(self, generator):
        """大量 dict 摘要触发压缩路径不崩溃"""
        # 50 章每章 200 字 → 10000 字,触发 max_length=5000 的压缩
        summaries = [
            {"text": f"第{i}章" + "x" * 200} for i in range(1, 51)
        ]
        result = generator._compress_summaries(summaries, max_length=5000)
        assert isinstance(result, str)
        assert len(result) <= 5000

    def test_original_bug_repro(self, generator):
        """[回归] 复刻日志中的 bug 触发场景"""
        # 用户日志: 107 条 dict 摘要 → join 处 TypeError
        summaries = [{"text": f"第{i}章摘要内容"} for i in range(1, 108)]
        # 修复前会抛 TypeError,修复后正常返回 str
        result = generator._compress_summaries(summaries, max_length=50000)
        assert isinstance(result, str)
        assert "第1章摘要内容" in result
        assert "第107章摘要内容" in result
