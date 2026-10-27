"""Docs check: every command shown in the docs refers to a real launcher or CLI command."""
from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

from medimg.__main__ import build_parser

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
LAUNCHER_STEMS = {"setup": "setup", "start": "serve", "assess": "assess", "selftest": "selftest"}
PREFIXES = ("python -m medimg", "uv run", "./setup", "./start", "./assess", "./selftest",
            "setup.bat", "start.bat", "assess.bat", "selftest.bat",
            ".\\setup.bat", ".\\start.bat", ".\\assess.bat", ".\\selftest.bat")
EXPECTED_DOCS = ["SETUP_MAC", "SETUP_WINDOWS_NVIDIA", "SETUP_LINUX_NVIDIA", "USING_THE_SHEET", "HANDOFF",
                 "TROUBLESHOOTING", "PROMPTING_GUIDE", "SAFETY_AND_LICENCES", "ARCHITECTURE", "FUTURE", "SETUP_WINDOWS_SDCPP", "TEST_MACHINES"]


def fenced_lines(path: Path):
    inside = False
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if raw.strip().startswith("```"):
            inside = not inside
            continue
        if inside:
            yield n, raw.strip()


def doc_commands():
    for path in DOCS:
        for n, line in fenced_lines(path):
            if line.startswith(PREFIXES):
                yield pytest.param(path, n, line, id=f"{path.name}:{n}")


def parse_cli(args: list[str], where: str) -> None:
    parser = build_parser()
    try:
        ns = parser.parse_args(args)
    except SystemExit as e:  # argparse prints its own error to stderr
        raise AssertionError(f"{where}: not a valid medimg command line: {args}") from e
    assert ns.command, f"{where}: no subcommand in {args}"


def check_launcher(name: str, rest: list[str], where: str) -> None:
    stem = name.split(".")[0]
    assert stem in LAUNCHER_STEMS, f"{where}: unknown launcher {name}"
    assert (ROOT / name).is_file(), f"{where}: launcher file {name} does not exist"
    parse_cli([LAUNCHER_STEMS[stem], *rest], where)


@pytest.mark.parametrize("path,n,line", list(doc_commands()))
def test_command_is_real(path, n, line):
    where = f"{path.name}:{n}"
    tokens = shlex.split(line.replace(".\\", "./", 1) if line.startswith(".\\") else line)
    first = tokens[0]
    if line.startswith("python -m medimg"):
        parse_cli(tokens[3:], where)
    elif line.startswith("uv run"):
        rest = [t for t in tokens[2:] if t != "--no-sync"]
        if rest[:3] == ["python", "-m", "medimg"]:
            parse_cli(rest[3:], where)
        else:
            assert rest[0] == "pytest", f"{where}: unsupported uv run command {line}"
    else:
        check_launcher(first[2:] if first.startswith(("./", ".\\")) else first, tokens[1:], where)


BARE_BAT = re.compile(r"(?<![.\\\w-])(?:setup|start|assess|selftest)\.bat\b")


def test_windows_docs_have_no_bare_bat_commands():
    """PowerShell needs .\\name.bat; allow bare names only when double-clicking or naming the file."""
    for path in DOCS:
        for n, line in fenced_lines(path):
            assert not BARE_BAT.match(line), f"{path.name}:{n}: bare .bat command (use .\\): {line}"
        for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for m in BARE_BAT.finditer(raw):
                before = raw[:m.start()].lower()
                ok = before.rstrip("` ").endswith(("double-click", "shows")) or "dir" in before[-30:] \
                    or "double-click" in before[-40:]
                assert ok, f"{path.name}:{n}: bare {m.group(0)} (use .\\{m.group(0)} for PowerShell)"


def test_docs_exist_and_commands_found():
    for stem in EXPECTED_DOCS:
        assert (ROOT / "docs" / f"{stem}.md").is_file(), stem
    assert (ROOT / "README.md").is_file()
    assert len(list(doc_commands())) >= 8, "the docs should show real commands"


def test_launcher_files_exist():
    for stem in LAUNCHER_STEMS:
        for ext in ("command", "sh", "bat"):
            assert (ROOT / f"{stem}.{ext}").is_file(), f"{stem}.{ext}"


def test_readme_quick_start_has_five_numbered_steps():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    section = text.split("## Quick start", 1)[1].split("\n## ", 1)[0]
    numbers = re.findall(r"^(\d+)\. \*\*", section, flags=re.M)
    assert numbers == ["1", "2", "3", "4", "5"]
    assert "image_prompts_sample.xlsx" in section and "Gallery" in section
    for stem in EXPECTED_DOCS:
        assert f"docs/{stem}.md" in text, f"README does not link {stem}"


@pytest.mark.parametrize("name", ["SETUP_WINDOWS_NVIDIA", "SETUP_LINUX_NVIDIA"])
def test_nvidia_docs_have_banner_and_driver_check(name):
    text = (ROOT / "docs" / f"{name}.md").read_text(encoding="utf-8")
    assert "unverified on real hardware" in text.lower()
    assert "570" in text and "nvidia-smi" in text


def test_windows_doc_mentions_long_paths():
    text = (ROOT / "docs" / "SETUP_WINDOWS_NVIDIA.md").read_text(encoding="utf-8")
    assert "long paths" in text.lower()


