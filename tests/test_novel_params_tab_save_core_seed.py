# -*- coding: utf-8 -*-
"""保存配置时将故事创意写入 core_seed.txt 的契约测试

NovelParamsTab._persist_story_idea_to_core_seed 是保存配置的反向同步,
对称于 _autofill_story_idea_from_core_seed:加载时 disk→输入框,保存时
输入框→disk。这一步必须有,否则 outline_generator._generate_core_seed
检测不到种子文件,会用模型重新生成,丢失用户原始意图。
"""

import os

import pytest


@pytest.fixture
def isolated_output_dir(tmp_path):
    """提供独立的 output 子目录(不预先创建)"""
    d = tmp_path / "output"
    return str(d)


class TestPersistStoryIdeaToCoreSeed:
    def test_writes_new_seed_file(self, isolated_output_dir):
        """output_dir 不存在 + 输入有内容 → 自动创建目录并写入"""
        from src.gui.tabs.novel_params_tab import NovelParamsTab

        story = "中年老登意外获得'纯种赛级嘉豪'系统"
        err = NovelParamsTab._persist_story_idea_to_core_seed(isolated_output_dir, story)

        assert err is None
        seed_path = os.path.join(isolated_output_dir, "core_seed.txt")
        assert os.path.isfile(seed_path)
        with open(seed_path, "r", encoding="utf-8") as f:
            assert f.read() == story

    def test_overwrites_existing_seed_with_different_content(self, tmp_path):
        """磁盘已有种子但内容不同 → 覆盖(对称于加载时 disk 覆盖输入框)"""
        from src.gui.tabs.novel_params_tab import NovelParamsTab

        out = tmp_path / "out"
        out.mkdir()
        old = out / "core_seed.txt"
        old.write_text("旧的种子", encoding="utf-8")

        err = NovelParamsTab._persist_story_idea_to_core_seed(str(out), "新的种子")

        assert err is None
        assert old.read_text(encoding="utf-8") == "新的种子"

    def test_skips_when_content_matches_disk(self, tmp_path):
        """磁盘内容已与输入一致 → 不重写(避免无意义 IO 与 mtime 抖动)"""
        from src.gui.tabs.novel_params_tab import NovelParamsTab

        out = tmp_path / "out"
        out.mkdir()
        seed_path = out / "core_seed.txt"
        seed_path.write_text("一致的内容", encoding="utf-8")
        original_mtime = seed_path.stat().st_mtime_ns

        err = NovelParamsTab._persist_story_idea_to_core_seed(str(out), "一致的内容")

        assert err is None
        # mtime 没变 = 没有重写
        assert seed_path.stat().st_mtime_ns == original_mtime

    def test_skips_when_story_idea_empty(self, isolated_output_dir):
        """故事创意为空字符串 → 不动磁盘(用户答 A:保留已有文件)"""
        from src.gui.tabs.novel_params_tab import NovelParamsTab

        err = NovelParamsTab._persist_story_idea_to_core_seed(isolated_output_dir, "")

        assert err is None
        assert not os.path.exists(isolated_output_dir)  # 不应顺带创建空目录

    def test_skips_when_story_idea_whitespace_only(self, tmp_path):
        """全空白字符串等同于空,不动磁盘"""
        from src.gui.tabs.novel_params_tab import NovelParamsTab

        out = tmp_path / "out"
        out.mkdir()
        existing = out / "core_seed.txt"
        existing.write_text("已有的精心写的种子", encoding="utf-8")
        original_mtime = existing.stat().st_mtime_ns

        err = NovelParamsTab._persist_story_idea_to_core_seed(str(out), "   \n\t  ")

        assert err is None
        assert existing.read_text(encoding="utf-8") == "已有的精心写的种子"
        assert existing.stat().st_mtime_ns == original_mtime

    def test_skips_when_output_dir_blank(self):
        """output_dir 为空 → 跳过(沿用 _autofill 的容错风格)"""
        from src.gui.tabs.novel_params_tab import NovelParamsTab

        err = NovelParamsTab._persist_story_idea_to_core_seed("", "any")

        assert err is None

    def test_creates_output_dir_when_missing(self, tmp_path):
        """output_dir 不存在 → 自动创建,然后写入"""
        from src.gui.tabs.novel_params_tab import NovelParamsTab

        out = tmp_path / "deep" / "nested" / "out"
        # 故意不预创建任何一层
        err = NovelParamsTab._persist_story_idea_to_core_seed(str(out), "种子")

        assert err is None
        assert (out / "core_seed.txt").is_file()

    def test_returns_error_string_on_write_failure(self, tmp_path, monkeypatch):
        """写入异常 → 返回错误字符串(供保存成功弹窗追加)"""
        from src.gui.tabs.novel_params_tab import NovelParamsTab

        out = tmp_path / "out"
        out.mkdir()

        def _boom(*args, **kwargs):
            raise PermissionError("simulated denied")

        # 拦截 open 的写入路径
        real_open = open

        def _fake_open(path, mode="r", *args, **kwargs):
            if "w" in mode and str(path).endswith("core_seed.txt"):
                raise PermissionError("simulated denied")
            return real_open(path, mode, *args, **kwargs)

        monkeypatch.setattr("builtins.open", _fake_open)

        err = NovelParamsTab._persist_story_idea_to_core_seed(str(out), "any")

        assert isinstance(err, str)
        assert "denied" in err or "Permission" in err or "失败" in err

    def test_strips_story_idea_before_compare_and_write(self, tmp_path):
        """前后空白应被去除后再比较/写入(与 _autofill 的 strip 行为对称)"""
        from src.gui.tabs.novel_params_tab import NovelParamsTab

        out = tmp_path / "out"
        out.mkdir()

        err = NovelParamsTab._persist_story_idea_to_core_seed(str(out), "  种子内容  \n")

        assert err is None
        seed_path = out / "core_seed.txt"
        assert seed_path.read_text(encoding="utf-8") == "种子内容"

    def test_relative_output_dir_resolved_via_config_dir(self, tmp_path):
        """相对路径 + 提供 config_dir → 相对 config_dir 解析"""
        from src.gui.tabs.novel_params_tab import NovelParamsTab

        cfg_dir = tmp_path / "project"
        cfg_dir.mkdir()

        err = NovelParamsTab._persist_story_idea_to_core_seed(
            "data/output", "相对路径种子", config_dir=str(cfg_dir)
        )

        assert err is None
        target = cfg_dir / "data" / "output" / "core_seed.txt"
        assert target.is_file()
        assert target.read_text(encoding="utf-8") == "相对路径种子"
