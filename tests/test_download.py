import os
import sys
import types
from pathlib import Path

import pytest

from medimg import config, download


def _install_hf(monkeypatch, snap=None, hub=None):
    mod = types.ModuleType("huggingface_hub")
    mod.calls = []

    def snapshot_download(repo_id, **kw):
        mod.calls.append(("snapshot", repo_id, kw))
        if snap is not None:
            return snap(repo_id, kw)
        return "/fake/snapshot"

    def hf_hub_download(repo_id, filename, **kw):
        mod.calls.append(("file", repo_id, filename, kw))
        if hub is not None:
            return hub(repo_id, filename, kw)
        return "/fake/" + filename

    mod.snapshot_download = snapshot_download
    mod.hf_hub_download = hf_hub_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", mod)
    return mod


def test_mflux_cached_uses_local_files_only_and_pinned_revision(monkeypatch):
    hf = _install_hf(monkeypatch)
    assert download.mflux_cached() == Path("/fake/snapshot")
    _, repo, kw = hf.calls[0]
    assert repo == config.MFLUX_MODEL_ID
    assert kw == {"revision": config.MFLUX_MODEL_REVISION, "allow_patterns": download.MFLUX_PATTERNS,
                  "local_files_only": True}


def test_mflux_cached_none_when_missing(monkeypatch):
    def boom(repo, kw):
        raise RuntimeError("not cached")
    _install_hf(monkeypatch, snap=boom)
    assert download.mflux_cached() is None


def test_download_mflux_reuses_cache(monkeypatch):
    hf = _install_hf(monkeypatch)
    msgs = []
    assert download.download_mflux(msgs.append) == Path("/fake/snapshot")
    assert any("already done" in m for m in msgs)
    assert all(c[2].get("local_files_only") for c in hf.calls)


def test_download_mflux_downloads_when_missing(monkeypatch):
    def snap(repo, kw):
        if kw.get("local_files_only"):
            raise RuntimeError("no")
        return "/fake/new"
    hf = _install_hf(monkeypatch, snap=snap)
    msgs = []
    assert download.download_mflux(msgs.append) == Path("/fake/new")
    assert hf.calls[-1][2] == {"revision": config.MFLUX_MODEL_REVISION,
                               "allow_patterns": download.MFLUX_PATTERNS}


def test_download_mflux_failure_is_plain_error(monkeypatch):
    def snap(repo, kw):
        raise OSError("offline")
    _install_hf(monkeypatch, snap=snap)
    from medimg.errors import ModelUnavailable
    with pytest.raises(ModelUnavailable) as ei:
        download.download_mflux(lambda m: None)
    assert ei.value.fix


def test_gguf_q8_allow_patterns_exclude_transformer_shards(monkeypatch):
    def snap(repo, kw):
        if kw.get("local_files_only"):
            raise RuntimeError("not cached")
        return "/fake/diff"
    hf = _install_hf(monkeypatch, snap=snap, hub=lambda r, f, kw: (_ for _ in ()).throw(RuntimeError("no"))
                     if kw.get("local_files_only") else "/fake/" + f)
    download.download_diffusers("gguf_q8_offload", lambda m: None)
    real = [c for c in hf.calls if c[0] == "snapshot" and not c[2].get("local_files_only")]
    assert len(real) == 1
    kw = real[0][2]
    assert kw["revision"] == config.DIFFUSERS_MODEL_REVISION
    from fnmatch import fnmatch
    shard = "transformer/diffusion_pytorch_model-00001-of-00003.safetensors"
    assert not any(fnmatch(shard, p) for p in kw["allow_patterns"]) or any(
        fnmatch(shard, p) for p in kw["ignore_patterns"])
    assert "transformer/*.safetensors" in kw["ignore_patterns"]
    assert any(fnmatch("text_encoder/model-00001-of-00003.safetensors", p) for p in kw["allow_patterns"])
    files = [c for c in hf.calls if c[0] == "file" and not c[3].get("local_files_only")]
    assert [(c[1], c[2]) for c in files] == [(config.GGUF_REPO_ID, config.GGUF_FILES["q8_0"][0])]


def test_full_modes_download_whole_repo(monkeypatch):
    def snap(repo, kw):
        if kw.get("local_files_only"):
            raise RuntimeError("not cached")
        return "/fake/diff"
    hf = _install_hf(monkeypatch, snap=snap)
    download.download_diffusers("model_cpu_offload", lambda m: None)
    kw = [c for c in hf.calls if not c[2].get("local_files_only")][0][2]
    assert "allow_patterns" not in kw and "ignore_patterns" not in kw
    assert not [c for c in hf.calls if c[0] == "file"]


def test_unknown_mode(monkeypatch):
    _install_hf(monkeypatch)
    from medimg.errors import ModelUnavailable
    with pytest.raises(ModelUnavailable):
        download.download_diffusers("bogus", lambda m: None)


@pytest.mark.skipif(sys.platform != "darwin" or os.uname().machine != "arm64",
                    reason="Apple silicon only")
def test_real_cache_snapshot_offline(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    root = Path.home() / ".cache/huggingface/hub/models--filipstrand--Z-Image-Turbo-mflux-4bit"
    if not root.exists():
        pytest.skip("weights not in the Hugging Face cache")
    path = download.mflux_cached()
    assert path is not None and path.is_dir()
    assert path.name == config.MFLUX_MODEL_REVISION
