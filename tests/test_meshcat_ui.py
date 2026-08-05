from __future__ import annotations

import pytest

from twin_lab import meshcat_ui


class _FakeMeshcat:
    def __init__(self, port: int = 7000) -> None:
        self._port = port

    def port(self) -> int:
        return self._port

    def web_url(self) -> str:  # pragma: no cover - present only to catch accidental use
        raise AssertionError("announce_viewer must not report the bound host as the URL")


def test_announce_viewer_prints_a_localhost_url(capsys, monkeypatch) -> None:
    """VS Code spots the viewer by this URL, so losing it costs the open-in-browser prompt."""

    monkeypatch.setattr(meshcat_ui, "wsl_ipv4_address", lambda: None)

    meshcat_ui.announce_viewer("Collision viewer", _FakeMeshcat(7001))

    assert capsys.readouterr().out == "Collision viewer: http://localhost:7001\n"


def test_announce_viewer_adds_the_lan_url_under_wsl(capsys, monkeypatch) -> None:
    monkeypatch.setattr(meshcat_ui, "wsl_ipv4_address", lambda: "172.28.1.5")

    meshcat_ui.announce_viewer("Collision viewer", _FakeMeshcat())

    out = capsys.readouterr().out.splitlines()
    assert out[0] == "Collision viewer: http://localhost:7000"
    assert out[1] == "From another machine: http://172.28.1.5:7000"


def test_wsl_ipv4_address_is_none_off_wsl(monkeypatch) -> None:
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)

    assert meshcat_ui.wsl_ipv4_address() is None


def test_viewer_params_bind_the_ipv4_wildcard() -> None:
    """An IPv6-wildcard bind never reaches /proc/net/tcp, where VS Code looks for servers."""

    pytest.importorskip("pydrake")

    assert meshcat_ui.viewer_params().host == "0.0.0.0"
    assert meshcat_ui.viewer_params().show_stats_plot is False
    assert meshcat_ui.viewer_params(show_stats_plot=True).show_stats_plot is True
