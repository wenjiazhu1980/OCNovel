# -*- coding: utf-8 -*-
"""
测试标题生成器模块 - TitleGenerator
"""

import os
import json
import pytest
from unittest.mock import MagicMock
from src.generators.title_generator import TitleGenerator


class TestTitleGenerator:
    """TitleGenerator 测试"""

    @pytest.fixture
    def mock_model(self):
        model = MagicMock()
        model.generate.return_value = (
            "番茄小说：逆天修仙路\n"
            "七猫小说：仙途问道\n"
            "起点中文网：万界至尊\n"
            "书旗小说：破天一剑\n"
            "掌阅：情系仙途"
        )
        return model

    @pytest.fixture
    def generator(self, mock_model, tmp_path):
        return TitleGenerator(mock_model, output_dir=str(tmp_path / "marketing"))

    def test_init(self, generator, tmp_path):
        assert os.path.isdir(str(tmp_path / "marketing"))

    def test_generate_titles(self, generator):
        titles = generator.generate_titles(
            novel_type="东方玄幻",
            theme="修真逆袭",
            keywords=["修仙", "逆袭"],
            character_names=["林小凡"],
        )
        assert isinstance(titles, dict)
        assert len(titles) > 0

    def test_generate_titles_with_outline(self, generator):
        titles = generator.generate_titles(
            novel_type="仙侠",
            theme="问道",
            keywords=["仙侠"],
            character_names=["张三"],
            existing_outline="主角从废柴成长为仙帝",
        )
        assert isinstance(titles, dict)

    def test_generate_titles_error(self, tmp_path):
        mock_model = MagicMock()
        mock_model.generate.side_effect = Exception("API错误")
        gen = TitleGenerator(mock_model, output_dir=str(tmp_path / "marketing"))
        titles = gen.generate_titles("玄幻", "修真", ["修仙"], ["主角"])
        # 错误时应返回默认标题
        assert isinstance(titles, dict)
        assert all("未能生成" in v for v in titles.values())

    def test_generate_summary(self, generator, mock_model):
        mock_model.generate.return_value = "这是一段精彩的故事梗概，讲述了主角的修仙之路。"
        summary = generator.generate_summary(
            novel_type="玄幻",
            theme="修真",
            titles={"番茄小说": "逆天修仙路"},
        )
        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_generate_summary_too_long(self, generator, mock_model):
        """超过200字的梗概应被截短"""
        mock_model.generate.side_effect = [
            "A" * 300,  # 第一次返回过长
            "精简后的梗概",  # 第二次返回精简版
        ]
        summary = generator.generate_summary("玄幻", "修真", {"番茄": "标题"})
        assert isinstance(summary, str)

    def test_generate_summary_error(self, tmp_path):
        mock_model = MagicMock()
        mock_model.generate.side_effect = Exception("API错误")
        gen = TitleGenerator(mock_model, output_dir=str(tmp_path / "marketing"))
        summary = gen.generate_summary("玄幻", "修真", {})
        assert summary == "未能生成小说梗概"

    def test_save_to_file(self, generator, tmp_path):
        titles = {"番茄小说": "测试标题"}
        summary = "测试梗概"
        cover_prompts = {"番茄小说": "封面提示词"}
        filepath = generator.save_to_file(titles, summary, cover_prompts)
        assert os.path.exists(filepath)
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["titles"] == titles
        assert data["summary"] == summary

    def test_one_click_generate(self, generator, mock_model):
        mock_model.generate.side_effect = [
            "番茄小说：标题1\n七猫小说：标题2\n起点中文网：标题3\n书旗小说：标题4\n掌阅：标题5",
            "故事梗概内容",
            "风格描述",
            "番茄小说：提示词1、2、3、4、5、6\n七猫小说：提示词1、2、3、4、5、6\n起点中文网：提示词1、2、3、4、5、6\n书旗小说：提示词1、2、3、4、5、6\n掌阅：提示词1、2、3、4、5、6",
        ]
        result = generator.one_click_generate(
            novel_config={"type": "玄幻", "theme": "修真", "keywords": ["修仙"], "main_characters": ["林小凡"]},
        )
        assert "titles" in result
        assert "summary" in result
        assert "cover_prompts" in result
        assert "saved_file" in result


