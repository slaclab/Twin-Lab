from __future__ import annotations

import json
import webbrowser

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
    """The printed URL is the fallback whenever the browser cannot be launched."""

    monkeypatch.setattr(meshcat_ui, "wsl_ipv4_address", lambda: None)
    monkeypatch.setattr(meshcat_ui, "open_in_browser", lambda url: None)

    meshcat_ui.announce_viewer("Collision viewer", _FakeMeshcat(7001))

    assert capsys.readouterr().out == "Collision viewer: http://localhost:7001\n"


def test_announce_viewer_opens_the_localhost_url(monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(meshcat_ui, "wsl_ipv4_address", lambda: None)
    monkeypatch.setattr(meshcat_ui, "open_in_browser", opened.append)

    meshcat_ui.announce_viewer("Collision viewer", _FakeMeshcat(7002))

    assert opened == ["http://localhost:7002"]


def test_announce_viewer_can_leave_the_browser_alone(monkeypatch) -> None:
    monkeypatch.setattr(meshcat_ui, "wsl_ipv4_address", lambda: None)
    monkeypatch.setattr(
        meshcat_ui,
        "open_in_browser",
        lambda url: pytest.fail("open_browser=False must not launch a browser"),
    )

    meshcat_ui.announce_viewer("Collision viewer", _FakeMeshcat(), open_browser=False)


def test_open_in_browser_hands_wsl_urls_to_windows(monkeypatch) -> None:
    """WSL has no Linux browser, so the URL has to cross to the Windows default one."""

    calls: list[list[str]] = []
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu-26.04")
    monkeypatch.setattr(
        meshcat_ui.shutil,
        "which",
        lambda name: "/mnt/c/WINDOWS/explorer.exe" if name == "explorer.exe" else None,
    )
    monkeypatch.setattr(meshcat_ui.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    monkeypatch.setattr(
        meshcat_ui.webbrowser,
        "open",
        lambda url: pytest.fail("must not fall back to the Linux browser under WSL"),
    )

    meshcat_ui.open_in_browser("http://localhost:7000")

    assert calls == [["/mnt/c/WINDOWS/explorer.exe", "http://localhost:7000"]]


def test_open_in_browser_survives_a_missing_browser(monkeypatch) -> None:
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)

    def refuse(url: str) -> bool:
        raise webbrowser.Error("no runnable browser")

    monkeypatch.setattr(meshcat_ui.webbrowser, "open", refuse)

    meshcat_ui.open_in_browser("http://localhost:7000")


def test_announce_viewer_adds_the_lan_url_under_wsl(capsys, monkeypatch) -> None:
    monkeypatch.setattr(meshcat_ui, "wsl_ipv4_address", lambda: "172.28.1.5")
    monkeypatch.setattr(meshcat_ui, "open_in_browser", lambda url: None)

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


def test_the_page_is_told_the_same_view_directions_python_frames_with() -> None:
    """A second copy of the directions in the JavaScript would be free to drift."""

    settings = json.loads(meshcat_ui.VIEW_SETTINGS_JS.split("=", 1)[1].rstrip(";"))

    assert settings["isometric"] == list(meshcat_ui.ISOMETRIC_DIRECTION)
    assert settings["trimetric"] == list(meshcat_ui.TRIMETRIC_DIRECTION)
    assert settings["fit"] == meshcat_ui.FRAMING_DISTANCE


def test_the_patched_page_carries_the_view_cube(tmp_path) -> None:
    source = tmp_path / "meshcat.html"
    source.write_text("<head><title>Drake MeshCat</title></head><body></body>", encoding="utf-8")

    html = meshcat_ui._patched_html(source)

    assert "twinlab-view-cube" in html
    # Both later scripts read these, so they have to be in the page ahead of them.
    assert html.index("TWINLAB_VIEWS =") < html.index("window.twinlab.modelBox =")
    assert html.index("window.twinlab.modelBox =") < html.index("window.twinlab.modelBox()")
