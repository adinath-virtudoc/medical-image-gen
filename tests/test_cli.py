import os
import subprocess
import sys
import types

import pytest

from medimg import __main__ as cli


def test_help_lists_commands():
    out = subprocess.run([sys.executable, "-m", "medimg", "--help"], capture_output=True, text=True)
    assert out.returncode == 0
    for c in ("setup", "assess", "serve", "smoke", "selftest"):
        assert c in out.stdout


def test_no_host_flag():
    assert "--host" not in cli.build_parser().format_help()
    for sub in ("serve",):
        with pytest.raises(SystemExit):
            cli.build_parser().parse_args([sub, "--host", "0.0.0.0"])


@pytest.fixture
def mocks(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "x")  # so teardown restores "unset"
    monkeypatch.delenv("HF_HUB_OFFLINE")
    seen = {}
    for cmd, (mod, fn, _) in cli.DISPATCH.items():
        m = types.ModuleType(mod)
        def target(args, cmd=cmd):
            seen[cmd] = (dict(vars(args)), os.environ.get("HF_HUB_OFFLINE"))
            return 0
        setattr(m, fn, target)
        monkeypatch.setitem(sys.modules, mod, m)
    return seen


@pytest.mark.parametrize("cmd,expected", [("serve", "1"), ("smoke", "1"), ("assess", "1"), ("setup", None), ("selftest", "1")])
def test_offline_env(mocks, cmd, expected):
    assert cli.main([cmd]) == 0
    assert mocks[cmd][1] == expected


def test_flags_parse(mocks):
    assert cli.main(["serve", "--port", "9001", "--fake-engine", "--no-browser", "--output-root", "/x"]) == 0
    a = mocks["serve"][0]
    assert a["port"] == 9001 and a["fake_engine"] and a["no_browser"] and a["output_root"] == "/x"
    assert cli.main(["smoke"]) == 0
    assert mocks["smoke"][0]["size"] == "512x512" and mocks["smoke"][0]["steps"] == 4
    assert cli.main(["setup", "--skip-smoke", "--skip-assess", "--yes"]) == 0
    assert cli.main(["assess", "--no-benchmark", "--json"]) == 0


def test_usage_error_exit_2(mocks):
    assert cli.main(["bogus"]) == 2
    assert cli.main([]) == 2


def test_missing_module_clear_message(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "medimg.setup_cmd", None)  # forces ImportError
    monkeypatch.delitem(sys.modules, "medimg.setup_cmd")
    import importlib
    monkeypatch.setattr(importlib, "import_module",
                        lambda n: (_ for _ in ()).throw(ModuleNotFoundError(name=n)))
    assert cli.main(["setup"]) == 1
    assert "not available" in capsys.readouterr().err


def test_medimg_error_printed(monkeypatch, capsys):
    from medimg.errors import Invalid
    m = types.ModuleType("medimg.smoke")
    def boom(args):
        raise Invalid("bad thing.", "do this.")
    m.run = boom
    monkeypatch.setitem(sys.modules, "medimg.smoke", m)
    assert cli.main(["smoke"]) == 1
    err = capsys.readouterr().err
    assert "bad thing." in err and "do this." in err


@pytest.mark.parametrize("cmd", ["setup", "assess", "serve", "smoke", "selftest"])
def test_engine_flag_all_commands(mocks, cmd):
    assert cli.main([cmd]) == 0
    assert mocks[cmd][0]["engine"] is None
    assert cli.main([cmd, "--engine", "sdcpp"]) == 0
    assert mocks[cmd][0]["engine"] == "sdcpp"
    assert cli.main([cmd, "--engine", "auto"]) == 0
    assert mocks[cmd][0]["engine"] == "auto"
    assert cli.main([cmd, "--engine", "bogus"]) == 2


@pytest.mark.parametrize("cmd", ["setup", "assess", "serve", "smoke", "selftest"])
def test_engine_in_help(cmd):
    out = subprocess.run([sys.executable, "-m", "medimg", cmd, "--help"], capture_output=True, text=True)
    assert out.returncode == 0 and "--engine" in out.stdout


def test_new_flags_parse(mocks):
    assert cli.main(["selftest", "--quick", "--all-tiers", "--engine", "sdcpp", "--tier", "mid",
                     "--size", "256x256", "--steps", "2", "--timeout", "60", "--output-root", "/x",
                     "--no-open", "--json", "--fake-engine"]) == 0
    a = mocks["selftest"][0]
    assert a["quick"] and a["all_tiers"] and a["engine"] == "sdcpp" and a["tier"] == "mid"
    assert a["size"] == "256x256" and a["steps"] == 2 and a["timeout"] == 60.0
    assert a["output_root"] == "/x" and a["no_open"] and a["json"] and a["fake_engine"]
    assert cli.main(["selftest"]) == 0
    d = mocks["selftest"][0]
    assert d["size"] == "512x512" and d["steps"] == 4 and d["timeout"] == 1800 and d["tier"] is None
    assert cli.main(["setup", "--tier", "low", "--output-root", "/x"]) == 0
    assert mocks["setup"][0]["tier"] == "low" and mocks["setup"][0]["output_root"] == "/x"
    assert cli.main(["assess", "--tier", "mid", "--retry-gpu"]) == 0
    assert mocks["assess"][0]["tier"] == "mid" and mocks["assess"][0]["retry_gpu"] is True
    assert cli.main(["assess"]) == 0 and mocks["assess"][0]["retry_gpu"] is False
    assert cli.main(["smoke", "--tier", "low"]) == 0
    assert mocks["smoke"][0]["tier"] == "low"
    assert cli.main(["smoke", "--tier", "auto"]) == 0


@pytest.mark.parametrize("argv", [["setup", "--tier", "huge"], ["assess", "--tier", "x"],
                                  ["smoke", "--tier", "x"], ["selftest", "--tier", "auto"]])
def test_bad_tier_exit_2(mocks, argv):
    assert cli.main(argv) == 2
