"""Build a local paper study from authored HTML and traceable figure metadata.

No network, model calls, or PDF interpretation. Python standard library only.
"""
import argparse
import hashlib
import html
import json
import re
import shutil
from pathlib import Path
from reading_budget import estimate_reading, reading_options

ASSETS = Path(__file__).resolve().parents[1] / "assets"
ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def esc(value):
    return html.escape(str(value), quote=True)


def safe_id(value):
    if not ID.fullmatch(value):
        raise ValueError(f"Invalid HTML identifier: {value!r}")
    return value


def paper_identity(source):
    """Render paper-time authorship and verified publication/resource metadata."""
    affiliations = source.get("affiliations", [])
    affiliation_ids = {str(a["id"]): str(i) for i, a in enumerate(affiliations, 1)}
    if len(affiliation_ids) != len(affiliations):
        raise ValueError("Duplicate affiliation id")
    authors = source.get("authors", "作者未核实")
    names, author_html = [], []
    for author in authors if isinstance(authors, list) else [authors]:
        author = {"name": author} if isinstance(author, str) else author
        name = author["name"]
        names.append(name)
        label = esc(name)
        if author.get("url"):
            label = f'<a href="{esc(author["url"])}">{label}</a>'
        refs = [str(ref) for ref in author.get("affiliations", [])]
        if any(ref not in affiliation_ids for ref in refs):
            raise ValueError(f"Unknown affiliation for {name}")
        marks = ",".join(affiliation_ids[ref] for ref in refs)
        if marks:
            label += f'<sup>{esc(marks)}</sup>'
        if author.get("note"):
            label += f'<span class="author-note"> ({esc(author["note"])})</span>'
        author_html.append(label)
    affiliation_html = "".join(f'<span><sup>{i}</sup>{esc(a["name"])}</span>' for i, a in enumerate(affiliations, 1))
    publication = source.get("publication", {})
    if isinstance(publication, str):
        publication = {"status": publication}
    status = publication.get("status", "发表情况未核实")
    parts = [str(p) for p in (status, publication.get("venue"), publication.get("year")) if p]
    publication_html = esc(" · ".join(parts))
    if publication.get("url"):
        publication_html = f'<a href="{esc(publication["url"])}">{publication_html}</a>'
    if publication.get("doi"):
        doi = str(publication["doi"])
        url = doi if doi.startswith("https://doi.org/") else "https://doi.org/" + doi
        publication_html += f' <a class="doi" href="{esc(url)}">DOI</a>'
    resources = [{"label": "Paper", "url": source["url"]}, *source.get("resources", [])]
    resource_html, seen = [], set()
    for resource in resources:
        url = resource["url"]
        if url in seen:
            continue
        seen.add(url)
        label = resource["label"]
        if resource.get("attribution"):
            label += " · " + resource["attribution"]
        resource_html.append(f'<a href="{esc(url)}">{esc(label)}</a>')
    result = (f'<div class="paper-identity"><p class="paper-authors">{" · ".join(author_html)}</p>'
              f'<p class="paper-affiliations">{affiliation_html}</p>'
              f'<p class="paper-publication">{publication_html}</p>'
              f'<nav class="paper-resources" aria-label="论文资源">{"".join(resource_html)}</nav></div>')
    return result, " · ".join(names)


