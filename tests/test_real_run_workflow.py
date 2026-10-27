import re
from pathlib import Path

import yaml

WF = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "real-run.yml"
TEXT = WF.read_text(encoding="utf-8")
DATA = yaml.safe_load(TEXT)
SHAS = {
    "actions/checkout": "3d3c42e5aac5ba805825da76410c181273ba90b1",
    "astral-sh/setup-uv": "1c37ad07a6a961277cf70c0d37d6f313000f5884",
    "actions/cache/restore": "55cc8345863c7cc4c66a329aec7e433d2d1c52a9",
    "actions/cache/save": "55cc8345863c7cc4c66a329aec7e433d2d1c52a9",
    "actions/upload-artifact": "cf430e030ddbb5b0abf93d22962f4752f3646cd9",
}
CPU = DATA["jobs"]["cpu-real-run"]
LAB = DATA["jobs"]["self-hosted-real-run"]


def step(job, sid):
    return next(s for s in job["steps"] if s.get("id") == sid)


def runs(job):
    return "\n".join(s.get("run", "") for s in job["steps"])


def test_triggers_exact():
    on = DATA.get("on", DATA.get(True))
    assert set(on) == {"workflow_dispatch", "schedule"}
    assert set(on["workflow_dispatch"]["inputs"]) == {"target", "selfhosted_tier"}


def test_jobs_exist():
    assert set(DATA["jobs"]) == {"cpu-real-run", "self-hosted-real-run"}


def test_cpu_job():
    assert set(CPU["strategy"]["matrix"]["os"]) == {"windows-latest", "ubuntu-24.04"}
    assert CPU["timeout-minutes"] == 90
    assert CPU["defaults"]["run"]["shell"] == "bash"


def test_lab_job():
    assert LAB["runs-on"] == ["self-hosted", "medimg-lab"]
    assert "workflow_dispatch" in LAB["if"]
    assert LAB["timeout-minutes"] == 240


def test_uses_pinned():
    seen = 0
    for job in (CPU, LAB):
        for s in job["steps"]:
            if "uses" in s:
                seen += 1
                assert re.match(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$", s["uses"]), s["uses"]
                name, sha = s["uses"].split("@")
                assert SHAS[name] == sha
    assert seen >= 8
    assert re.search(r"@[0-9a-f]{40} # v\d+\.\d+\.\d+", TEXT)


def test_cpu_commands():
    assert all(x in step(CPU, "setup")["run"] for x in ("--engine sdcpp", "--tier low", "--yes"))
    assert "tools/e2e_check.py" in step(CPU, "e2e")["run"]
    assert "--engine sdcpp" in step(CPU, "e2e")["run"]
    st = step(CPU, "selftest")["run"]
    assert all(x in st for x in ("selftest", "--quick", "--no-open"))
    assert step(CPU, "cachekey") and step(CPU, "restore")


def test_cache_save_condition():
    save = next(s for s in CPU["steps"] if s.get("uses", "").startswith("actions/cache/save@"))
    assert "steps.setup.outcome == 'success'" in save["if"]
    assert "cache-hit != 'true'" in save["if"]


def test_upload_always():
    for job in (CPU, LAB):
        up = next(s for s in job["steps"] if s.get("uses", "").startswith("actions/upload-artifact@"))
        assert "always()" in up["if"]


def test_env_and_permissions():
    assert DATA["permissions"] == {"contents": "read"}
    for job in (CPU, LAB):
        assert job["env"]["PYTHONUTF8"] == "1"
        assert job.get("permissions", DATA["permissions"]) == {"contents": "read"}


def test_lab_steps_portable():
    for s in LAB["steps"]:
        assert "shell" not in s
        assert "$GITHUB_" not in s.get("run", "")
        assert "$env:" not in s.get("run", "")
    assert "defaults" not in LAB
    setup = step(LAB, "setup")["run"]
    assert "--engine" not in setup and "--tier" not in setup
    assert "selftest" in runs(LAB)
    assert "--quick" not in runs(LAB)


def test_tests_yml_actions_are_sha_pinned():
    import re
    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent / ".github/workflows/tests.yml").read_text()
    uses = re.findall(r"uses:\s*(\S+)", text)
    assert uses
    for u in uses:
        assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", u), u
    assert "contents: read" in text
