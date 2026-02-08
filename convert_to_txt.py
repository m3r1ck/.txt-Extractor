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

import pymupdf4llm
from bs4 import BeautifulSoup


def pdf_to_text(pdf_path: Path) -> str:
    """Extract text from a PDF file with improved layout analysis."""
    md_text = pymupdf4llm.to_markdown(str(pdf_path))
    # Strip Markdown formatting to produce clean plain text
    lines = []
    for line in md_text.splitlines():
        # Remove heading markers
        stripped = line.lstrip("#").strip() if line.startswith("#") else line
        # Remove bold/italic markers
        stripped = stripped.replace("**", "").replace("__", "")
        lines.append(stripped)
    return "\n".join(lines).strip()


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

    # Process tables in-place: replace each <table> with its text rendition
    for table_tag in soup.find_all("table"):
        rows = []
        for tr in table_tag.find_all("tr"):
            cells = [td.get_text(separator=" ", strip=True)
                     for td in tr.find_all(["td", "th"])]
            rows.append(cells)
        formatted = _format_table(rows)
        table_tag.replace_with(f"\n{formatted}\n" if formatted else "")

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


def _format_table(rows: list[list[str | None]]) -> str:
    """Format a list of rows into an aligned plain-text table."""
    if not rows:
        return ""

    # Normalise: replace None with empty string
    rows = [[cell or "" for cell in row] for row in rows]

    # Determine column widths
    max_cols = max(len(row) for row in rows)
    col_widths = [0] * max_cols
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))

    # Build formatted lines
    lines = []
    for row_idx, row in enumerate(rows):
        padded = []
        for i in range(max_cols):
            val = str(row[i]) if i < len(row) else ""
            padded.append(val.ljust(col_widths[i]))
        lines.append("  ".join(padded).rstrip())

        # Add a separator after the header row
        if row_idx == 0:
            sep = "  ".join("-" * w for w in col_widths)
            lines.append(sep)

    return "\n".join(lines)


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
