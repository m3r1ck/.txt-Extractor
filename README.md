# txt-Extractor

Convert `.pdf` and `.htm`/`.html` files to plain `.txt`.

Tables are preserved as aligned plain-text columns.

## Setup

```bash
pip install -r requirements.txt
```

## Usage

Convert a single file:

```bash
python convert_to_txt.py report.pdf
python convert_to_txt.py page.html
```

Convert every supported file in a directory (recursive):

```bash
python convert_to_txt.py ./documents/
```

Write output to a specific directory:

```bash
python convert_to_txt.py ./documents/ --output-dir ./output/
```

Output `.txt` files are placed next to the originals by default.
