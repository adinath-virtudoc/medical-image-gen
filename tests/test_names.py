import pytest

from medimg.names import (
    image_file_name, image_id, path_too_long, rel_path, safe_component,
)


def test_reserved():
    assert safe_component("CON") == "CON_"
    assert safe_component("com1") == "com1_"
    assert safe_component("LPT9") == "LPT9_"
    assert safe_component("Console") == "Console"
    assert safe_component("con.lateral") == "con_.lateral"
    assert safe_component("Nul.1") == "Nul_.1"
    assert safe_component("Aux.notes") == "Aux_.notes"


def test_reserved_in_rel_path():
    assert rel_path("Nul.1", "Aux.notes", "Lecture", "con.lateral") == "Nul_.1/Aux_.notes/Lecture/con_.lateral.png"


def test_strip_chars():
    assert safe_component("a<b>:c") == "abc"
    assert safe_component('a"/\\|?*b') == "ab"
    assert safe_component("a\x00\x1f\tb\x7f") == "ab"


def test_trim_and_empty():
    assert safe_component("name. . ") == "name"
    assert safe_component("  ") == "untitled"
    assert safe_component("...") == "untitled"
    assert safe_component("") == "untitled"


@pytest.mark.parametrize("n,exp", [("x.PNG", "x.png"), ("x", "x.png"), ("x.png", "x.png"), ("CON.png", "CON_.png")])
def test_file_name(n, exp):
    assert image_file_name(n) == exp


def test_rel_path():
    assert rel_path("A", "B", "C", "x.PNG") == "A/B/C/x.png"
    assert rel_path("", "", "", "x") == "_single/x.png"
    assert rel_path(" ", "", "", "x") == "_single/x.png"
    assert rel_path("A:", "", "C", "x") == "A/untitled/C/x.png"


def test_too_long(tmp_path):
    assert not path_too_long(tmp_path, "a/b.png")
    assert path_too_long(tmp_path, "a" * 300 + ".png")
    assert path_too_long(tmp_path, "abc.png", limit=5)


def test_image_id_stable():
    a = image_id("A/B/C/x.png")
    assert a == image_id("A/B/C/x.png") and len(a) == 16
    assert a != image_id("A/B/C/y.png")
