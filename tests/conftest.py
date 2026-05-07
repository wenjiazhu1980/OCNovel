# -*- coding: utf-8 -*-
"""
OCNovel 测试公共 fixtures
提供 MockModel、MockConfig、MockKnowledgeBase 等可复用的测试桩
"""

import os
import sys
import json
import shutil
import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from dataclasses import asdict

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.generators.common.data_structures import ChapterOutline, NovelOutline, Character


# ---------------------------------------------------------------------------
# Mock Model
# ---------------------------------------------------------------------------
class MockModel:
    """模拟 AI 模型，实现 generate() 和 embed() 接口"""

    def __init__(self, config=None):
        self.config = config or {}
        self.model_name = config.get("model_name", "mock-model") if config else "mock-model"
        self.api_key = "mock-api-key"
        self.generate_responses = []  # 可预设返回队列
        self._call_count = 0

    def generate(self, prompt: str, max_tokens=None, **kwargs) -> str:
        """返回预设响应或默认响应"""
        if self.generate_responses:
            resp = self.generate_responses[self._call_count % len(self.generate_responses)]
            self._call_count += 1
            return resp
        self._call_count += 1
        return "模拟生成的文本内容"

    def embed(self, text: str) -> np.ndarray:
        """返回固定维度的随机向量"""
        np.random.seed(hash(text) % (2**31))
        return np.random.rand(128).astype("float32")

    def close(self):
        pass


# ---------------------------------------------------------------------------
# Mock Config
# ---------------------------------------------------------------------------
class MockConfig:
    """模拟 Config 对象，提供测试所需的最小配置"""

    def __init__(self, output_dir="/tmp/ocnovel_test_output"):
        self.output_config = {"output_dir": output_dir}
        self.novel_config = {
            "type": "东方玄幻",
            "theme": "修真逆袭",
            "style": "热血",
            "target_chapters": 10,
            "chapter_length": 3000,
            "writing_guide": {
                "world_building": {
                    "magic_system": "灵气修炼体系",
                    "social_system": "宗门制度",
                    "background": "灵气复苏时代",
                },
                "character_guide": {
                    "protagonist": {
                        "background": "废柴少年",
                        "initial_personality": "坚韧不拔",
                        "growth_path": "逆天改命",
                    },
                    "supporting_roles": [],
                    "antagonists": [],
                },
                "plot_structure": {
                    "act_one": {"setup": "废柴觉醒", "inciting_incident": "获得传承", "first_plot_point": "踏上修炼之路"},
                    "act_two": {"rising_action": "历练成长", "midpoint": "发现阴谋", "complications": "背叛", "darkest_moment": "陷入绝境", "second_plot_point": "突破瓶颈"},
                    "act_three": {"climax": "终极对决", "resolution": "拯救苍生", "denouement": "新的征程"},
                },
                "style_guide": {
                    "tone": "热血",
                    "pacing": "快节奏",
                    "description_focus": ["战斗场面", "修炼突破", "人物内心"],
                },
            },
        }
        self.knowledge_base_config = {
            "cache_dir": os.path.join(output_dir, "cache"),
            "chunk_size": 500,
            "chunk_overlap": 50,
            "reference_files": [],
        }
        self.generation_config = {
            "max_retries": 1,
            "retry_delay": 0,
            "validation": {"enabled": False},
            "batch_size": 5,
            "outline_batch_size": 10,
            "outline_context_chapters": 5,
            "outline_detail_chapters": 3,
            "max_tokens": 4096,
            "summary_max_content_length": 4000,
        }
        self.log_config = {"log_dir": os.path.join(output_dir, "logs")}
        self.model_config = {
            "outline_model": {"type": "openai", "api_key": "mock", "model_name": "mock", "base_url": "http://mock"},
            "content_model": {"type": "openai", "api_key": "mock", "model_name": "mock", "base_url": "http://mock"},
            "embedding_model": {"type": "openai", "api_key": "mock", "model_name": "mock", "base_url": "http://mock"},
        }
        self.imitation_config = {"enabled": False}
        self.generator_config = {
            "target_chapters": 10,
            "chapter_length": 3000,
        }
        self.config = {
            "novel_config": self.novel_config,
            "generation_config": self.generation_config,
            "output_config": self.output_config,
            "knowledge_base_config": self.knowledge_base_config,
        }

    def get_model_config(self, model_type: str):
        return self.model_config.get(model_type, {})

    def get_writing_guide(self):
        return self.novel_config["writing_guide"]

    def get_imitation_model(self):
        return self.model_config.get("content_model", {})

    def __getattr__(self, name):
        if name in self.config:
            return self.config[name]
        raise AttributeError(f"MockConfig has no attribute '{name}'")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_model():
    return MockModel()


