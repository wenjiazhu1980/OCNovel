# -*- coding: utf-8 -*-
"""GUI PipelineWorker 大纲质量闸门集成测试。

验证 pipeline_worker 在大纲连续后、正文生成前调用质量闸门：
- 闸门判定 not passed → emit(False) 中止，不进 generate_content
- 闸门判定 passed → 正常进入逐章生成

闸门内部逻辑由 test_outline_quality_gate.py 覆盖；本文件只验证流水线布线契约。
借鉴 test_pipeline_worker_h4.py 的 mock/patch 模式。
"""

import pytest
from unittest.mock import patch, MagicMock

from src.generators.outline.outline_quality_gate import QualityGateResult


_qapp = None


@pytest.fixture(scope="module")
def qapp():
    global _qapp
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        pytest.skip("PySide6 not installed, skipping GUI tests")

    _qapp = QApplication.instance()
    if _qapp is None:
        _qapp = QApplication([])
    yield _qapp


def _make_mocks(target_chapters=3):
    mock_ai_config = MagicMock()
    mock_ai_config.get_openai_config.return_value = {"type": "openai"}

    mock_outline_generator = MagicMock()
    mock_outline_generator.chapter_outlines = [
        MagicMock(title=f"第{i}章") for i in range(1, target_chapters + 1)
    ]
    mock_outline_generator.patch_missing_chapters.return_value = ([], [])

    mock_content_generator = MagicMock()
    mock_content_generator.chapter_outlines = mock_outline_generator.chapter_outlines
    mock_content_generator._outline_discontinuous = []
    mock_content_generator._chapter_content_exists.return_value = None
    mock_content_generator._chapters_in_summary = set()
    mock_content_generator._length_warnings = {}
    mock_content_generator.current_chapter = 0
    mock_content_generator.merge_all_chapters.return_value = ["/tmp/merged.txt"]

    return mock_ai_config, mock_outline_generator, mock_content_generator


def _patch_pipeline(mock_config, mock_ai_config, mock_outline_generator, mock_content_generator):
    return [
        patch("src.config.config.Config", return_value=mock_config),
        patch("src.config.ai_config.AIConfig", return_value=mock_ai_config),
        patch("src.generators.common.utils.setup_logging"),
        patch("src.gui.workers.pipeline_worker.create_model", return_value=MagicMock()),
        patch("src.knowledge_base.knowledge_base.KnowledgeBase", return_value=MagicMock()),
        patch("src.generators.finalizer.finalizer.NovelFinalizer", return_value=MagicMock()),
        patch("src.generators.outline.outline_generator.OutlineGenerator",
              return_value=mock_outline_generator),
        patch("src.generators.content.content_generator.ContentGenerator",
              return_value=mock_content_generator),
    ]


def _run_worker(mock_config, patches):
    from src.gui.workers.pipeline_worker import PipelineWorker
    worker = PipelineWorker(config_path="dummy.json", env_path="dummy.env")
    finished = []
    worker.pipeline_finished.connect(lambda ok: finished.append(ok))
    for p in patches:
        p.start()
    try:
        worker.run()
    finally:
        for p in patches:
            p.stop()
    return finished


class TestPipelineWorkerQualityGate:

    def test_gate_not_passed_blocks_before_content(self, qapp, mock_config):
        """闸门未通过 → 流水线 emit(False)，不进入正文生成。"""
        mock_config.novel_config["target_chapters"] = 3
        mock_config.generation_config["outline_quality_gate_enabled"] = True
        mock_ai_config, mock_outline, mock_content = _make_mocks(3)

        gate = QualityGateResult(passed=False, initial_fatal=2, remaining_fatal=1,
                                 rounds_run=1, revised=True)
        patches = _patch_pipeline(mock_config, mock_ai_config, mock_outline, mock_content)
        patches.append(patch(
            "src.generators.outline.outline_quality_gate.run_quality_gate_for_pipeline",
            return_value=gate,
        ))

        finished = _run_worker(mock_config, patches)

        assert finished == [False]
        mock_content.generate_content.assert_not_called()
        mock_content.merge_all_chapters.assert_not_called()

    def test_gate_passed_allows_content(self, qapp, mock_config):
        """闸门通过 → 正常逐章生成。"""
        mock_config.novel_config["target_chapters"] = 3
        mock_config.generation_config["outline_quality_gate_enabled"] = True
        mock_ai_config, mock_outline, mock_content = _make_mocks(3)
        mock_content.generate_content.return_value = True

        gate = QualityGateResult(passed=True, initial_fatal=0, remaining_fatal=0,
                                 rounds_run=1, revised=False)
        patches = _patch_pipeline(mock_config, mock_ai_config, mock_outline, mock_content)
        patches.append(patch(
            "src.generators.outline.outline_quality_gate.run_quality_gate_for_pipeline",
            return_value=gate,
        ))

        finished = _run_worker(mock_config, patches)

        assert finished == [True]
        assert mock_content.generate_content.call_count == 3

    def test_gate_skipped_when_all_chapters_done(self, qapp, mock_config):
        """全书已完成（current_chapter == target）→ 无正文可生成，闸门不该跑，直接 emit(True)。

        回归防护：闸门曾插在「全书完成」判断之前，导致已写完的书重跑 auto 时
        被存量大纲的 fatal 拦在 emit(False)、走不到成功收尾。闸门只应在确有正文
        要生成时把关。
        """
        mock_config.novel_config["target_chapters"] = 3
        mock_config.generation_config["outline_quality_gate_enabled"] = True
        mock_ai_config, mock_outline, mock_content = _make_mocks(3)
        mock_content.current_chapter = 3  # start_chapter=4 > end=3 → 全书完成

        # 闸门若被调用会判 not passed；正确行为是根本不调用它
        gate_spy = MagicMock(return_value=QualityGateResult(
            passed=False, initial_fatal=2, remaining_fatal=2, rounds_run=1, revised=False))
        patches = _patch_pipeline(mock_config, mock_ai_config, mock_outline, mock_content)
        patches.append(patch(
            "src.generators.outline.outline_quality_gate.run_quality_gate_for_pipeline",
            gate_spy,
        ))

        finished = _run_worker(mock_config, patches)

        assert finished == [True]
        gate_spy.assert_not_called()
        mock_content.generate_content.assert_not_called()
