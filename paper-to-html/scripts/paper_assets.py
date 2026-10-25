"""Read-only PDF inspection/rendering/cropping; records physical pages and SHA-256.

inspect requires pypdf; render/crop require pypdfium2 and Pillow.
Coordinates: normalized left,top,right,bottom on the rendered, rotated page.
"""
import argparse
import hashlib
import json
from pathlib import Path


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect", help="Extract page-delimited text and a source manifest")
    inspect.add_argument("pdf", type=Path)
    inspect.add_argument("--output", type=Path, required=True)
    for command in ("render", "crop"):
        c = sub.add_parser(command)
        c.add_argument("pdf", type=Path)
        c.add_argument("--page", type=int, required=True, help="1-based physical PDF page")
        c.add_argument("--scale", type=float, default=2.5, help="Pixels per PDF point; 2.5 = 180 dpi")
        c.add_argument("--output", type=Path, required=True)
        if command == "crop":
            c.add_argument("--box", type=float, nargs=4, required=True, metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"))
            c.add_argument("--version", required=True)
            c.add_argument("--label", required=True, help="Original figure/table/equation identifier")
            c.add_argument("--url", required=True)
    a = p.parse_args()
    try:
        if a.pdf.resolve() == a.output.resolve():
            raise ValueError("Output must not overwrite the source PDF")
        digest = hashlib.sha256(a.pdf.read_bytes()).hexdigest()
        if a.command == "inspect":
            from pypdf import PdfReader
            reader = PdfReader(a.pdf)
            a.output.mkdir(parents=True, exist_ok=True)
            text = "\n\n".join(f"=== PDF PHYSICAL PAGE {i + 1} ===\n{page.extract_text() or ''}" for i, page in enumerate(reader.pages))
            (a.output / "pages.txt").write_text(text, encoding="utf-8")
            write_json(a.output / "source.json", {"file": a.pdf.name, "sha256": digest, "physical_pages": len(reader.pages), "metadata": {str(k): str(v) for k, v in (reader.metadata or {}).items()}, "note": "Text extraction is a reading aid; inspect rendered equations, figures, and tables."})
            print(f"Inspected {len(reader.pages)} pages; {a.output}")
            return
        if not 0 < a.scale <= 8:
            raise ValueError("scale must be > 0 and <= 8")
        import pypdfium2 as pdfium
        with pdfium.PdfDocument(a.pdf) as doc:
            if not 1 <= a.page <= len(doc):
                raise ValueError(f"page must be in 1..{len(doc)}")
            page = doc[a.page - 1]
            bitmap = page.render(scale=a.scale)
            image = bitmap.to_pil().copy()
            bitmap.close()
            page.close()
        if a.command == "crop":
            left, top, right, bottom = a.box
            if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
                raise ValueError("box must satisfy 0 <= left < right <= 1 and 0 <= top < bottom <= 1")
            width, height = image.size
            image = image.crop((round(left * width), round(top * height), round(right * width), round(bottom * height)))
            if min(image.size) < 4:
                raise ValueError("Crop too small")
        a.output.parent.mkdir(parents=True, exist_ok=True)
        image.save(a.output)
        record = {"pdf": a.pdf.name, "pdf_sha256": digest, "page": a.page, "page_numbering": "physical, 1-based", "scale": a.scale, "image": a.output.name, "image_sha256": hashlib.sha256(a.output.read_bytes()).hexdigest(), "width": image.width, "height": image.height}
        if a.command == "crop":
            record.update({"box": a.box, "version": a.version, "label": a.label, "url": a.url, "operation": "原 PDF 栅格裁切；未修改图内内容"})
        write_json(a.output.with_suffix(a.output.suffix + ".source.json"), record)
        print(a.output)
    except (ImportError, ValueError, OSError) as exc:
        p.exit(1, f"PDF operation failed: {exc}\n")


if __name__ == "__main__":
    main()
