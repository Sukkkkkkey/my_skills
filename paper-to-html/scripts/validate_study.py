"""Structure and reading-load checks; cannot validate meaning or mathematics."""
import argparse
from collections import Counter
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
from reading_budget import estimate_reading


class Document(HTMLParser):
    def __init__(self, path):
        super().__init__(convert_charrefs=True)
        self.path = path
        self.ids, self.links, self.issues, self.figure_stack = [], [], [], []
        self.text = path.read_text(encoding="utf-8-sig")
        self.feed(self.text)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.append(a["id"])
        for name in ("href", "src", "poster"):
            if a.get(name):
                self.links.append((tag, name, a[name]))
        if tag == "img" and not a.get("alt") and a.get("id") != "image-large":
            self.issues.append("Image lacks meaningful alt text")
        if tag == "figure":
            self.figure_stack.append({"caption": False, "id": a.get("id", "unnamed")})
            if not a.get("data-source-version") or not a.get("data-source-locator"):
                self.issues.append(f"Figure {a.get('id')} lacks source version/locator (mark original diagrams explicitly)")
        if tag == "figcaption" and self.figure_stack:
            self.figure_stack[-1]["caption"] = True

    def handle_endtag(self, tag):
        if tag == "figure" and self.figure_stack:
            f = self.figure_stack.pop()
            if not f["caption"]:
                self.issues.append(f"Figure {f['id']} lacks a caption")


def validate(path):
    cache = {}
    def doc(p):
        p = p.resolve()
        if p not in cache:
            cache[p] = Document(p)
        return cache[p]
    d = doc(path)
    errors = list(d.issues)
    warnings = []
    errors.extend(f"Duplicate id: {key}" for key, n in Counter(d.ids).items() if n > 1)
    for marker in (r"\{\{(?:figure|cite):", r"\bTODO\b", r"\bTBD\b", r"待补充", r"\\\[", r"\\\("):
        if re.search(marker, d.text):
            errors.append(f"Unresolved content/math marker: {marker}")
    if not re.search(r"<html[^>]+lang=", d.text, re.I):
        errors.append("Missing document language")
    for tag, attr, raw in d.links:
        u = urlsplit(raw)
        if u.scheme in ("http", "https") or u.netloc:
            if attr in ("src", "poster") or (tag == "link" and attr == "href"):
                errors.append(f"Remote embedded dependency: {raw}")
            continue
        if u.scheme in ("mailto", "tel", "data"):
            continue
        if u.scheme or raw.startswith(("/", "\\")):
            errors.append(f"Nonportable local link: {raw}")
            continue
        target = (path.parent / unquote(u.path)).resolve() if u.path else path.resolve()
        if not target.is_file():
            errors.append(f"Missing target: {raw}")
            continue
        if u.fragment and target.suffix.lower() in (".html", ".htm") and unquote(u.fragment) not in doc(target).ids:
            errors.append(f"Missing anchor: {raw}")
    coverage_file = path.parent / "coverage.json"
    if coverage_file.is_file():
        coverage = json.loads(coverage_file.read_text(encoding="utf-8-sig"))
        for item in coverage.get("items", []):
            if item.get("status") == "not-applicable":
                continue
            if item.get("status") == "reference-only":
                if item.get("priority") == "core" or not item.get("note") or not item.get("source"):
                    errors.append(f"Invalid reference-only coverage: {item.get('source')}")
                continue
            if item.get("status") == "linked":
                target_ref = urlsplit(item.get("target", ""))
                linked_path = (path.parent / unquote(target_ref.path)).resolve()
                if target_ref.scheme or target_ref.netloc or not target_ref.path or not linked_path.is_file() or linked_path.suffix.lower() not in (".html", ".htm"):
                    errors.append(f"Missing local supplement: {item.get('target')}")
                elif target_ref.fragment and unquote(target_ref.fragment) not in doc(linked_path).ids:
                    errors.append(f"Supplement anchor missing: {item.get('target')}")
                if not item.get("note"):
                    errors.append(f"Linked coverage needs scope note: {item.get('source')}")
                continue
            anchor = item.get("target", "").lstrip("#")
            if anchor not in d.ids:
                errors.append(f"Coverage target missing: {anchor}")
            if item.get("status") == "unresolved":
                warnings.append(f"Unresolved source coverage: {item.get('source')}")
    else:
        warnings.append("No coverage.json: completeness requires manual evidence")
    # Inspect CSS for imported fonts, remote images or missing local assets.
    for tag, attr, raw in d.links:
        if tag != "link" or not raw.endswith(".css") or urlsplit(raw).scheme:
            continue
        css = path.parent / unquote(raw)
        if not css.is_file():
            continue
        text = css.read_text(encoding="utf-8-sig")
        for ref in re.findall(r"url\(\s*['\"]?([^)'\"\s]+)", text):
            if ref.startswith("data:"):
                continue
            if ref.startswith(("http:", "https:", "//")):
                errors.append(f"Remote CSS resource: {ref}")
            elif not (css.parent / unquote(ref)).is_file():
                errors.append(f"Missing CSS resource: {ref}")
        if re.search(r"@import\s+['\"]", text):
            warnings.append("CSS string @import requires manual offline verification")
    reading = None
    try:
        reading = estimate_reading(d.text)
        if not reading["passed"]:
            errors.append(f'Reading estimate {reading["estimated_minutes"]} min exceeds {reading["budget_minutes"]:g} min')
    except (ValueError, TypeError) as exc:
        errors.append(f"Reading estimate: {exc}")
    return {"file": path.name, "scope": "structure and reading estimate; no semantic certification", "passed": not errors, "reading": reading, "errors": sorted(set(errors)), "warnings": sorted(set(warnings)), "ids": len(d.ids), "links": len(d.links)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("html", type=Path)
    p.add_argument("--report", type=Path)
    a = p.parse_args()
    try:
        result = validate(a.html.resolve())
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if a.report:
            a.report.parent.mkdir(parents=True, exist_ok=True)
            a.report.write_text(text, encoding="utf-8")
        print(text)
        raise SystemExit(0 if result["passed"] else 1)
    except (OSError, ValueError) as exc:
        p.exit(2, f"Validation failed: {exc}\n")


if __name__ == "__main__":
    main()
