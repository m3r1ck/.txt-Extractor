#!/usr/bin/env python3
"""Convert .pdf and .htm/.html files to .txt format.

Usage:
    python convert_to_txt.py <file_or_directory> [--output-dir DIR]

Examples:
    python convert_to_txt.py report.pdf
    python convert_to_txt.py page.html
    python convert_to_txt.py ./documents/ --output-dir ./output/
"""

import argparse
import sys
from pathlib import Path

import pymupdf
import pytesseract
from bs4 import BeautifulSoup
from PIL import Image


def pdf_to_text(pdf_path: Path) -> str:
    """Extract text from a PDF using OCR on every page.

    Renders each page at 300 DPI, detects and corrects orientation,
    then runs OCR. Works for scanned docs, screenshots, and sideways pages.
    """
    import io
    import re

    doc = pymupdf.open(pdf_path)
    parts = []

    for page in doc:
        # Render at 300 DPI for good OCR quality
        zoom = 300 / 72
        mat = pymupdf.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        img = Image.open(io.BytesIO(pix.tobytes("png")))

        # Detect and correct orientation for sideways pages
        try:
            osd = pytesseract.image_to_osd(img)
            angle = int(re.search(r"Rotate: (\d+)", osd).group(1))
            if angle:
                img = img.rotate(-angle, expand=True)
        except Exception:
            pass

        text = pytesseract.image_to_string(img, config="--psm 1")
        if text.strip():
            parts.append(text.strip())

    doc.close()
    return _clean_ocr_text("\n\n".join(parts))


def _is_junk_line(line: str) -> bool:
    """Return True if a line is a standalone number, dollar amount, percentage,
    quarter label, or other non-sentence fragment from a financial table.

    Lines that contain real words in sentences are always kept.
    """
    import re

    s = line.strip()
    if not s:
        return False

    # Standalone bullet/symbol with no text
    if s in ("▪", "•", "●", "■", "-", "–", "—", "*", "|"):
        return True

    # Purely numbers, dollar signs, percentages, commas, parens, dots, dashes
    # e.g. "$785", "38.5%", "(1,234)", "2,039"
    if re.match(r"^[\s\d$%€£,().\-+/]+$", s):
        return True

    # Quarter/year labels: Q2.17, FY2023, Q1 2024, etc.
    if re.match(r"^[QFY\d.\s/\-]+$", s, re.IGNORECASE):
        return True

    # Very short line (< 25 chars) that is mostly numbers/symbols, not words
    # e.g. "38.7%" or "$864" or "Q2.18" but NOT "*High FCF generator"
    if len(s) < 25:
        word_chars = len(re.findall(r"[a-zA-Z]", s))
        if word_chars < 4:
            return True

    return False


def _clean_ocr_text(text: str) -> str:
    """Remove junk lines (standalone financial data) from OCR output.

    Keeps all lines that look like real sentences or bullet-point notes.
    Only removes lines that are purely numbers/symbols with no real words.
    """
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        if _is_junk_line(line):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def html_to_text(html_path: Path) -> str:
    """Extract text from an HTML file, including tables."""
    raw = html_path.read_bytes()

    # Try UTF-8 first, fall back to latin-1 which never fails
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        content = raw.decode("latin-1")

    soup = BeautifulSoup(content, "html.parser")

    # Remove script and style elements
    for tag in soup(["script", "style"]):
        tag.decompose()

    # Convert <br> and <p> to newlines so they aren't lost
    for br in soup.find_all("br"):
        br.replace_with("\n")

    # Process tables: keep paragraph text, remove financial tables
    for table_tag in soup.find_all("table"):
        paragraph_texts = []
        for td in table_tag.find_all(["td", "th"]):
            cell_text = td.get_text(separator=" ", strip=True)
            if len(cell_text) > 80:
                paragraph_texts.append(cell_text)
        if paragraph_texts:
            table_tag.replace_with("\n" + "\n\n".join(paragraph_texts) + "\n")
        else:
            table_tag.decompose()

    text = soup.get_text(separator="\n")

    # Collapse excessive blank lines
    lines = text.splitlines()
    cleaned = []
    blank_count = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            blank_count += 1
            if blank_count <= 2:
                cleaned.append("")
        else:
            blank_count = 0
            cleaned.append(stripped)

    return "\n".join(cleaned).strip()


def convert_file(input_path: Path, output_dir: Path | None = None) -> Path:
    """Convert a single file and write the .txt output. Returns the output path."""
    suffix = input_path.suffix.lower()

    if suffix == ".pdf":
        text = pdf_to_text(input_path)
    elif suffix in (".htm", ".html"):
        text = html_to_text(input_path)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")

    if output_dir is None:
        output_dir = input_path.parent

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / (input_path.stem + ".txt")
    out_path.write_text(text, encoding="utf-8")
    return out_path


def gather_files(target: Path) -> list[Path]:
    """Collect all supported files from a path (file or directory)."""
    supported = {".pdf", ".htm", ".html"}
    if target.is_file():
        if target.suffix.lower() in supported:
            return [target]
        print(f"Skipping unsupported file: {target}", file=sys.stderr)
        return []

    if target.is_dir():
        files = sorted(
            f for f in target.rglob("*")
            if f.is_file() and f.suffix.lower() in supported
        )
        return files

    print(f"Path not found: {target}", file=sys.stderr)
    return []


def main():
    parser = argparse.ArgumentParser(
        description="Convert .pdf and .htm/.html files to plain .txt"
    )
    parser.add_argument(
        "input",
        type=Path,
        help="A file or directory to convert",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for output .txt files (default: same as input)",
    )
    args = parser.parse_args()

    files = gather_files(args.input)
    if not files:
        print("No supported files found.", file=sys.stderr)
        sys.exit(1)

    for f in files:
        try:
            out = convert_file(f, args.output_dir)
            print(f"{f} -> {out}")
        except Exception as e:
            print(f"ERROR converting {f}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
