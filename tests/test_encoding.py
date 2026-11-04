from pathlib import Path
import os
import re
import tempfile

import config
from support import create_test_database


ROOT = Path(__file__).resolve().parents[1]
TEST_DATABASE = Path(tempfile.mkdtemp(prefix="encoding-tests-")) / "student.db"
create_test_database(TEST_DATABASE)
config.DATABASE = str(TEST_DATABASE)
os.environ["STUDENT_DB_PATH"] = str(TEST_DATABASE)
os.environ["SECRET_KEY"] = "encoding-test-secret"
os.environ["PYTHON_DOTENV_DISABLED"] = "1"

from app import create_app


MARKERS = tuple(chr(value) for value in (0xC3, 0xE2, 0xC2, 0xF0, 0x178, 0xFFFD))
EMOJI = re.compile("[\\U0001F300-\\U0001FAFF\\U00002600-\\U000027BF\\U0001F1E6-\\U0001F1FF]")


def test_templates_and_css_are_utf8_without_mojibake():
    paths = list((ROOT / "templates").glob("**/*.html"))
    paths.extend((ROOT / "static").glob("**/*.css"))
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert not any(marker in text for marker in MARKERS), path


def test_login_pages_have_no_replacement_character():
    client = create_app({"TESTING": True}).test_client()
    for path in ("/admin/login", "/student/login"):
        assert "\ufffd" not in client.get(path).get_data(as_text=True)


def test_admin_dashboard_has_no_emoji_code_points():
    application = create_app({"TESTING": True})
    client = application.test_client()
    with client.session_transaction() as session:
        session["username"] = "admin"
        session["role"] = "admin"
    assert not EMOJI.search(client.get("/admin").get_data(as_text=True))
