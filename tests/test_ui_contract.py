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
        actual = _contract(path.read_text(encoding="utf-8"))
        expected = _contract(_head_template(path))
        if path.name == "teacher_management.html":
            assert actual == expected
        elif path.name == "add_subject.html":
            assert actual[1] == expected[1]
            assert actual[0] == [(
                "{{ url_for('save_subject') }}",
                "post",
                ("credits", "csrf_token", "department", "semester", "subject_code", "subject_name"),
            )]
        elif path.name == "edit_subject.html":
            assert actual[1] == expected[1]
            assert actual[0] == [(
                "/update_subject/{{ subject['subject_id'] }}",
                "post",
                ("credits", "csrf_token", "department", "semester", "subject_code", "subject_name"),
            )]
        elif path.name == "teacher_dashboard.html":
            assert actual == expected
        elif path.name == "subjects.html":
            assert actual[1] == expected[1]
            assert actual[0] == [
                ("/delete_subject/{{ s['subject_id'] }}", "post", ("csrf_token",)),
                ("/subjects", "get", ("department", "search")),
            ]
        elif path.name == "admin_fees_pending.html":
            assert actual[1] == expected[1]
            assert actual[0] == [(
                "{{ url_for('assign_fees') }}",
                "post",
                ("csrf_token", "exam_fee", "exam_type", "registration_date", "semester"),
            )]
        elif path.name == "student.html":
            assert actual == expected
        else:
            assert actual == expected, path.name


def test_templates_have_no_inline_css_blocks_or_style_attributes():
    for path in TEMPLATES.glob("*.html"):
        text = path.read_text(encoding="utf-8")
        assert "<style" not in text.lower(), path.name
        assert not re.search(r"\sstyle\s*=", text, re.I), path.name