def test_troubleshooting_has_required_rows():
    text = (ROOT / "docs" / "TROUBLESHOOTING.md").read_text(encoding="utf-8")
    rows = [r.lower() for r in text.splitlines() if r.startswith("|") and not r.startswith("|---")]
    for needle in ("out of memory", "port in use", "model not found offline", "sheet rejected",
                   "cuda not available", "slow generation", "windows path too long"):
        assert any(r.lstrip("| ").startswith(needle) for r in rows), f"missing row: {needle}"


def test_safety_doc_covers_licences_and_rules():
    text = (ROOT / "docs" / "SAFETY_AND_LICENCES.md").read_text(encoding="utf-8")
    assert "Apache 2.0" in text and "other" in text
    assert "Tongyi-MAI/Z-Image-Turbo" in text and "filipstrand/Z-Image-Turbo-mflux-4bit" in text
    lower = text.lower()
    for needle in ("adults only", "likeness", "clinician", "eu ai act", "127.0.0.1", "no network"):
        assert needle in lower, needle


def test_usage_doc_lists_every_column():
    text = (ROOT / "docs" / "USING_THE_SHEET.md").read_text(encoding="utf-8")
    for col in ("Subject", "Unit", "Lecture", "Image Prompt", "Image Name", "Status", "Size", "Seed"):
        assert f"| {col} |" in text, col
    for status in ("pending", "done", "failed", "blocked", "invalid"):
        assert f"| {status} |" in text, status


def test_handoff_rule_and_future_items():
    handoff = (ROOT / "docs" / "HANDOFF.md").read_text(encoding="utf-8")
    assert "only one person" in handoff.lower()
    assert len(re.findall(r"^\d\. \*\*", handoff, flags=re.M)) == 5
    future = (ROOT / "docs" / "FUTURE.md").read_text(encoding="utf-8").lower()
    for needle in ("catalogue", "model selection", "image-to-image", "controlnet", "zip export", "research"):
        assert needle in future, needle


def test_readme_table_has_no_nvidia_column():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    header = next(r for r in text.splitlines() if r.startswith("| | Mac"))
    assert "without NVIDIA" in header
    assert "5-6 min" in text and "docs/SETUP_WINDOWS_SDCPP.md" in text


def test_sdcpp_doc_shows_engine_flags():
    text = (ROOT / "docs" / "SETUP_WINDOWS_SDCPP.md").read_text(encoding="utf-8")
    assert "--engine sdcpp" in text and "--engine auto" in text
    assert "More info" in text and "Run anyway" in text and "com.apple.quarantine" in text
    for link in ("TROUBLESHOOTING.md", "HARDWARE_ALTERNATIVES.md"):
        assert link in text


@pytest.mark.parametrize("name", ["SETUP_WINDOWS_NVIDIA", "SETUP_LINUX_NVIDIA"])
def test_nvidia_docs_point_to_sdcpp(name):
    assert "SETUP_WINDOWS_SDCPP.md" in (ROOT / "docs" / f"{name}.md").read_text(encoding="utf-8")


def test_sdcpp_doc_linux_and_windows_window_claims():
    text = (ROOT / "docs" / "SETUP_WINDOWS_SDCPP.md").read_text(encoding="utf-8")
    assert "Ubuntu 24.04" in text and "22.04 or newer" not in text
    assert "Stopped with an error" in text and "stays open. It" not in text
    assert "<path to sd-cli>" not in text


def _read(*parts):
    return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")


def test_test_machines_doc_content():
    text = _read("docs", "TEST_MACHINES.md")
    lower = text.lower()
    for needle in ("medimg-lab", "self-hosted", "security", "Run workflow", "artifact", "GPU",
                   "ARCHITECTURE.md", "real-run"):
        assert needle.lower() in lower, needle
    windows = text.split("Windows", 1)[1]
    assert re.search(r"^1\. ", windows, flags=re.M) and re.search(r"^6\. ", windows, flags=re.M)
    mac = re.split(r"^#+ .*Mac.*$", text, flags=re.M)
    assert len(mac) > 1, "no Mac registration section"
    assert re.search(r"^1\. ", mac[1], flags=re.M) and "./run.sh" in mac[1]


def test_architecture_has_test_strategy():
    text = _read("docs", "ARCHITECTURE.md")
    assert "## Test strategy" in text and "anatomy" in text.lower()
    for needle in ("device_proven", "failed_devices", "MEDIMG_PROFILE_PATH", "e2e_check"):
        assert needle in text, needle


def test_readme_points_to_selftest():
    text = _read("README.md")
    assert "selftest" in text and "docs/TEST_MACHINES.md" in text
    assert "## New computer? Run the self-test" in text


def test_troubleshooting_has_selftest_rows():
    text = _read("docs", "TROUBLESHOOTING.md")
    rows = [r.lstrip("| ").lower() for r in text.splitlines() if r.startswith("|")]
    for needle in ("self-test says nothing to test", "self-test timed out",
                   "the image program crashed (code 0xc0000", "this processor type is not supported (arm)"):
        assert any(r.startswith(needle) for r in rows), needle
    assert "--retry-gpu" in text