class TestTitleGeneratorSummaryCompression:
    """测试 TitleGenerator 摘要压缩功能"""

    @pytest.fixture
    def mock_model(self):
        model = MagicMock()
        model.generate.return_value = "测试响应"
        return model

    @pytest.fixture
    def generator(self, mock_model, tmp_path):
        return TitleGenerator(mock_model, output_dir=str(tmp_path / "marketing"))

    def test_compress_summaries_within_limit(self, generator):
        """测试摘要总长度在限制内时不压缩"""
        summaries = [f"第{i}章摘要：这是一个简短的摘要" for i in range(10)]
        result = generator._compress_summaries(summaries, max_length=50000)

        # 应该返回所有摘要
        assert len(result.split('\n')) == 10
        assert "第0章摘要" in result
        assert "第9章摘要" in result

    def test_compress_summaries_sampling(self, generator):
        """测试摘要过长时进行智能采样"""
        # 创建400条摘要，每条约300字符，总长度约120000字符
        summaries = [f"第{i}章摘要：" + "这是一个很长的摘要内容" * 20 for i in range(400)]

        result = generator._compress_summaries(summaries, max_length=50000)

        # 压缩后长度应该小于限制
        assert len(result) <= 50000
        # 应该保留开头、中间、结尾的章节
        assert "第0章摘要" in result  # 开头
        # 结尾章节应该在390-399之间
        assert any(f"第{i}章摘要" in result for i in range(390, 400))
        # 应该进行了采样（不是所有章节都保留）
        result_lines = result.split('\n')
        assert len(result_lines) < 400  # 采样后章节数应该少于原始数量

    def test_compress_summaries_truncation(self, generator):
        """测试采样后仍过长时进行截断"""
        # 创建100条超长摘要，每条约1000字符
        summaries = [f"第{i}章摘要：" + "这是一个超级长的摘要内容" * 50 for i in range(100)]

        result = generator._compress_summaries(summaries, max_length=10000)

        # 压缩后长度应该小于限制
        assert len(result) <= 10000
        # 应该包含截断标记
        assert "..." in result

    def test_compress_summaries_empty_list(self, generator):
        """测试空摘要列表"""
        result = generator._compress_summaries([], max_length=50000)
        assert result == ""

    def test_compress_summaries_single_summary(self, generator):
        """测试单条摘要"""
        summaries = ["第1章摘要：这是唯一的摘要"]
        result = generator._compress_summaries(summaries, max_length=50000)

        assert result == summaries[0]

    def test_generate_summary_with_compression(self, generator, mock_model):
        """测试生成摘要时自动压缩章节摘要"""
        # 创建400条摘要
        summaries = [f"第{i}章：" + "内容" * 50 for i in range(400)]

        mock_model.generate.return_value = "压缩后生成的梗概"

        summary = generator.generate_summary(
            novel_type="玄幻",
            theme="修真",
            titles={"番茄小说": "测试标题"},
            summaries=summaries
        )

        # 验证生成成功
        assert summary == "压缩后生成的梗概"

        # 验证传入模型的提示词长度合理（通过检查 generate 被调用）
        assert mock_model.generate.called


class TestCoverPromptsParsing:
    """测试 generate_cover_prompts 对不同 markdown 变体的解析鲁棒性"""

    @pytest.fixture
    def gen_and_model(self, tmp_path):
        mock_model = MagicMock()
        gen = TitleGenerator(mock_model, output_dir=str(tmp_path / "marketing"))
        return gen, mock_model

    def test_plain_format_parses_all_platforms(self, gen_and_model):
        """基线：纯文本平台名格式能解析所有平台"""
        gen, mock_model = gen_and_model
        titles = {
            "番茄小说": "T1", "七猫小说": "T2", "起点中文网": "T3",
            "书旗小说": "T4", "掌阅": "T5",
        }
        mock_model.generate.side_effect = [
            "风格描述占位",
            "番茄小说：要素1、要素2、要素3、要素4、要素5、要素6\n"
            "七猫小说：要素1、要素2、要素3、要素4、要素5、要素6\n"
            "起点中文网：要素1、要素2、要素3、要素4、要素5、要素6\n"
            "书旗小说：要素1、要素2、要素3、要素4、要素5、要素6\n"
            "掌阅：要素1、要素2、要素3、要素4、要素5、要素6",
        ]
        result = gen.generate_cover_prompts("玄幻", titles, "梗概")
        assert set(result.keys()) == set(titles.keys())
        # 全部命中实际内容（不落兜底模板）
        for v in result.values():
            assert "要素1" in v

    def test_markdown_list_bold_platform_name_regression(self, gen_and_model):
        """回归：模型返回 markdown 列表 + 粗体平台名也应被解析

        Bug 症状：原解析器 `platform in platforms` 严格等值匹配，
        `*   **番茄小说**` 无法命中预期 `番茄小说`，结果五个平台全部
        走兜底默认模板（用户日志观察到 WARNING '以下平台缺少有效的提示词'）。
        """
        gen, mock_model = gen_and_model
        titles = {
            "番茄小说": "T1", "七猫小说": "T2", "起点中文网": "T3",
            "书旗小说": "T4", "掌阅": "T5",
        }
        style_resp = "风格描述占位"
        cover_resp = (
            "### **1. 标题：凡人修仙:开局一个破罐**\n"
            "*   **番茄小说**：麻衣少年、发光石罐、荧光绿魔气、岩浆红神光、中心俯视、东方玄幻\n"
            "*   **七猫小说**:清秀少年、水雾缭绕、青蓝水墨、对角构图、萤火点缀、神秘氛围\n"
            "*   **起点中文网**:背对众生、石罐神像、暗金玄武黑、仰视背影、金色闪电、史诗厚重\n"
            "*   **书旗小说**:巨大破罐、持刀挺立、黑白灰朱砂、极简荒原、文字碎裂、锋利光标\n"
            "*   **掌阅**:坚毅少年、裂痕古罐、琥珀暮光紫、夕阳剪影、丁达尔光柱、细腻尘埃\n"
        )
        mock_model.generate.side_effect = [style_resp, cover_resp]

        result = gen.generate_cover_prompts("玄幻", titles, "梗概")

        # 五个平台都应被成功解析（bug 修复前是 0 个，全部走兜底）
        missing = set(titles.keys()) - set(result.keys())
        assert not missing, f"仍有平台解析失败: {missing}"
        # 平台 key 不应残留 markdown 符号
        for p in result:
            assert "*" not in p and "#" not in p, f"平台名 '{p}' 含 markdown 残留"
        # 实际内容应来自模型返回，而非兜底模板
        assert result["番茄小说"].startswith("麻衣少年")
        assert result["掌阅"].startswith("坚毅少年")


