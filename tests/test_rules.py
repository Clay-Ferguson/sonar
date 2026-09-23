"""AGENTS.md rules that can be checked by reading the source.

Each of these is a rule a well-meaning change could break without any
behavioral test noticing until a user did: a hand-built button wearing the
desktop theme, or a command line handed to a shell. The source is parsed
rather than grepped, so a mention in a comment or a docstring is not a hit.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parent.parent / "sonarex"
SOURCES = sorted(PACKAGE.glob("*.py"))


def _calls(path: Path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call):
            yield node


def _name(func: ast.expr) -> str:
    """`QPushButton` for `QPushButton(...)`, `os.system` for `os.system(...)`."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return f"{_name(func.value)}.{func.attr}"
    return ""


def test_the_package_has_sources():
    assert len(SOURCES) > 10  # a wrong PACKAGE path would pass everything below


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_every_button_comes_from_style(path):
    """Every button is made by `style.action_button()` or `icon_button()`;
    one built directly wears the desktop theme instead of the app's."""
    if path.name == "style.py":
        return
    built = [
        call.lineno for call in _calls(path) if _name(call.func).endswith("QPushButton")
    ]
    assert built == [], f"QPushButton(...) built directly at {path.name} lines {built}"


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_nothing_runs_through_a_shell(path):
    """ugrep, find and the user's Open command all run as argv lists: the
    command comes from a text field, so a shell would make it an injection."""
    offenders = []
    for call in _calls(path):
        if _name(call.func) in ("os.system", "os.popen"):
            offenders.append(call.lineno)
        for keyword in call.keywords:
            shell_on = not (
                isinstance(keyword.value, ast.Constant) and keyword.value.value is False
            )
            if keyword.arg == "shell" and shell_on:
                offenders.append(call.lineno)
    assert offenders == [], f"shell use in {path.name} at lines {offenders}"
