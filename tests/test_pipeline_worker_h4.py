# -*- coding: utf-8 -*-
"""H4 回归测试：GUI pipeline 章节失败后仍发出成功信号

关联：
- 评审报告 docs/reviews/2026-05-07-codex-review.md §H4
- 修复路线图 docs/reviews/2026-05-07-fix-roadmap.md §Phase 3
"""

import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Qt 环境 fixture(与 test_chapter_list_and_regen 复用同一份)
# ---------------------------------------------------------------------------
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


def _make_mocks(target_chapters=5):
    """生成 PipelineWorker.run() 所需的全套 mock"""
    mock_ai_config = MagicMock()
    mock_ai_config.get_openai_config.return_value = {"type": "openai"}

    mock_outline_generator = MagicMock()
    mock_outline_generator.chapter_outlines = [
        MagicMock(title=f"第{i}章") for i in range(1, target_chapters + 1)
    ]
    # 关键:补洞函数返回 (succeeded, still_missing) 元组(若被调用)
    mock_outline_generator.patch_missing_chapters.return_value = ([], [])

    mock_content_generator = MagicMock()
    mock_content_generator.chapter_outlines = mock_outline_generator.chapter_outlines
    # 默认大纲连续(空列表表示无缺洞,不触发补洞分支)
    mock_content_generator._outline_discontinuous = []
    # 默认无已存在章节(强制走 generate_content 路径)
    mock_content_generator._chapter_content_exists.return_value = None
    mock_content_generator._chapters_in_summary = set()
    # 默认无字数异常标记
    mock_content_generator._length_warnings = {}
    # current_chapter=0 → start_chapter=1,生成全量
    mock_content_generator.current_chapter = 0
    mock_content_generator.merge_all_chapters.return_value = "/tmp/merged.txt"

    return mock_ai_config, mock_outline_generator, mock_content_generator


def _patch_pipeline(mock_config, mock_ai_config, mock_outline_generator, mock_content_generator):
    """统一 patch 所有 PipelineWorker.run() 内部依赖"""
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


class TestPipelineWorkerH4FailureConsolidation:
    """[H4] PipelineWorker 失败收敛"""

    def test_continuous_mode_break_on_first_failure(self, qapp, mock_config):
        """连续模式:第 2 章失败应立即中止后续生成,最终 emit(False),跳过合并"""
        from src.gui.workers.pipeline_worker import PipelineWorker

        mock_config.novel_config["target_chapters"] = 5
        mock_ai_config, mock_outline, mock_content = _make_mocks(5)

        # 第 1 章成功,第 2 章失败,后续不应被调用
        mock_content.generate_content.side_effect = [True, False]

        worker = PipelineWorker(config_path="dummy.json", env_path="dummy.env")

        finished, failed_emits = [], []
        worker.pipeline_finished.connect(lambda ok: finished.append(ok))
        worker.chapter_failed.connect(lambda n, msg: failed_emits.append(n))

        patches = _patch_pipeline(mock_config, mock_ai_config, mock_outline, mock_content)
        for p in patches:
            p.start()
        try:
            worker.run()
        finally:
            for p in patches:
                p.stop()

        # 总信号应为失败
        assert finished == [False], f"Expected [False], got {finished}"
        # 第 2 章失败被记录
        assert 2 in failed_emits
        # 第 2 章失败后中止 → 第 3/4/5 章不应再被生成
        assert mock_content.generate_content.call_count == 2
        # 失败时不应触发自动合并
        mock_content.merge_all_chapters.assert_not_called()

    def test_target_chapters_mode_continues_after_failure(self, qapp, mock_config):
        """指定章节模式:某章失败后其他章节仍尝试,但最终 emit(False)"""
        from src.gui.workers.pipeline_worker import PipelineWorker

        mock_config.novel_config["target_chapters"] = 10
        mock_ai_config, mock_outline, mock_content = _make_mocks(10)

        # 第 3 章失败,第 5 章成功,第 7 章失败
        mock_content.generate_content.side_effect = [False, True, False]

        worker = PipelineWorker(
            config_path="dummy.json",
            env_path="dummy.env",
            target_chapters_list=[3, 5, 7],
        )

        finished, failed_emits, completed = [], [], []
        worker.pipeline_finished.connect(lambda ok: finished.append(ok))
        worker.chapter_failed.connect(lambda n, msg: failed_emits.append(n))
        worker.chapter_completed.connect(lambda n, t: completed.append(n))

        patches = _patch_pipeline(mock_config, mock_ai_config, mock_outline, mock_content)
        for p in patches:
            p.start()
        try:
            worker.run()
        finally:
            for p in patches:
                p.stop()

        # 指定章节模式应继续尝试所有章节
        assert mock_content.generate_content.call_count == 3
        # 第 3 和 7 章失败
        assert 3 in failed_emits and 7 in failed_emits
        # 第 5 章成功
        assert 5 in completed
        # 总体仍判定失败(只要任一章失败)
        assert finished == [False]
        # 指定章节模式不触发自动合并(原本就不合并)
        mock_content.merge_all_chapters.assert_not_called()

    def test_all_success_triggers_merge_and_emits_true(self, qapp, mock_config):
        """连续模式全部成功时:emit(True),触发自动合并"""
        from src.gui.workers.pipeline_worker import PipelineWorker

        mock_config.novel_config["target_chapters"] = 3
        mock_ai_config, mock_outline, mock_content = _make_mocks(3)
        mock_content.generate_content.return_value = True

        worker = PipelineWorker(config_path="dummy.json", env_path="dummy.env")

        finished = []
        worker.pipeline_finished.connect(lambda ok: finished.append(ok))

        patches = _patch_pipeline(mock_config, mock_ai_config, mock_outline, mock_content)
        for p in patches:
            p.start()
        try:
            worker.run()
        finally:
            for p in patches:
                p.stop()

        assert finished == [True]
        assert mock_content.generate_content.call_count == 3
        # 全部成功时触发合并
        mock_content.merge_all_chapters.assert_called_once()

    def test_continuous_mode_exception_break(self, qapp, mock_config):
        """连续模式:章节生成抛异常应被记入失败并中止"""
        from src.gui.workers.pipeline_worker import PipelineWorker

        mock_config.novel_config["target_chapters"] = 5
        mock_ai_config, mock_outline, mock_content = _make_mocks(5)

        mock_content.generate_content.side_effect = [
            True,
            RuntimeError("API timeout"),
        ]

        worker = PipelineWorker(config_path="dummy.json", env_path="dummy.env")

        finished, failed_emits = [], []
        worker.pipeline_finished.connect(lambda ok: finished.append(ok))
        worker.chapter_failed.connect(lambda n, msg: failed_emits.append((n, msg)))

        patches = _patch_pipeline(mock_config, mock_ai_config, mock_outline, mock_content)
        for p in patches:
            p.start()
        try:
            worker.run()
        finally:
            for p in patches:
                p.stop()

        assert finished == [False]
        # 第 2 章异常被捕获并记录
        assert any(n == 2 and "API timeout" in msg for n, msg in failed_emits)
        # 异常后不再调用第 3/4/5 章
        assert mock_content.generate_content.call_count == 2
        mock_content.merge_all_chapters.assert_not_called()