@pytest.fixture
def mock_config(tmp_path):
    output_dir = str(tmp_path / "output")
    os.makedirs(output_dir, exist_ok=True)
    return MockConfig(output_dir=output_dir)


@pytest.fixture
def sample_chapter_outline():
    return ChapterOutline(
        chapter_number=1,
        title="废柴觉醒",
        key_points=["主角被欺负", "意外获得传承", "初次修炼"],
        characters=["林小凡", "王大锤"],
        settings=["青云宗外门"],
        conflicts=["外门弟子欺压"],
    )


@pytest.fixture
def sample_chapter_outlines():
    return [
        ChapterOutline(
            chapter_number=i,
            title=f"第{i}章标题",
            key_points=[f"关键点{i}-1", f"关键点{i}-2", f"关键点{i}-3"],
            characters=["林小凡", f"角色{i}"],
            settings=[f"场景{i}"],
            conflicts=[f"冲突{i}"],
        )
        for i in range(1, 6)
    ]


@pytest.fixture
def sample_sync_info():
    return {
        "世界观": {
            "世界背景": ["灵气复苏时代"],
            "阵营势力": ["青云宗", "魔道"],
            "重要规则": ["修炼需要灵根"],
            "关键场所": ["青云宗"],
        },
        "人物设定": {
            "人物信息": [
                {"名称": "林小凡", "身份": "外门弟子", "特点": "坚韧", "发展历程": "", "当前状态": "炼气期"}
            ],
            "人物关系": ["林小凡与王大锤为好友"],
        },
        "剧情发展": {
            "主线梗概": "废柴少年逆天改命",
            "重要事件": ["获得传承"],
            "悬念伏笔": ["神秘玉佩的秘密"],
            "已解决冲突": [],
            "进行中冲突": ["外门弟子欺压"],
        },
        "前情提要": ["林小凡在青云宗外门艰难求生"],
        "最后更新章节": 1,
        "最后更新时间": "2025-01-01 00:00:00",
    }


@pytest.fixture
def sample_chapter_content():
    return """第1章 废柴觉醒

青云宗外门，晨雾弥漫。
林小凡蹲在杂役房门口，揉着被打肿的脸。
"哼，废物就是废物。"王大锤冷笑着走远。
林小凡咬了咬牙，心里暗暗发誓："总有一天，我会让你们刮目相看。"
他摸了摸怀里那块冰凉的玉佩，感觉到一股奇异的暖流涌入体内。
"咦……这感觉还挺舒服的。"他心里想着，嘴角不自觉地翘了起来。
"""


@pytest.fixture
def output_dir_with_outline(mock_config, sample_chapter_outlines):
    """创建带有大纲文件的输出目录"""
    output_dir = mock_config.output_config["output_dir"]
    os.makedirs(output_dir, exist_ok=True)
    outline_data = [asdict(o) for o in sample_chapter_outlines]
    with open(os.path.join(output_dir, "outline.json"), "w", encoding="utf-8") as f:
        json.dump(outline_data, f, ensure_ascii=False, indent=2)
    return output_dir
