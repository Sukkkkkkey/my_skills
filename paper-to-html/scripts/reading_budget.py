"""Estimate editorial reading load; not a measured human reading-time guarantee.

Counts all main content, including closed details, plus visual/math allowances.
Navigation and source notes are excluded. Uses only the Python standard library.
"""
import argparse
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re

CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002fa1f]")
WORDS = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+(?:[’'\-][A-Za-zÀ-ÖØ-öø-ÿ0-9]+)*")
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
IGNORE = {"script", "style", "nav", "button", "footer", "dialog", "template"}
# Editorial defaults, deliberately not adjustable to make an oversized page pass.
RATES = {"cjk_characters_per_minute": 350, "latin_words_per_minute": 160,
         "minutes_per_visual": 0.5, "minutes_per_equation": 0.25}


class ReadingContent(HTMLParser):
    def __init__(self, document):
        super().__init__(convert_charrefs=True)
        self.stack, self.parts, self.metadata = [], [], {}
        self.figures = self.tables = self.equations = 0
        self.has_main = False
        self.feed(document)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta" and a.get("name", "").startswith("paper-reading-"):
            self.metadata[a["name"]] = a.get("content", "")
        parent = self.stack[-1] if self.stack else {"main": False, "ignore": False, "figure": False, "equation": False}
        in_main = tag == "main" or parent["main"]
        self.has_main |= tag == "main"
        classes = set(a.get("class", "").split())
        ignored = parent["ignore"] or tag in IGNORE or a.get("id") == "sources" or "reading-time" in classes
        is_equation = ("equation" in classes or "math-line" in classes or (tag == "math" and a.get("display") == "block"))
        if in_main and not ignored:
            if tag in ("figure", "img", "svg") and not parent["figure"]:
                self.figures += 1
            if tag == "table" and not parent["figure"]:
                self.tables += 1
            if is_equation and not parent["equation"]:
                self.equations += 1
        if tag not in VOID:
            self.stack.append({"tag": tag, "main": in_main, "ignore": ignored,
                               "figure": parent["figure"] or tag == "figure",
                               "equation": parent["equation"] or is_equation})

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]["tag"] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self.stack and self.stack[-1]["main"] and not self.stack[-1]["ignore"]:
            self.parts.append(data)


def reading_options(options=None):
    options = options or {}
    budget = float(options.get("budget_minutes", 10))
    extra = float(options.get("extra_minutes", 0))
    if not math.isfinite(budget) or budget <= 0 or not math.isfinite(extra) or extra < 0:
        raise ValueError("Reading budget must be positive and extra time non-negative")
    reason = str(options.get("override_reason", "")).strip()
    extra_reason = str(options.get("extra_reason", "")).strip()
    if budget > 10 and not reason:
        raise ValueError("A budget above 10 minutes needs the user's requested scope in reading.override_reason")
    if extra and not extra_reason:
        raise ValueError("Additional visual/derivation time needs reading.extra_reason")
    return {"budget_minutes": budget, "extra_minutes": extra,
            "override_reason": reason, "extra_reason": extra_reason}


def estimate_reading(document, options=None):
    parsed = ReadingContent(document)
    if not parsed.has_main:
        raise ValueError("Reading estimate requires a <main> containing the complete study")
    if options is None:
        options = {key: parsed.metadata["paper-reading-" + key.replace("_", "-")]
                   for key in ("budget_minutes", "extra_minutes", "override_reason", "extra_reason")
                   if "paper-reading-" + key.replace("_", "-") in parsed.metadata}
    policy = reading_options(options)
    text = " ".join(parsed.parts)
    cjk_count = len(CJK.findall(text))
    word_count = len(WORDS.findall(CJK.sub(" ", text)))
    text_minutes = cjk_count / RATES["cjk_characters_per_minute"] + word_count / RATES["latin_words_per_minute"]
    visual_minutes = (parsed.figures + parsed.tables) * RATES["minutes_per_visual"]
    equation_minutes = parsed.equations * RATES["minutes_per_equation"]
    total = text_minutes + visual_minutes + equation_minutes + policy["extra_minutes"]
    return {"scope": "Editorial estimate, including closed details; not measured human reading time",
            "cjk_characters": cjk_count, "latin_words_and_numbers": word_count,
            "figures": parsed.figures, "tables": parsed.tables, "equation_blocks": parsed.equations,
            "rates": RATES, **policy, "text_minutes": round(text_minutes, 2),
            "visual_minutes": visual_minutes, "equation_minutes": equation_minutes,
            "estimated_minutes": round(total, 2), "display_minutes": max(1, math.ceil(total)),
            "passed": total <= policy["budget_minutes"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        result = estimate_reading(args.html.read_text(encoding="utf-8-sig"))
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(output, encoding="utf-8")
        print(output)
        raise SystemExit(0 if result["passed"] else 1)
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(2, f"Reading estimate failed: {exc}\n")


if __name__ == "__main__":
    main()
