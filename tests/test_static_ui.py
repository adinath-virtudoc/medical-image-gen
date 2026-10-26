"""Pure file checks on the static UI. No server, no browser."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "medimg" / "static"
FILES = ("index.html", "app.css", "app.js")


def read(name):
    return (STATIC / name).read_text(encoding="utf-8")


def header_ids():
    m = re.search(r"<!--(.*?)-->", read("index.html"), re.S)
    assert m, "index.html needs a header comment listing element ids"
    ids = re.findall(r"^\s*([a-z][a-z0-9-]*)\s*:", m.group(1), re.M)
    return [i for i in ids if i != "ids"]


@pytest.mark.parametrize("name", FILES)
def test_files_exist(name):
    assert (STATIC / name).is_file()


@pytest.mark.parametrize("name", FILES)
def test_no_absolute_urls(name):
    text = read(name)
    assert "http://" not in text and "https://" not in text
    assert "//cdn" not in text


def test_no_off_origin_script_or_link():
    html = read("index.html")
    for tag in re.findall(r"<(?:script|link)\b[^>]*>", html, re.I):
        for url in re.findall(r"""(?:src|href)\s*=\s*["']([^"']+)["']""", tag, re.I):
            assert url.startswith("/") and not url.startswith("//"), url


def test_header_ids_exist_in_markup():
    ids = header_ids()
    assert len(ids) > 50
    html = read("index.html")
    body = html[html.index("-->"):]
    missing = [i for i in ids if not re.search(r"""\bid\s*=\s*["']%s["']""" % re.escape(i), body)]
    assert not missing, missing


def test_required_controls_listed():
    ids = set(header_ids())
    need = {"st-model", "st-bar", "st-image", "st-eta", "st-local", "b-file", "b-retry", "b-count",
            "b-estimate", "b-generate", "b-cancel", "b-download", "s-prompt", "s-seed", "s-random",
            "s-steps", "s-size", "s-generate", "g-tree", "g-grid", "lightbox", "lb-regen", "lb-reuse",
            "lb-folder", "d-report", "d-table", "d-bench", "d-unverified", "set-root", "set-unload",
            "c-total", "c-done", "c-pending", "c-blocked", "c-failed", "c-invalid"}
    assert need <= ids, need - ids


def test_markup_ids_unique():
    ids = re.findall(r"""\bid\s*=\s*["']([^"']+)["']""", read("index.html"))
    assert len(ids) == len(set(ids))


PINNED_ROUTES = [
    "/api/config", "/api/status", "/api/sheet", "/api/sheet/download", "/api/sheet/estimate",
    "/api/jobs/batch", "/api/jobs/single", "/api/jobs/regenerate", "/api/jobs/cancel",
    "/api/gallery/tree", "/api/gallery/images", "/open-folder", "/api/device",
    "/api/device/benchmark", "/api/settings",
]


@pytest.mark.parametrize("route", PINNED_ROUTES)
def test_app_js_uses_route(route):
    assert route in read("app.js")


def test_app_js_only_same_origin_fetches():
    js = read("app.js")
    for url in re.findall(r"""["'](/[a-z][^"']*)["']""", js):
        if url.startswith(("/api/", "/files/", "/static/")) or url == "/open-folder":
            continue
        # other slash strings (e.g. " / " separators) are not URLs
        assert " " in url or url == "/", url


def test_app_js_single_iife():
    js = read("app.js").strip()
    assert js.startswith("(function") and js.endswith("})();")
    assert len(re.findall(r"^\(function", js, re.M)) == 1
    assert not re.search(r"^\s*(import|export)\s", js, re.M)


def test_app_js_polls_every_500ms():
    assert re.search(r"setInterval\(\s*poll\s*,\s*500\s*\)", read("app.js"))


def test_steps_slider():
    html = read("index.html")
    tag = re.search(r"<input[^>]*id=\"s-steps\"[^>]*>", html).group(0)
    assert 'type="range"' in tag
    assert 'min="4"' in tag and 'max="15"' in tag and 'value="9"' in tag
    assert "8" in html and "9 recommended for Z-Image Turbo" in html


@pytest.mark.parametrize("select_id", ["s-size", "b-size"])
def test_six_presets(select_id):
    html = read("index.html")
    sel = re.search(r"<select[^>]*id=\"%s\"[^>]*>(.*?)</select>" % select_id, html, re.S).group(1)
    values = re.findall(r"value=\"(\d+x\d+)\"", sel)
    assert values == ["1024x1024", "768x1344", "1344x768", "832x1216", "1216x832", "768x768"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_app_js_syntax():
    r = subprocess.run(["node", "--check", str(STATIC / "app.js")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
