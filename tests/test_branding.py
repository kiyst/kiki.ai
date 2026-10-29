from pathlib import Path

from kiki.cli import _parser


def test_cli_and_default_data_path_use_kiki_name() -> None:
    parser = _parser()
    arguments = parser.parse_args([])

    assert parser.prog == "kiki"
    assert arguments.database == Path(".kiki/index.sqlite3")


def test_old_brand_is_absent_from_product_text() -> None:
    root = Path(__file__).resolve().parents[1]
    files = [root / "README.md", root / "pyproject.toml"]
    files.extend((root / "src" / "kiki").rglob("*.py"))
    files.extend((root / "docs").rglob("*.md"))
    old_name = "desk" + "ai"

    for path in files:
        assert old_name not in path.read_text(encoding="utf-8").casefold(), path
