"""Shared fixtures. Tests never import mflux, mlx, torch or diffusers for real."""
from __future__ import annotations

import pytest

from medimg.engines.fake_engine import FakeEngine


@pytest.fixture
def fake_mflux(monkeypatch):
    """Install stub mflux/mlx modules; returns the recorded calls list[tuple[str, dict]]."""
    from tests.stubs import mflux_stub
    calls = mflux_stub.install(monkeypatch)
    yield calls  # monkeypatch removes the sys.modules entries afterwards


@pytest.fixture
def fake_diffusers(monkeypatch):
    """Install stub torch/diffusers modules; returns the recorded calls list."""
    from tests.stubs import diffusers_stub
    calls = diffusers_stub.install(monkeypatch)
    yield calls


@pytest.fixture
def output_root(tmp_path):
    root = tmp_path / "output_root"
    root.mkdir()
    return root


@pytest.fixture
def fake_engine():
    eng = FakeEngine(step_s=0.0)
    eng.load()
    return eng
