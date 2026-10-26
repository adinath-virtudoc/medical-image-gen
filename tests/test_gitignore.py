import fnmatch
from pathlib import Path

GI = Path(__file__).resolve().parent.parent / ".gitignore"
REQUIRED = [".venv/", "venv/", "__pycache__/", "*.pyc", "device_profile.json", "*.png", "*.jpg", "*.jpeg",
            "*.webp", "*.xlsx", "!templates/image_prompts_template.xlsx", "!templates/image_prompts_sample.xlsx",
            "*.safetensors", "*.gguf", "models/", "output/", "outputs/", ".pytest_cache/", ".DS_Store", "*.log"]


def lines():
    return [l.strip() for l in GI.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]


def ignored(path: str) -> bool:
    """Minimal gitignore emulation (last matching rule wins). No git."""
    result = False
    parts = path.split("/")
    for rule in lines():
        neg = rule.startswith("!")
        pat = rule[1:] if neg else rule
        if pat.endswith("/"):
            d = pat[:-1]
            hit = any(fnmatch.fnmatch(p, d) for p in parts[:-1]) or (path.rstrip("/") and fnmatch.fnmatch(parts[-1], d))
        elif "/" in pat:
            hit = fnmatch.fnmatch(path, pat)
        else:
            hit = any(fnmatch.fnmatch(p, pat) for p in parts)
        if hit:
            result = not neg
    return result


def test_required_lines_present():
    present = lines()
    for r in REQUIRED:
        assert r in present, r


def test_matching():
    for p in ["device_profile.json", "a.png", "b.xlsx", ".venv", ".venv/lib/x.py", "x/y.safetensors"]:
        assert ignored(p), p
    assert not ignored("templates/image_prompts_sample.xlsx")
    assert not ignored("templates/image_prompts_template.xlsx")
    assert ignored("templates/other.xlsx")
    assert not ignored("medimg/config.py")
