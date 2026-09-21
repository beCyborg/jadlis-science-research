"""The plain-language contract of the visible zone.

`examples/sample-report.md` is what the synthesizer reads as the style exemplar — a prompt rule the
example contradicts loses. So the example itself is checked against the rules of
`references/plain-language.md`, and the prompts are checked for pointing at that file.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "science-research"
SAMPLE = SKILL / "examples" / "sample-report.md"
PLAIN = SKILL / "references" / "plain-language.md"
CORE_SRC = (ROOT / "workflows" / "search-paper-core.js").read_text(encoding="utf-8")


def visible_zone(text):
    """Everything before the first folded block — the part a human actually reads."""
    body = text.split("---", 2)[-1]
    return body.split("> [!note]-")[0]


def test_plain_language_reference_exists_and_is_wired_into_the_prompts():
    text = PLAIN.read_text(encoding="utf-8")
    for anchor in ("уверенность высокая", "Ссылки — сносками", "Цифры — сначала смысл",
                   "Причина → следствие", "TL;DR"):
        assert anchor in text, anchor
    # the synthesizer and the fix agent must both be sent to it
    synth = CORE_SRC.split("function synthPrompt")[1].split("\n}")[0]
    fix = CORE_SRC.split("function fixPrompt")[1].split("\n}")[0]
    assert "plain-language.md" in synth
    assert "plain-language.md" in fix


def test_sample_report_visible_zone_has_no_jargon():
    zone = visible_zone(SAMPLE.read_text(encoding="utf-8"))
    banned = {
        "GRADE-слово": re.compile(r"\b(HIGH|MODERATE|LOW|VERY LOW|GRADE)\b"),
        "бейдж-ссылка": re.compile(r"\[[a-z]{1,2}\d+·"),
        "служебная метка": re.compile(r"\[AR-fix\]"),
        "доверительный интервал": re.compile(r"95% CI|95% ДИ"),
        "статистика": re.compile(r"\bI²|\bp\s*[<=]\s*0[.,]|\bOR\s+\d|\bHR\s+\d|\bg\s+0[.,]\d"),
        "англицизм": re.compile(r"alerting|confounding|конфаундер|гетерогенность|indirectness"),
    }
    hits = {name: rx.findall(zone) for name, rx in banned.items()}
    assert not any(hits.values()), {k: v for k, v in hits.items() if v}


def test_sample_report_uses_footnotes_and_words_for_confidence():
    text = SAMPLE.read_text(encoding="utf-8")
    zone = visible_zone(text)
    assert re.search(r"\[\^\d+\]", zone), "в видимой зоне нет ни одной сноски"
    for word in ("уверенность средняя", "уверенность низкая"):
        assert word in zone, word
    # A–E: letter plus Russian words, per §1 of plain-language.md
    assert "A — можно верить" in zone and "E — не верить" in zone
    # definitions live in one block at the very end of the file
    tail = text.strip().split("\n")
    defs = [l for l in tail if re.match(r"^\[\^\d+\]:", l)]
    assert len(defs) >= 5, defs
    assert re.match(r"^\[\^\d+\]:", tail[-1]), tail[-1]
    # every footnote used in the body has a definition
    used = set(re.findall(r"\[\^(\d+)\](?!:)", text))
    defined = set(re.findall(r"^\[\^(\d+)\]:", text, re.M))
    assert used <= defined, used - defined


def test_sample_report_visible_zone_fits_the_cap():
    zone = visible_zone(SAMPLE.read_text(encoding="utf-8"))
    assert len(zone.strip().split("\n")) <= 140, len(zone.strip().split("\n"))
    # the stale cap 120 used to live in the methodology block — the corpus cap is 240
    assert "cap 120" not in SAMPLE.read_text(encoding="utf-8")
    assert "cap 240" in SAMPLE.read_text(encoding="utf-8")
