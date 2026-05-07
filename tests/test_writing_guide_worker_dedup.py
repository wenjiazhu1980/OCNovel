# -*- coding: utf-8 -*-
"""[5.3] WritingGuideWorker 描写侧重去重异步化测试

验证 worker 内 _maybe_dedup_focus 在后台线程完成去重,
主线程不再需要触发 embed() 网络调用。
"""

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def worker():
    """构造一个 WritingGuideWorker 实例(不启动 QThread.run)"""
    from src.gui.workers.writing_guide_worker import WritingGuideWorker
    return WritingGuideWorker(
        env_path="/nonexistent.env",
        story_idea="测试创意",
        title="测试",
        novel_type="玄幻",
        theme="复仇",
        style="爽文",
        existing_focus=["山门遇袭"],
        dedup_max_total=5,
    )


class TestWorkerDedupAsync:
    def test_dedup_writes_metadata_into_result(self, worker):
        """worker 在 result 中写入 description_focus_kept 与 stats"""
        result = {
            "style_guide": {
                "description_focus": ["雷劫渡劫", "突破筑基", "山门遇袭"],
            }
        }
        # 强制 jaccard 兜底路径 (无 embedding 模型)
        with patch.object(worker, "_create_embedding_model_in_worker", return_value=None):
            worker._maybe_dedup_focus(result)

        assert "description_focus_kept" in result
        assert "description_focus_dedup_stats" in result
        kept = result["description_focus_kept"]
        stats = result["description_focus_dedup_stats"]
        # 必须是字符串列表
        assert isinstance(kept, list)
        assert all(isinstance(x, str) for x in kept)
        # "山门遇袭" 已存在 → 应被剔除
        assert "山门遇袭" not in kept
        # 兜底路径 method 应为 jaccard
        assert stats["method"] == "jaccard"

    def test_dedup_respects_max_total(self):
        """超过 max_total 的部分截断"""
        from src.gui.workers.writing_guide_worker import WritingGuideWorker
        worker = WritingGuideWorker(
            env_path="/nonexistent.env",
            story_idea="x", title="x", novel_type="x", theme="x", style="x",
            existing_focus=["A"],
            dedup_max_total=3,
        )
        result = {
            "style_guide": {
                "description_focus": ["B", "C", "D", "E", "F"],
            }
        }
        with patch.object(worker, "_create_embedding_model_in_worker", return_value=None):
            worker._maybe_dedup_focus(result)
        # max_total=3, existing 已有 1 → 还能新增 2 条
        kept = result["description_focus_kept"]
        assert len(kept) <= 2
        stats = result["description_focus_dedup_stats"]
        # 至少有一条被截断
        assert stats["rejected_capped"] >= 1

    def test_no_focus_field_no_op(self, worker):
        """无 description_focus 字段时不修改 result"""
        result = {"style_guide": {}}
        worker._maybe_dedup_focus(result)
        assert "description_focus_kept" not in result
        assert "description_focus_dedup_stats" not in result

    def test_empty_focus_list_no_op(self, worker):
        """description_focus 为空列表时不写入 metadata"""
        result = {"style_guide": {"description_focus": []}}
        worker._maybe_dedup_focus(result)
        assert "description_focus_kept" not in result

    def test_dedup_failure_silent(self, worker):
        """去重内部异常时不影响 result(主线程会兜底)"""
        result = {
            "style_guide": {
                "description_focus": ["A", "B"],
            }
        }
        with patch(
            "src.gui.utils.focus_dedup.deduplicate_focus_items",
            side_effect=RuntimeError("simulated failure"),
        ):
            # 不应抛异常
            worker._maybe_dedup_focus(result)
        # 失败时不写入 metadata,主线程检测到缺失会走兜底
        assert "description_focus_kept" not in result
