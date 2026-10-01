"""依赖完整性测试。

存在意义：requirements.txt 曾漏掉 `trafilatura`（tools.py 顶层 import），
照 README 全新安装后 `python main.py` 会直接 ImportError。
这两个测试把「代码用到」与「声明/安装」对齐，防止同类事故复发。
"""

import ast
import re
import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as dist_version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements.txt"

# import 名 → PyPI 分发名（两者不一致时才需要映射）
ALIASES = {
    "dotenv": "python-dotenv",
    "bs4": "beautifulsoup4",
    "PIL": "pillow",
    "yaml": "pyyaml",
    "sklearn": "scikit-learn",
}

# tests/ 自身不算「项目代码」，其它目录按需排除
SKIP_DIRS = {"venv", ".venv", "__pycache__", ".git", "tests", "notes", "examples"}


def _declared_distributions() -> set[str]:
    """requirements.txt 里声明的分发名（去掉版本约束、extras、注释）。"""
    names: set[str] = set()
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        name = re.split(r"[<>=!~\[\s;]", line, maxsplit=1)[0].strip().lower()
        if name:
            names.add(name)
    return names


def _local_modules() -> set[str]:
    """项目自身的顶层模块/包名（core、agents、tools、main …）。"""
    names: set[str] = set()
    for entry in ROOT.iterdir():
        if entry.name in SKIP_DIRS:
            continue
        if entry.is_dir():
            names.add(entry.name)
        elif entry.suffix == ".py":
            names.add(entry.stem)
    return names


def _imported_top_level() -> dict[str, set[str]]:
    """扫描项目代码里所有 import 的顶层模块名 → 出现在哪些文件。"""
    found: dict[str, set[str]] = {}
    for path in ROOT.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.setdefault(alias.name.split(".")[0], set()).add(path.name)
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # 相对导入
                    continue
                if node.module:
                    found.setdefault(node.module.split(".")[0], set()).add(path.name)
    return found


def test_requirements_file_is_not_empty():
    assert _declared_distributions(), "requirements.txt 解析结果为空，格式可能有问题"


def test_all_third_party_imports_are_declared():
    declared = _declared_distributions()
    local = _local_modules()
    stdlib = set(sys.stdlib_module_names)

    missing = {
        module: sorted(files)
        for module, files in _imported_top_level().items()
        if module not in stdlib
        and module not in local
        and ALIASES.get(module, module).lower() not in declared
    }
    assert not missing, f"requirements.txt 缺少代码中用到的依赖: {missing}"


def test_declared_requirements_are_installed():
    missing = []
    for dist in sorted(_declared_distributions()):
        try:
            dist_version(dist)
        except PackageNotFoundError:
            missing.append(dist)
    assert not missing, f"这些依赖已声明但未安装: {missing}（请 pip install -r requirements.txt）"
