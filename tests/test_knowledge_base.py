# -*- coding: utf-8 -*-
"""
测试知识库模块 - KnowledgeBase, TextChunk
"""

import os
import json
import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from src.knowledge_base.knowledge_base import KnowledgeBase, TextChunk


class TestTextChunk:
    """TextChunk 数据结构测试"""

    def test_create(self):
        chunk = TextChunk(content="测试内容", chapter=1, start_idx=0, end_idx=10, metadata={"key": "value"})
        assert chunk.content == "测试内容"
        assert chunk.chapter == 1
        assert chunk.metadata["key"] == "value"


class TestKnowledgeBase:
    """KnowledgeBase 测试"""

    @pytest.fixture
    def mock_embedding_model(self):
        model = MagicMock()
        model.model_name = "mock-embedding"
        model.embed.return_value = np.random.rand(128).astype("float32")
        return model

    @pytest.fixture
    def kb_config(self, tmp_path):
        return {
            "cache_dir": str(tmp_path / "kb_cache"),
            "chunk_size": 100,
            "chunk_overlap": 20,
        }

    @pytest.fixture
    def kb(self, kb_config, mock_embedding_model):
        return KnowledgeBase(kb_config, mock_embedding_model)

    def test_init(self, kb, kb_config):
        assert kb.is_built is False
        assert kb.chunks == []
        assert os.path.isdir(kb_config["cache_dir"])

    def test_init_with_reranker(self, kb_config, mock_embedding_model):
        reranker_config = {"model_name": "reranker-model", "api_key": "key", "base_url": "http://mock"}
        with patch("openai.OpenAI"):
            kb = KnowledgeBase(kb_config, mock_embedding_model, reranker_config=reranker_config)
        assert kb.reranker is not None or kb.reranker_config is not None

    def test_chunk_text_single_chapter(self, kb):
        text = "这是一段测试文本，" * 50
        chunks = kb._chunk_text(text)
        assert len(chunks) > 0
        for chunk in chunks:
            assert isinstance(chunk, TextChunk)
            assert chunk.content.strip() != ""

    def test_chunk_text_multiple_chapters(self, kb):
        text = "第1章 开始\n" + "内容" * 100 + "\n第2章 继续\n" + "更多内容" * 100
        chunks = kb._chunk_text(text)
        assert len(chunks) > 0
        chapters = set(c.chapter for c in chunks)
        assert len(chapters) >= 1

    def test_build_and_search(self, kb, mock_embedding_model):
        text = "第1章 测试\n" + "这是第一章的内容，讲述了主角的冒险故事。" * 20
        kb.build(text)
        assert kb.is_built is True
        assert kb.index is not None
        assert len(kb.chunks) > 0

        # 搜索
        results = kb.search("主角冒险", k=3)
        assert isinstance(results, list)
        assert len(results) > 0

    def test_build_caching(self, kb, mock_embedding_model, kb_config):
        text = "第1章 缓存测试\n" + "缓存内容" * 50
        kb.build(text)
        call_count_1 = mock_embedding_model.embed.call_count

        # 第二次构建应该从缓存加载
        kb2 = KnowledgeBase(kb_config, mock_embedding_model)
        kb2.build(text)
        call_count_2 = mock_embedding_model.embed.call_count
        # 缓存命中时不应该再调用 embed
        assert call_count_2 == call_count_1

    def test_build_force_rebuild(self, kb, mock_embedding_model):
        text = "第1章 强制重建\n" + "内容" * 50
        kb.build(text)
        count_1 = mock_embedding_model.embed.call_count
        kb.build(text, force_rebuild=True)
        count_2 = mock_embedding_model.embed.call_count
        assert count_2 > count_1

    def test_search_without_build_raises(self, kb):
        with pytest.raises(ValueError, match="not built"):
            kb.search("查询")

    def test_search_empty_vector(self, kb, mock_embedding_model):
        text = "第1章 测试\n" + "内容" * 50
        kb.build(text)
        mock_embedding_model.embed.return_value = None
        results = kb.search("查询")
        assert results == []

    def test_get_all_references(self, kb, mock_embedding_model):
        text = "第1章 测试\n" + "参考内容" * 50
        kb.build(text)
        refs = kb.get_all_references()
        assert isinstance(refs, dict)
        assert len(refs) <= 10

    def test_get_all_references_empty(self, kb):
        refs = kb.get_all_references()
        assert refs == {}

    def test_get_context(self, kb, mock_embedding_model):
        text = "第1章 测试\n" + "上下文内容" * 100
        kb.build(text)
        if kb.chunks:
            context = kb.get_context(kb.chunks[0])
            assert "previous_chunks" in context
            assert "next_chunks" in context
            assert "chapter_summary" in context

    def test_build_from_files(self, kb, mock_embedding_model, tmp_path):
        file1 = str(tmp_path / "ref1.txt")
        file2 = str(tmp_path / "ref2.txt")
        with open(file1, "w", encoding="utf-8") as f:
            f.write("第1章 参考文件1\n" + "参考内容1" * 50)
        with open(file2, "w", encoding="utf-8") as f:
            f.write("第2章 参考文件2\n" + "参考内容2" * 50)
        kb.build_from_files([file1, file2])
        assert kb.is_built is True

    def test_build_from_files_empty_raises(self, kb):
        with pytest.raises(ValueError, match="内容为空"):
            kb.build_from_files(["/nonexistent/file.txt"])

    def test_build_from_texts(self, kb, mock_embedding_model):
        texts = ["第一章内容" * 30, "第二章内容" * 30]
        kb.build_from_texts(texts)
        assert kb.is_built is True

    def test_get_cache_path_deterministic(self, kb):
        path1 = kb._get_cache_path("same text")
        path2 = kb._get_cache_path("same text")
        assert path1 == path2

    def test_get_cache_path_different_text(self, kb):
        path1 = kb._get_cache_path("text A")
        path2 = kb._get_cache_path("text B")
        assert path1 != path2
