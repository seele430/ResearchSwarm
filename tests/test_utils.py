"""文件名净化与路径去重测试（步骤 3）。

历史问题：main.py 直接用 `query[:20]` 拼文件名 —— 问句含 `:` `?` `*` `/` 会崩，
前 20 字相同的两次运行会互相覆盖。
"""

from core.utils import safe_filename, unique_path
from main import build_report_path

ILLEGAL = set('<>:"/\\|?*')


class TestSafeFilename:
    def test_replaces_windows_illegal_chars(self):
        cleaned = safe_filename('a/b\\c:d*e?f"g<h>i|j')
        assert not ILLEGAL & set(cleaned)
        assert "_" in cleaned

    def test_strips_trailing_dots_and_spaces(self):
        assert safe_filename("report... ") == "report"

    def test_blocks_path_separators(self):
        cleaned = safe_filename("../../etc/passwd")
        assert not ILLEGAL & set(cleaned)
        assert not cleaned.startswith(".")

    def test_empty_or_all_illegal_uses_fallback(self):
        assert safe_filename("   ", fallback="report") == "report"
        assert safe_filename("", fallback="report") == "report"

    def test_collapses_whitespace_and_keeps_cjk(self):
        assert safe_filename("AI  Agent   的发展趋势") == "AI Agent 的发展趋势"

    def test_length_cap(self):
        assert len(safe_filename("字" * 100, max_length=40)) == 40

    def test_reserved_device_names_are_prefixed(self):
        assert safe_filename("CON") == "_CON"
        assert safe_filename("lpt1") == "_lpt1"


class TestUniquePath:
    def test_returns_same_path_when_free(self, tmp_path):
        path = tmp_path / "new.md"
        assert unique_path(path) == path

    def test_appends_suffix_when_exists(self, tmp_path):
        (tmp_path / "report.md").write_text("x", encoding="utf-8")
        assert unique_path(tmp_path / "report.md").name == "report_2.md"

    def test_handles_multiple_collisions(self, tmp_path):
        for name in ("report.md", "report_2.md"):
            (tmp_path / name).write_text("x", encoding="utf-8")
        assert unique_path(tmp_path / "report.md").name == "report_3.md"


class TestBuildReportPath:
    def test_illegal_query_yields_writable_path(self, tmp_path):
        path = build_report_path("为什么 C: 盘满了？/ 怎么清理 *", directory=str(tmp_path))
        assert path.parent == tmp_path
        assert not ILLEGAL & set(path.name)
        path.write_text("ok", encoding="utf-8")  # 真的能落盘
        assert path.read_text(encoding="utf-8") == "ok"

    def test_same_query_prefix_does_not_overwrite(self, tmp_path):
        query = "AI Agent 的发展趋势"
        first = build_report_path(query, directory=str(tmp_path))
        first.write_text("1", encoding="utf-8")
        second = build_report_path(query, directory=str(tmp_path))
        assert first != second
        assert first.read_text(encoding="utf-8") == "1"

    def test_empty_query_falls_back(self, tmp_path):
        assert build_report_path("   ", directory=str(tmp_path)).name.startswith("report_")