def build(config, output):
    cfg = read_json(config)
    base = config.parent
    source = cfg["source"]
    reading = reading_options(cfg.get("reading"))
    identity_html, author_names = paper_identity(source)
    output.mkdir(parents=True, exist_ok=True)
    (output / "assets").mkdir(exist_ok=True)
    for name in ("paper.css", "paper.js"):
        shutil.copy2(ASSETS / name, output / "assets" / name)
    figures = cfg.get("figures", [])
    if isinstance(figures, str):
        figures = read_json(base / figures)
    figure_list = figures
    figures = {safe_id(f["key"]): f for f in figure_list}
    if len(figures) != len(figure_list):
        raise ValueError("Duplicate figure key")
    citation_list = cfg.get("citations", [])
    citations = {safe_id(c["id"]): c for c in citation_list}
    if len(citations) != len(citation_list):
        raise ValueError("Duplicate citation id")
    rendered_figures = set()

    def figure(match):
        key = match.group(1)
        f = figures[key]
        if key in rendered_figures:
            raise ValueError(f"Figure {key} appears twice; link to #fig-{key} instead")
        rendered_figures.add(key)
        src = base / f["image"]
        if not src.is_file():
            raise FileNotFoundError(src)
        version = f.get("version", source["version"])
        locator = f["locator"]
        if not f.get("alt") or not f.get("reading"):
            raise ValueError(f"Figure {key} needs alt and reading")
        dest = output / "assets" / "figures" / (key + src.suffix.lower())
        dest.parent.mkdir(exist_ok=True)
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
        rel = dest.relative_to(output).as_posix()
        url = f.get("url", source["url"])
        dims = (f' width="{int(f["width"])}" height="{int(f["height"])}"'
                if f.get("width") and f.get("height") else "")
        return (f'<figure id="fig-{key}" data-source-version="{esc(version)}" '
                f'data-source-locator="{esc(locator)}"><a class="zoom" href="{rel}" '
                f'aria-label="放大：{esc(f["title"])}"><img src="{rel}" alt="{esc(f["alt"])}"'
                f'{dims} loading="lazy"></a><figcaption><strong>{esc(f["title"])}</strong>'
                f'<div class="figure-reading">{f["reading"]}</div>'
                f'<p class="source"><a href="{esc(url)}">{esc(f.get("label", locator))}</a>'
                f' · {esc(version)} · {esc(locator)} · {esc(f.get("operation", "原 PDF 裁切"))}</p>'
                '</figcaption></figure>')

    def cite(match):
        key = match.group(1)
        c = citations[key]
        return f'<a class="cite" href="#evidence-{key}" title="{esc(c["locator"])}">[{esc(key)}]</a>'

    sections, nav, section_ids = [], [], set()
    abstract = cfg.get("abstract")
    if abstract is not None:
        abstract_text = abstract.get("text", "").strip()
        if not abstract_text:
            raise ValueError("abstract.text must contain the original English abstract")
        abstract_body = "".join(f'<p>{esc(p.strip())}</p>' for p in re.split(r"\n\s*\n", abstract_text) if p.strip())
        note = f'<p class="source">{esc(abstract["note"])}</p>' if abstract.get("note") else ""
        abstract_source = abstract.get("url", source["url"])
        locator = abstract["locator"]
        sections.append(f'<section id="abstract" class="chapter"><div class="chapter-label">01 · ORIGINAL ABSTRACT</div><h2>Abstract</h2>'
                        f'<div class="original-abstract" lang="en">{abstract_body}</div>{note}'
                        f'<p class="source"><a href="{esc(abstract_source)}">英文原文</a> · {esc(source["version"])} · {esc(locator)}</p></section>')
        nav.append('<li><a href="#abstract"><span>01</span>Abstract</a></li>')
        section_ids.add("abstract")
    for i, s in enumerate(cfg["sections"], len(sections) + 1):
        ident = safe_id(s["id"])
        if ident in section_ids or ident == "sources":
            raise ValueError(f"Duplicate/reserved section id: {ident}")
        section_ids.add(ident)
        body = (base / s["body_file"]).read_text(encoding="utf-8-sig") if "body_file" in s else s["body_html"]
        body = re.sub(r"\{\{figure:([A-Za-z][A-Za-z0-9_-]*)\}\}", figure, body)
        body = re.sub(r"\{\{cite:([A-Za-z][A-Za-z0-9_-]*)\}\}", cite, body)
        if re.search(r"\{\{(?:figure|cite):", body):
            raise ValueError(f"Unresolved template marker in {ident}")
        sections.append(f'<section id="{ident}" class="chapter"><div class="chapter-label">{i:02d}</div><h2>{esc(s["title"])}</h2>{body}</section>')
        nav.append(f'<li><a href="#{ident}"><span>{i:02d}</span>{esc(s["title"])}</a></li>')
    evidence = "".join(f'<li id="evidence-{key}"><strong>{esc(key)}</strong> · {esc(c["locator"])} — {esc(c["claim"])}'
                        f' <a href="{esc(c.get("url", source["url"]))}">核对来源</a></li>' for key, c in citations.items())
    # source_footer is authored HTML for coverage statements and known material gaps.
    footer = cfg.get("source_footer", "")
    sections.append(f'<section id="sources" class="chapter"><div class="chapter-label">SOURCE NOTES</div><h2>来源与阅读核对</h2>'
                    f'<p><a href="{esc(source["url"])}">{esc(source["title"])}</a><br>{esc(source["version"])} · '
                    f'{esc(author_names)}</p><p class="source">固定 PDF SHA-256：<code class="hash">{esc(source.get("sha256", "未提供"))}</code></p>'
                    f'<p class="source">论文身份与资源核查：{esc(source.get("metadata_checked", "未记录日期"))}</p>'
                    + "".join(f'<p class="source"><a href="{esc(s["url"])}">{esc(s["label"])}</a></p>' for s in source.get("metadata_sources", []))
                    + f'{footer}<ol class="evidence-list">{evidence}</ol></section>')
    nav.append('<li><a href="#sources"><span>↗</span>来源与阅读核对</a></li>')
    reading_meta = "".join(f'<meta name="paper-reading-{key.replace("_", "-")}" content="{esc(value)}">' for key, value in reading.items())
    document = f'''<!doctype html>
<html lang="{esc(cfg.get('lang', 'zh-CN'))}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(cfg['title'])}</title><meta name="description" content="{esc(cfg.get('summary', ''))}">
{reading_meta}
<link rel="stylesheet" href="assets/paper.css"><script src="assets/paper.js" defer></script></head><body>
<a class="skip" href="#main">跳到正文</a><header class="masthead"><a href="#top">PAPER STUDY</a><span>{esc(cfg.get('edition', '论文精读'))}</span>
<button id="font-toggle" type="button" aria-pressed="false" hidden>大字阅读</button></header>
<div class="layout" id="top"><aside><details class="toc" open><summary>阅读目录</summary><nav aria-label="章节目录"><ol>{''.join(nav)}</ol></nav></details></aside>
<main id="main"><header class="hero"><p class="eyebrow">{esc(cfg.get('kicker', 'RESEARCH / METHODS / EVIDENCE'))}</p>
<h1>{esc(cfg['title'])}</h1><p class="subtitle">{esc(cfg.get('subtitle', source['title']))}</p>
{identity_html}
{'' if abstract is not None else '<p class="deck">' + esc(cfg.get('summary', '')) + '</p>'}<p class="meta">{esc(source['version'])} · {esc(cfg.get('audience', '面向具备领域基础的读者'))}</p><!--READING_TIME--></header>
{''.join(sections)}<footer class="endnote">{esc(cfg.get('endnote', '图表版权归原作者；本页为有出处的分析与学习材料。'))}</footer></main></div>
<dialog id="image-dialog" aria-labelledby="image-title"><div class="dialog-bar"><p id="image-title"></p><button id="image-size" type="button" aria-pressed="false">原尺寸</button><button id="image-close" type="button">关闭 ×</button></div><img id="image-large" alt=""></dialog>
</body></html>'''
    reading_report = estimate_reading(document, reading)
    (output / "reading-report.json").write_text(json.dumps(reading_report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not reading_report["passed"]:
        raise ValueError(f'Reading estimate {reading_report["estimated_minutes"]} min exceeds {reading["budget_minutes"]:g} min; condense this page (including folded content)')
    document = document.replace("<!--READING_TIME-->", f'<p class="reading-time meta">预估阅读约 {reading_report["display_minutes"]} 分钟 · 含图表与折叠内容</p>')
    target = output / "index.html"
    target.write_text(document, encoding="utf-8")
    for name in ("coverage.json", "review.json"):
        src = base / name
        if src.is_file() and src.resolve() != (output / name).resolve():
            shutil.copy2(src, output / name)
    (output / "build-manifest.json").write_text(json.dumps({
        "source": source, "reading": reading_report, "figures_used": sorted(rendered_figures),
        "figures": [{k: v for k, v in figures[key].items() if k not in ("reading", "image")}
                    for key in sorted(rendered_figures)],
        "html_sha256": hashlib.sha256(target.read_bytes()).hexdigest()
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        build(args.config.resolve(), args.output.resolve())
    except (KeyError, ValueError, OSError) as exc:
        parser.exit(1, f"Build failed: {exc}\n")


if __name__ == "__main__":
    main()
