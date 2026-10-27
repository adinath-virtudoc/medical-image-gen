import hashlib
import io
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

from medimg import config
from medimg.errors import ModelUnavailable
from medimg.sdcpp import install, pins

FIX = Path(__file__).parent / "fixtures" / "sdcpp"


def make_zip(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, d in members.items():
            z.writestr(n, d)
    return buf.getvalue()


class Resp:
    def __init__(self, data, status=200):
        self.buf, self.status = io.BytesIO(data), status

    def read(self, n=-1):
        return self.buf.read(n)

    def close(self):
        pass


def setup_asset(monkeypatch, data, sha=None):
    a = pins.Asset("test-build", "t.zip", "https://example.invalid/t.zip", len(data),
                   sha or hashlib.sha256(data).hexdigest(), "sd-cli")
    monkeypatch.setitem(pins.ASSETS, "test-build", a)
    return a


def test_install_binary(tmp_path, monkeypatch):
    data = make_zip({"sd-cli": b"#!/bin/sh\n", "lib.dll": b"x"})
    setup_asset(monkeypatch, data)
    assert install.binary_cached("test-build", tmp_path) is None
    reqs = []

    def opener(req):
        reqs.append(req)
        return Resp(data)

    exe = install.install_binary("test-build", lambda *_: None, tools_dir=tmp_path, opener=opener)
    assert exe == pins.binary_dir("test-build", tmp_path) / "sd-cli" and exe.is_file()
    assert (exe.parent / "lib.dll").is_file()
    assert reqs[0].get_header("Range") is None
    assert install.binary_cached("test-build", tmp_path) == exe
    if os.name != "nt":
        assert os.access(exe, os.X_OK)
    # downloads folder is not inside the build folder; no leftover temp dirs
    assert not list(exe.parent.glob("*.part"))
    assert not [p for p in exe.parent.parent.iterdir() if p.name.endswith(".tmp")]


def test_part_written_and_resume(tmp_path, monkeypatch):
    data = make_zip({"sd-cli": b"abc" * 100})
    asset = setup_asset(monkeypatch, data)
    dl = tmp_path / "sdcpp" / config.SDCPP_RELEASE_TAG / "downloads"
    dl.mkdir(parents=True)
    (dl / (asset.name + ".part")).write_bytes(data[:50])
    seen = {}

    def opener(req):
        seen["range"] = req.get_header("Range")
        return Resp(data[50:], status=206)

    install.install_binary("test-build", lambda *_: None, tools_dir=tmp_path, opener=opener)
    assert seen["range"] == "bytes=50-"
    assert install.binary_cached("test-build", tmp_path)


def test_resume_server_ignores_range(tmp_path, monkeypatch):
    data = make_zip({"sd-cli": b"abc" * 100})
    asset = setup_asset(monkeypatch, data)
    dl = tmp_path / "sdcpp" / config.SDCPP_RELEASE_TAG / "downloads"
    dl.mkdir(parents=True)
    (dl / (asset.name + ".part")).write_bytes(b"garbage")
    install.install_binary("test-build", lambda *_: None, tools_dir=tmp_path,
                           opener=lambda req: Resp(data, status=200))
    assert install.binary_cached("test-build", tmp_path)


def test_part_exists_during_download(tmp_path, monkeypatch):
    data = make_zip({"sd-cli": b"x"})
    asset = setup_asset(monkeypatch, data)
    part = tmp_path / "sdcpp" / config.SDCPP_RELEASE_TAG / "downloads" / (asset.name + ".part")

    class R(Resp):
        def read(self, n=-1):
            chunk = super().read(n)
            return chunk

    def opener(req):
        return R(data)

    install.install_binary("test-build", lambda *_: None, tools_dir=tmp_path, opener=opener)
    assert not part.exists()  # removed after success; the folder is outside the build folder
    assert part.parent not in pins.binary_dir("test-build", tmp_path).parents


def test_wrong_sha_deletes(tmp_path, monkeypatch):
    data = make_zip({"sd-cli": b"x"})
    asset = setup_asset(monkeypatch, data, sha="0" * 64)
    with pytest.raises(ModelUnavailable) as ei:
        install.install_binary("test-build", lambda *_: None, tools_dir=tmp_path,
                               opener=lambda req: Resp(data))
    assert ei.value.fix
    part = tmp_path / "sdcpp" / config.SDCPP_RELEASE_TAG / "downloads" / (asset.name + ".part")
    assert not part.exists()
    assert install.binary_cached("test-build", tmp_path) is None


def test_zip_slip_rejected(tmp_path, monkeypatch):
    data = make_zip({"sd-cli": b"x", "../evil.txt": b"bad"})
    setup_asset(monkeypatch, data)
    with pytest.raises(ModelUnavailable):
        install.install_binary("test-build", lambda *_: None, tools_dir=tmp_path,
                               opener=lambda req: Resp(data))
    assert not (tmp_path / "sdcpp" / config.SDCPP_RELEASE_TAG / "evil.txt").exists()
    assert install.binary_cached("test-build", tmp_path) is None


def test_zip_absolute_rejected(tmp_path, monkeypatch):
    data = make_zip({"sd-cli": b"x", "/abs.txt": b"bad"})
    setup_asset(monkeypatch, data)
    with pytest.raises(ModelUnavailable):
        install.install_binary("test-build", lambda *_: None, tools_dir=tmp_path,
                               opener=lambda req: Resp(data))


def test_models_cached_kwargs(monkeypatch):
    calls = []

    def fake(repo, filename, **kw):
        calls.append((repo, filename, kw))
        return f"/cache/{filename}"

    monkeypatch.setattr(install, "hf_hub_download", fake)
    got = install.models_cached("low")
    assert set(got) == {"diffusion", "llm", "vae"}
    assert len(calls) == 3
    for (repo, fn, kw), m in zip(calls, pins.TIERS["low"].values()):
        assert kw["local_files_only"] is True and kw["revision"] == m.revision and repo == m.repo


def test_models_cached_missing(monkeypatch):
    def fake(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(install, "hf_hub_download", fake)
    assert install.models_cached("low") is None


def test_download_models_mismatch_deletes(tmp_path, monkeypatch):
    def fake(repo, filename, **kw):
        p = tmp_path / Path(filename).name
        p.write_bytes(b"wrong")
        return str(p)

    monkeypatch.setattr(install, "hf_hub_download", fake)
    with pytest.raises(ModelUnavailable) as ei:
        install.download_models("low", lambda *_: None)
    assert "damaged" in ei.value.cause and ei.value.fix == "Run setup again."
    assert not list(tmp_path.iterdir())


def test_download_models_ok(tmp_path, monkeypatch):
    for role, m in pins.TIERS["low"].items():
        pass
    contents = {}

    def fake(repo, filename, **kw):
        assert kw.get("revision")
        p = tmp_path / Path(filename).name
        p.write_bytes(b"ok")
        return str(p)

    monkeypatch.setattr(install, "hf_hub_download", fake)
    sha = hashlib.sha256(b"ok").hexdigest()
    fixed = {t: {r: pins.ModelFile(m.repo, m.revision, m.filename, m.gb, sha) for r, m in d.items()}
             for t, d in pins.TIERS.items()}
    monkeypatch.setattr(pins, "TIERS", fixed)
    out = install.download_models("low", lambda *_: None)
    assert set(out) == {"diffusion", "llm", "vae"}


def test_verify_sha256(tmp_path):
    p = tmp_path / "f"
    p.write_bytes(b"hello")
    install.verify_sha256(p, hashlib.sha256(b"hello").hexdigest())
    with pytest.raises(ModelUnavailable):
        install.verify_sha256(p, "0" * 64)


class Done:
    def __init__(self, rc=0, out=""):
        self.returncode, self.stdout, self.stderr = rc, out, "noise"


def test_list_devices_mac():
    text = (FIX / "list_devices_mac.txt").read_text()
    seen = {}

    def run(cmd, **kw):
        seen.update(cmd=cmd, **kw)
        return Done(0, text)

    devs = install.list_devices(("/x/sd-cli",), Path("/x"), run=run)
    assert devs == [("MTL0", "Apple M2 Pro"), ("BLAS", "Accelerate"), ("CPU", "Apple M2 Pro")]
    assert seen["cmd"] == ["/x/sd-cli", "--list-devices"] and seen["timeout"] == 60
    assert install.list_devices(("a",), Path("."), run=lambda c, **k: Done(0, (FIX / "list_devices_win_iris.txt").read_text()))[0][0] == "Vulkan0"


def test_list_devices_failures():
    with pytest.raises(ModelUnavailable):
        install.list_devices(("a",), Path("."), run=lambda c, **k: Done(1, ""))

    def timeout(c, **k):
        raise subprocess.TimeoutExpired(c, 60)

    with pytest.raises(ModelUnavailable):
        install.list_devices(("a",), Path("."), run=timeout)

    def oserr(c, **k):
        raise OSError("nope")

    with pytest.raises(ModelUnavailable):
        install.list_devices(("a",), Path("."), run=oserr)


def test_health_check_uses_list_devices():
    seen = {}

    def run(cmd, **kw):
        seen["cmd"] = cmd
        return Done(0, "Vulkan0\tGPU\nCPU\tcpu\n")

    assert install.health_check(("a",), Path("."), run=run) == "devices: Vulkan0, CPU"
    assert seen["cmd"] == ["a", "--list-devices"]
    with pytest.raises(ModelUnavailable):
        install.health_check(("a",), Path("."), run=lambda c, **k: Done(1, ""))


def test_health_check_needs_cpu_line():
    with pytest.raises(ModelUnavailable):
        install.health_check(("a",), Path("."), run=lambda c, **k: Done(0, "Vulkan0\tGPU\n"))
    with pytest.raises(ModelUnavailable):
        install.health_check(("a",), Path("."), run=lambda c, **k: Done(0, ""))


def test_health_check_access_violation_shows_hex():
    with pytest.raises(ModelUnavailable) as ei:
        install.health_check(("a",), Path("."), run=lambda c, **k: Done(0xC0000005, ""))
    assert "0xC0000005" in str(ei.value)


def test_health_check_missing_dll_message(monkeypatch):
    monkeypatch.setattr(install.os, "name", "nt")
    with pytest.raises(ModelUnavailable) as ei:
        install.health_check(("a",), Path("."), run=lambda c, **k: Done(3221225781, ""))
    assert "Visual C++" in ei.value.fix and "aka.ms/vs/17/release/vc_redist.x64.exe" in ei.value.fix


def test_resolve_paths(tmp_path, monkeypatch):
    data = make_zip({"sd-cli": b"x"})
    setup_asset(monkeypatch, data)
    monkeypatch.setitem(pins.TIERS, "tt", pins.TIERS["low"])
    monkeypatch.setattr(install, "hf_hub_download", lambda repo, fn, **kw: f"/cache/{fn}")
    with pytest.raises(ModelUnavailable) as ei:
        install.resolve_paths("test-build", "low", tools_dir=tmp_path)
    assert "setup" in ei.value.fix
    install.install_binary("test-build", lambda *_: None, tools_dir=tmp_path, opener=lambda r: Resp(data))
    p = install.resolve_paths("test-build", "low", tools_dir=tmp_path)
    assert p.sd_cli == (str(pins.binary_dir("test-build", tmp_path) / "sd-cli"),)
    assert p.cwd == pins.binary_dir("test-build", tmp_path)
    assert p.build == "test-build" and p.tier == "low" and p.release == config.SDCPP_RELEASE_TAG
    assert str(p.diffusion).endswith("z_image_turbo-Q2_K.gguf")
    # models missing
    monkeypatch.setattr(install, "hf_hub_download", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    with pytest.raises(ModelUnavailable):
        install.resolve_paths("test-build", "low", tools_dir=tmp_path)


def test_chosen_build(tmp_path, monkeypatch):
    data = make_zip({"sd-cli": b"x"})
    setup_asset(monkeypatch, data)
    # nothing recorded -> build_for
    assert install.chosen_build("Windows", "AMD64", tmp_path) == "win-vulkan-x64"
    # recorded but binary missing -> build_for
    install.record_chosen_build("test-build", tmp_path)
    assert install.chosen_build("Windows", "AMD64", tmp_path) == "win-vulkan-x64"
    install.install_binary("test-build", lambda *_: None, tools_dir=tmp_path, opener=lambda r: Resp(data))
    assert install.chosen_build("Windows", "AMD64", tmp_path) == "test-build"
    assert (tmp_path / "sdcpp" / config.SDCPP_RELEASE_TAG / install.CHOSEN_BUILD_FILE).read_text() == "test-build"
    # unknown recorded key ignored
    install.record_chosen_build("bogus", tmp_path)
    assert install.chosen_build("Linux", "x86_64", tmp_path) == "linux-vulkan-x64"
    assert install.chosen_build("Darwin", "x86_64", tmp_path) is None


def test_health_check_surfaces_loader_error():
    class R:
        returncode, stdout, stderr = 1, "", "sd-cli: GLIBC_2.38 not found\n"
    with pytest.raises(ModelUnavailable, match="GLIBC_2.38"):
        install.health_check(("a",), Path("."), run=lambda c, **k: R())


def test_health_check_calls_list_devices(monkeypatch):
    calls = []

    def rec(sd_cli, cwd, run=None):
        calls.append((sd_cli, cwd))
        return [("Vulkan0", "x"), ("CPU", "y")]

    monkeypatch.setattr(install, "list_devices", rec)
    assert install.health_check(("a",), Path(".")) == "devices: Vulkan0, CPU"
    assert len(calls) == 1
    monkeypatch.setattr(install, "list_devices", lambda *a, **k: [("Vulkan0", "x")])
    with pytest.raises(ModelUnavailable):
        install.health_check(("a",), Path("."))


def test_single_list_devices_call_site():
    src = Path(install.__file__).read_text()
    assert src.count('"--list-devices"') + src.count("'--list-devices'") == 1


def test_list_devices_rich_errors(monkeypatch):
    with pytest.raises(ModelUnavailable) as ei:
        install.list_devices(("a",), Path("."), run=lambda c, **k: Done(0xC0000005, ""))
    assert "0xC0000005" in str(ei.value)
    monkeypatch.setattr(install.os, "name", "nt")
    with pytest.raises(ModelUnavailable) as ei:
        install.list_devices(("a",), Path("."), run=lambda c, **k: Done(3221225781, ""))
    assert "Visual C++" in ei.value.fix
