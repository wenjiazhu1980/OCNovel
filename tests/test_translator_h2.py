"""H2 回归测试：语言热切换 zh→en 时 _translators 未初始化导致 AttributeError

关联：
- 评审报告 docs/reviews/2026-05-07-codex-review.md §H2
- 修复路线图 docs/reviews/2026-05-07-fix-roadmap.md §Phase 1

注意：依赖 H1（恢复 tests/ 入库）才能进入 CI。
"""
import pytest
from unittest.mock import MagicMock, patch

# 通过 mock 屏蔽 PySide6 实际创建 QApplication 的依赖
# 这样测试可以在无显示器/headless 环境运行


@pytest.fixture
def mock_app():
    """伪 QApplication 实例，仅暴露需要的接口"""
    app = MagicMock()
    # 关键：默认不预设 _translators 属性，模拟 zh_CN 启动场景
    if hasattr(app, '_translators'):
        del app._translators
    return app


def test_switch_language_zh_to_en_when_translators_uninitialized(mock_app):
    """H2 核心回归：app._translators 不存在时切换到英文不应崩溃"""
    from src.gui.i18n.translator import switch_language

    # 模拟翻译文件不存在的最小路径（重点是验证 _translators 初始化）
    with patch('src.gui.i18n.translator.os.path.exists', return_value=False):
        # 修复前：会抛 AttributeError: 'MagicMock' has no attribute '_translators'
        # 修复后：应正常执行，返回 False（因为翻译文件不存在）
        result = switch_language(mock_app, 'en_US')

    # 验证 _translators 已被赋值为空列表（即使切换失败也应该被重置）
    assert hasattr(mock_app, '_translators')
    assert mock_app._translators == []
    # 翻译文件不存在时返回 False
    assert result is False


def test_switch_language_zh_to_zh_no_op(mock_app):
    """zh→zh 切换应该正常返回 True，且不影响 _translators 状态"""
    from src.gui.i18n.translator import switch_language

    result = switch_language(mock_app, 'zh_CN')
    assert result is True
    # 重置后即使是空列表也应存在该属性
    assert hasattr(mock_app, '_translators')
    assert mock_app._translators == []


def test_switch_language_en_to_zh_clears_translators(mock_app):
    """en→zh 切换时应移除已安装的英文 translator"""
    from src.gui.i18n.translator import switch_language

    # 模拟已安装一个翻译器的状态
    fake_translator = MagicMock()
    mock_app._translators = [fake_translator]

    result = switch_language(mock_app, 'zh_CN')

    # 验证 removeTranslator 被调用过
    mock_app.removeTranslator.assert_called_once_with(fake_translator)
    # 验证 _translators 被重置
    assert mock_app._translators == []
    assert result is True


def test_switch_language_idempotent(mock_app):
    """连续多次切换不应累积或崩溃"""
    from src.gui.i18n.translator import switch_language

    with patch('src.gui.i18n.translator.os.path.exists', return_value=False):
        for _ in range(5):
            switch_language(mock_app, 'en_US')
            switch_language(mock_app, 'zh_CN')

    # 最终态：_translators 是空列表（zh_CN 为最后一次调用）
    assert mock_app._translators == []
