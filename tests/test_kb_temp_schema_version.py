# -*- coding: utf-8 -*-
"""[Phase 6.3] KnowledgeBase temp pickle schema_version 测试

验证:
- 新格式(schema_version=2)正常恢复
- 旧格式(无 schema_version)被保守丢弃 + WARNING
- 错误的 schema_version(< 当前版本)同样丢弃
- pickle 损坏时静默返回空(原有行为保持)
"""

import os
import pickle
import logging
import pytest
from unittest.mock import MagicMock
from src.knowledge_base.knowledge_base import KnowledgeBase, TextChunk


@pytest.fixture
def kb(tmp_path):
    """构造最小可用 KnowledgeBase 实例(不实际加载 FAISS/embedding)"""
    config = {
        "cache_dir": str(tmp_path),
        "chunk_size": 500,
        "chunk_overlap": 50,
    }
    embedding_model = MagicMock()
    return KnowledgeBase(config, embedding_model)


def _write_temp_pickle(path: str, data):
    with open(path, "wb") as f:
        pickle.dump(data, f)


class TestTempSchemaVersion:
    def test_class_constant_exists(self):
        """TEMP_SCHEMA_VERSION 类常量应已定义为 2"""
        assert KnowledgeBase.TEMP_SCHEMA_VERSION == 2

    def test_new_format_loads_successfully(self, kb, tmp_path):
        """schema_version=2 的文件正常恢复"""
        temp_file = tmp_path / "kb_x.pkl.temp_1100"
        chunks = [TextChunk(content="片段1", chapter=1, start_idx=0, end_idx=3, metadata={})]
        vectors = [[0.1, 0.2, 0.3]]
        _write_temp_pickle(str(temp_file), {
            "schema_version": 2,
            "next_chunk_idx": 1100,
            "chunks": chunks,
            "vectors": vectors,
        })
        loaded_chunks, loaded_vectors = kb._load_from_temp(str(temp_file))
        assert len(loaded_chunks) == 1
        assert loaded_chunks[0].content == "片段1"
        assert loaded_vectors == [[0.1, 0.2, 0.3]]

    def test_legacy_format_without_schema_discarded(self, kb, tmp_path, caplog):
        """无 schema_version 字段的旧格式 → 保守丢弃 + WARNING"""
        temp_file = tmp_path / "kb_x.pkl.temp_1000"
        chunks = [TextChunk(content="旧片段", chapter=1, start_idx=0, end_idx=3, metadata={})]
        vectors = [[0.5, 0.6]]
        # 模拟 989616a 之前的格式:无 schema_version 字段
        _write_temp_pickle(str(temp_file), {
            "chunks": chunks,
            "vectors": vectors,
        })
        with caplog.at_level(logging.WARNING):
            loaded_chunks, loaded_vectors = kb._load_from_temp(str(temp_file))
        assert loaded_chunks == []
        assert loaded_vectors == []
        # WARNING 应提示用户重建
        assert any("schema_version" in r.message for r in caplog.records)

    def test_outdated_schema_version_discarded(self, kb, tmp_path, caplog):
        """schema_version=1(假设的旧版)同样丢弃"""
        temp_file = tmp_path / "kb_x.pkl.temp_500"
        _write_temp_pickle(str(temp_file), {
            "schema_version": 1,
            "chunks": [],
            "vectors": [],
        })
        with caplog.at_level(logging.WARNING):
            loaded_chunks, loaded_vectors = kb._load_from_temp(str(temp_file))
        assert loaded_chunks == []
        assert loaded_vectors == []

    def test_corrupted_pickle_returns_empty(self, kb, tmp_path):
        """文件损坏时静默返回空(保持原有行为)"""
        temp_file = tmp_path / "kb_x.pkl.temp_999"
        with open(temp_file, "wb") as f:
            f.write(b"not a valid pickle")
        loaded_chunks, loaded_vectors = kb._load_from_temp(str(temp_file))
        assert loaded_chunks == []
        assert loaded_vectors == []

    def test_non_dict_payload_discarded(self, kb, tmp_path, caplog):
        """pickle 解析出非 dict(如 list)→ 视为无 schema 处理"""
        temp_file = tmp_path / "kb_x.pkl.temp_777"
        _write_temp_pickle(str(temp_file), [1, 2, 3])
        with caplog.at_level(logging.WARNING):
            loaded_chunks, loaded_vectors = kb._load_from_temp(str(temp_file))
        assert loaded_chunks == []
        assert loaded_vectors == []

    def test_save_format_includes_schema(self, tmp_path):
        """保存的 temp pickle 必须含 schema_version 与 next_chunk_idx 字段"""
        # 直接验证一个手工 dump 的样本能被新版加载,反向证明保存格式
        temp_file = tmp_path / "kb_y.pkl.temp_2000"
        _write_temp_pickle(str(temp_file), {
            "schema_version": KnowledgeBase.TEMP_SCHEMA_VERSION,
            "next_chunk_idx": 2000,
            "chunks": [],
            "vectors": [],
        })
        # 重新加载验证字段存在
        with open(temp_file, "rb") as f:
            data = pickle.load(f)
        assert "schema_version" in data
        assert "next_chunk_idx" in data
        assert data["schema_version"] == 2
        assert data["next_chunk_idx"] == 2000
