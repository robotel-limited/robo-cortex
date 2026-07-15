import pytest

from robo_cortex.cli._output import format_status


class _FakeStream:
    def __init__(self, tty: bool):
        self._tty = tty

    def isatty(self):
        return self._tty


def test_format_status_active_is_green_when_tty(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    result = format_status("active", stream=_FakeStream(True))
    assert result == "\033[32mactive\033[0m"


@pytest.mark.parametrize("status", ["provisional", "needs_review"])
def test_format_status_review_statuses_are_yellow_when_tty(monkeypatch, status):
    monkeypatch.delenv("NO_COLOR", raising=False)
    result = format_status(status, stream=_FakeStream(True))
    assert result == f"\033[33m{status}\033[0m"


@pytest.mark.parametrize(
    "status", ["superseded", "invalidated", "abandoned", "archived"]
)
def test_format_status_terminal_statuses_are_red_when_tty(monkeypatch, status):
    monkeypatch.delenv("NO_COLOR", raising=False)
    result = format_status(status, stream=_FakeStream(True))
    assert result == f"\033[31m{status}\033[0m"


def test_format_status_unknown_status_passes_through_uncolored(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    result = format_status("some_future_status", stream=_FakeStream(True))
    assert result == "some_future_status"


def test_format_status_no_color_when_not_tty(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert format_status("active", stream=_FakeStream(False)) == "active"


def test_format_status_no_color_when_NO_COLOR_set(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    assert format_status("active", stream=_FakeStream(True)) == "active"


def test_format_status_no_color_when_NO_COLOR_present_but_empty(monkeypatch):
    # no-color.org: disable on presence of the variable, regardless of value.
    monkeypatch.setenv("NO_COLOR", "")
    assert format_status("active", stream=_FakeStream(True)) == "active"


def test_format_status_width_pads_before_coloring(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    result = format_status("active", width=13, stream=_FakeStream(True))
    assert result == f"\033[32m{'active':<13s}\033[0m"


def test_format_status_width_pads_without_color(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    result = format_status("active", width=13, stream=_FakeStream(False))
    assert result == f"{'active':<13s}"


def test_format_status_defaults_to_stdout_when_stream_omitted(monkeypatch, capsys):
    # No explicit stream -- falls back to sys.stdout, which pytest's capsys
    # replaces with a non-tty object, so this should never raise and never color.
    monkeypatch.delenv("NO_COLOR", raising=False)
    result = format_status("active")
    assert result == "active"
