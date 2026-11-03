import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"


def _contract(text):
    forms = []
    for form in re.findall(r"<form\b([^>]*)>(.*?)</form>", text, re.S | re.I):
        attrs, body = form
        action = re.search(r'\baction="([^"]*)"', attrs, re.I)
        method = re.search(r'\bmethod="([^"]*)"', attrs, re.I)
        names = tuple(sorted(re.findall(r'\bname="([^"]+)"', body, re.I)))
        forms.append((
            action.group(1) if action else "",
            (method.group(1) if method else "get").lower(),
            names,
        ))

    hrefs = set()
    for href in re.findall(r'\bhref="([^"]*)"', text, re.I):
        if not href.startswith(("#", "http://", "https://")):
            hrefs.add(href)
    hrefs.update(re.findall(r"url_for\(\s*['\"]([^'\"]+)['\"]", text))
    return sorted(forms), sorted(hrefs)


def _head_template(path):
    result = subprocess.run(
        ["git", "show", f"HEAD:templates/{path.name}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def test_ui_contract_matches_previous_templates():
    for path in sorted(TEMPLATES.glob("*.html")):
        assert _contract(path.read_text(encoding="utf-8")) == _contract(
            _head_template(path)
        ), path.name


def test_templates_have_no_inline_css_blocks_or_style_attributes():
    for path in TEMPLATES.glob("*.html"):
        text = path.read_text(encoding="utf-8")
        assert "<style" not in text.lower(), path.name
        assert not re.search(r"\sstyle\s*=", text, re.I), path.name
