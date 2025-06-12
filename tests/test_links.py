import re
from pathlib import Path


def test_markdown_links_exist():
    docs_dir = Path(__file__).resolve().parent.parent / "docs"
    pattern = re.compile(r"\[[^\]]+\]\((?!https?://)([^)]+)\)")
    broken_links = []

    for md_file in docs_dir.rglob("*.md"):
        content = md_file.read_text(encoding="utf-8")
        for match in pattern.finditer(content):
            link = match.group(1)
            path_str = link.split("#", 1)[0].strip()
            if not path_str:
                continue
            resolved = (md_file.parent / path_str)
            if not resolved.exists():
                broken_links.append(f"{md_file}:{link}")

    assert not broken_links, "Broken links found:\n" + "\n".join(broken_links)
