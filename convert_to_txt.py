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
import pymupdf4llm
import pytesseract
from bs4 import BeautifulSoup
from PIL import Image

# Minimum characters per page to consider embedded text sufficient
_MIN_TEXT_THRESHOLD = 50


def pdf_to_text(pdf_path: Path) -> str:
    """Extract text from a PDF file.

    Processes page by page. Uses embedded text when available, falls back
    to OCR for scanned pages. Detects and corrects page orientation for
    sideways pages. Skips financial tables but keeps paragraph text.
    """
    import io
    import re

    doc = pymupdf.open(pdf_path)
    parts = []

    for page_num in range(len(doc)):
        page = doc[page_num]

        # Try embedded text first
        embedded = page.get_text().strip()

        if len(embedded) >= _MIN_TEXT_THRESHOLD:
            parts.append(embedded)
        else:
            # Scanned page — use OCR with orientation detection
            zoom = 300 / 72
            mat = pymupdf.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            img = Image.open(io.BytesIO(pix.tobytes("png")))

            # Detect and correct orientation
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

    # Now filter the combined text: remove financial tables, keep paragraphs
    return _filter_tables("\n\n".join(parts))


def _is_financial_line(line: str) -> bool:
    """Check if a line looks like financial data rather than paragraph text."""
    import re

    stripped = line.strip()
    if not stripped:
        return False

    # Pure dollar amounts, percentages, or numbers
    if re.match(r"^[\s\d$%,().\-+]+$", stripped):
        return True

    # Quarter/year labels like Q2.17, Q3.18, FY2023, etc.
    if re.match(r"^[QFY\d.\s/\-]+$", stripped, re.IGNORECASE):
        return True

    # Short lines where numbers/financial chars dominate
    numeric_chars = len(re.findall(r"[\d$%,().\-]", stripped))
    alpha_chars = len(re.findall(r"[a-zA-Z]", stripped))
    total = numeric_chars + alpha_chars
    if total > 0 and numeric_chars > alpha_chars and len(stripped) < 60:
        return True

    # Bullet fragments (just a bullet with no real sentence)
    if stripped in ("▪", "•", "●", "■", "-", "–", "—"):
        return True

    # Lines that are just short financial labels + numbers
    # e.g. "Total Segment EBITDA" or "New Reporting Standards ($M)(1)"
    if len(stripped) < 80 and re.search(r"\(\$[A-Z]*\)", stripped):
        return True

    # Short financial label lines (common in chart/table headers)
    financial_keywords = (
        "revenue", "ebitda", "earnings", "income", "margin", "segment",
        "operating", "net sales", "gross profit", "cash flow",
        "financial results", "summary financial", "reporting standards",
    )
    if len(stripped) < 80 and any(kw in stripped.lower() for kw in financial_keywords):
        return True

    return False


def _filter_tables(text: str) -> str:
    """Remove financial table/chart content but keep paragraph text."""
    import re

    lines = text.splitlines()
    filtered = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # Detect markdown table lines
        if re.match(r"\s*\|", line):
            # Gather all consecutive table lines
            table_lines = []
            while i < len(lines) and re.match(r"\s*\|", lines[i]):
                table_lines.append(lines[i])
                i += 1

            # Extract cell contents (skip separator rows like |---|---|)
            cells_text = []
            for tl in table_lines:
                if re.match(r"\s*\|[\s\-:|]+\|\s*$", tl):
                    continue
                cells = [c.strip() for c in tl.split("|") if c.strip()]
                cells_text.extend(cells)

            # Check if this table has paragraph-length text (>80 chars in a cell)
            has_paragraph = any(len(cell) > 80 for cell in cells_text)
            if has_paragraph:
                for cell in cells_text:
                    if len(cell) > 40:
                        filtered.append(cell)
            continue

        # Detect clusters of financial data lines (charts/tables in plain text)
        if _is_financial_line(line):
            # Skip consecutive financial lines
            while i < len(lines) and (
                _is_financial_line(lines[i]) or not lines[i].strip()
            ):
                i += 1
            continue

        filtered.append(line)
        i += 1

    return "\n".join(filtered).strip()


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
