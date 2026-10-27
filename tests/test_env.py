import os

from backend.app.core.env import load_env, parse_env


def test_parse_env_skips_comments_and_strips_quotes():
    text = '# comment\n\nA=1\nexport B="two words"\nC=\'x\'\nnot a pair\nD=a=b\n'
    assert parse_env(text) == {"A": "1", "B": "two words", "C": "x", "D": "a=b"}


def test_load_env_does_not_override(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("EM_TEST_SET=from_file\nEM_TEST_NEW=new\n")
    monkeypatch.setenv("EM_TEST_SET", "from_shell")
    monkeypatch.delenv("EM_TEST_NEW", raising=False)
    load_env(env)
    assert os.environ["EM_TEST_SET"] == "from_shell"
    assert os.environ["EM_TEST_NEW"] == "new"
    monkeypatch.delenv("EM_TEST_NEW")


def test_load_env_missing_file_is_noop(tmp_path):
    load_env(tmp_path / "nope.env")
