import pytest

from medimg import rules
from medimg.rules import HINT, check_prompt

UNDER18 = "Blocked: the prompt states an age under 18. Images are adults only."


@pytest.mark.parametrize("p", [
    "45-year-old woman", "45 year old woman", "adult male", "aged 60", "age 45",
    "age: 45", "eighteen-year-old", "18-year-old man", "elderly man", "middle-aged",
    "middle aged woman", "older man", "older woman", "45yo man", "45 y/o man",
    "45 yrs woman", "forty-five-year-old man", "forty five year old man",
    "ninety-nine-year-old", "twenty-one-year-old", "AGED 30", "A 45-YEAR-OLD MAN",
    "schoolteacher's adult patient", "boyfriend of an adult", "girlfriend, 30 yo",
    "adults in a waiting room",
    "105-year-old woman", "18 yo", "aged eighteen",
])
def test_passes(p):
    assert check_prompt(p) is None, p


@pytest.mark.parametrize("p", [
    "16 yo", "17-year-old adult", "aged 12", "age: 9", "age 17", "sixteen-year-old",
    "seventeen year old man", "5 y/o", "10 yrs", "1.5-year-old", "zero-year-old",
    "45-year-old with a 16 yo son",
    "adult woman, 16 years of age", "an adult-looking 15 y.o. female",
    "adult, 15 years", "adult woman age-16", "adult woman (16)",
    "adult young lady of 16", "adult man 17 yrs of age", "adult, 12 y.o.",
])
def test_blocks_age_under_18(p):
    assert check_prompt(p) == UNDER18


@pytest.mark.parametrize("p,term", [
    ("teen", "teen"), ("adult teen", "teen"), ("a boy", "boy"), ("schoolgirl", "schoolgirl"),
    ("paediatric knee", "paediatric"), ("pediatric knee", "pediatric"),
    ("45-year-old man with a child", "child"), ("adult children", "children"),
    ("adult Kids", "kids"), ("toddlers", "toddlers"), ("newborn baby", "newborn"),
    ("babies", "babies"), ("adolescent", "adolescent"), ("juvenile", "juvenile"),
    ("minors", "minors"), ("underage", "underage"), ("youth", "youth"),
    ("youngsters", "youngsters"), ("highschooler", "highschooler"),
    ("preteen", "preteen"), ("tweens", "tweens"), ("kiddo", "kiddo"),
    ("teenager", "teenager"), ("teenaged", "teenaged"), ("neonate", "neonate"),
    ("schoolchildren", "schoolchildren"), ("schoolkid", "schoolkid"),
    ("childlike", "childlike"), ("adult at school", "school"), ("infants", "infants"),
    ("adolescence", "adolescence"), ("BOY", "boy"), ("45-year-old Girl", "girl"),
])
def test_blocks_minor_terms(p, term):
    assert check_prompt(p) == (
        f"Blocked: '{term}' suggests a minor. Images are adults only; rephrase."
    )


@pytest.mark.parametrize("p", ["woman", "man", "", "a knee X-ray", "person with a rash",
                               "nurse", "45 apples"])
def test_blocks_no_adult(p):
    assert check_prompt(p) == "Blocked: the prompt does not state an adult. " + HINT


@pytest.mark.parametrize("p", ["boyfriend", "girlfriend", "adulthood"])
def test_word_boundaries(p):
    r = check_prompt(p)
    assert r is None or "suggests a minor" not in r


def test_boyfriend_not_minor_term():
    assert check_prompt("adult man and his boyfriend") is None
    assert check_prompt("adult woman and her girlfriend") is None


def test_age_checked_before_terms():
    assert check_prompt("16 yo boy") == UNDER18


def test_reason_prefix_and_hint():
    for p in ["teen", "woman", "16 yo"]:
        assert check_prompt(p).startswith("Blocked: ")
    assert HINT == "State an adult age (for example 45-year-old) or the word adult."


def test_no_config_hooks():
    public = [n for n in dir(rules) if not n.startswith("_")]
    assert "os" not in public and "environ" not in public
