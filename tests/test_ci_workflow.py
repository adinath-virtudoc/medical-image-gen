from pathlib import Path

import yaml

WF = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "tests.yml"


def test_workflow():
    data = yaml.safe_load(WF.read_text(encoding="utf-8"))
    job = next(iter(data["jobs"].values()))
    assert set(job["strategy"]["matrix"]["os"]) == {"ubuntu-latest", "windows-latest"}
    steps = job["steps"]
    assert any("astral-sh/setup-uv" in s.get("uses", "") for s in steps)
    runs = [s.get("run", "") for s in steps]
    assert any(r.strip() == "uv sync" for r in runs)
    assert any("uv run pytest" in r for r in runs)
    assert not any("macos" in str(o) for o in job["strategy"]["matrix"]["os"])
