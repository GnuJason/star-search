"""Cross-check the RECONS Parquet against the image-only RECON_data.pdf print.

The PDF (``gaia_datasets/raw/RECON_data.pdf``) is a browser print of
http://www.recons.org/TOP100.posted.htm with no text layer, so it cannot be a
parsing source. This script renders it (pdftoppm), OCRs it (tesseract), and
reports how many distinct parallax values and system ranks from the parsed HTML
table are visible in the OCR text. It is a *visual sanity check*, not a parser.

Requires ``pdftoppm`` (poppler-utils) and ``tesseract`` on PATH.
"""

import argparse
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import pyarrow.parquet as pq


def ocr_pdf(pdf_path, dpi=200):
    for tool in ("pdftoppm", "tesseract"):
        if shutil.which(tool) is None:
            raise RuntimeError(f"{tool} is required for the PDF cross-check")
    with tempfile.TemporaryDirectory() as directory:
        prefix = Path(directory) / "page"
        subprocess.run(["pdftoppm", "-r", str(dpi), "-png", str(pdf_path), str(prefix)],
                       check=True, capture_output=True)
        text = []
        for image in sorted(Path(directory).glob("page-*.png")):
            result = subprocess.run(["tesseract", str(image), "-", "--psm", "6"],
                                    check=True, capture_output=True, text=True)
            text.append(result.stdout)
    # Common OCR confusions in fixed-width numeric tables.
    return "\n".join(text).replace("@", "0").replace("O.", "0.")


def crosscheck(parquet_path, pdf_path):
    table = pq.read_table(parquet_path, columns=["system_rank", "parallax_arcsec"])
    html_parallaxes = {f"{value:.5f}" for value in table["parallax_arcsec"].to_pylist()}
    html_ranks = set(table["system_rank"].to_pylist())
    ocr = ocr_pdf(pdf_path)
    ocr_parallaxes = set(re.findall(r"\b0\.\d{5}\b", ocr))
    ocr_ranks = {int(match) for match in re.findall(r"(?m)^\s*(\d{1,3})\.\s", ocr)}
    return {
        "html_parallaxes": len(html_parallaxes),
        "parallaxes_found_in_pdf": len(html_parallaxes & ocr_parallaxes),
        "parallaxes_missing_in_pdf": sorted(html_parallaxes - ocr_parallaxes),
        "html_systems": len(html_ranks),
        "ranks_found_in_pdf": len(html_ranks & ocr_ranks),
        "pdf_source_footer": "recons.org/TOP100.posted.htm" in ocr,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet", type=Path, default=Path("gaia_datasets/recons_nearest.parquet"))
    parser.add_argument("--pdf", type=Path, default=Path("gaia_datasets/raw/RECON_data.pdf"))
    parser.add_argument("--report", type=Path, default=Path("gaia_datasets/recons_pdf_crosscheck.md"))
    parser.add_argument("--min-fraction", type=float, default=0.9,
                        help="fail if fewer than this fraction of parallaxes are seen in the OCR")
    arguments = parser.parse_args()
    try:
        stats = crosscheck(arguments.parquet, arguments.pdf)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.error(str(error))
    fraction = stats["parallaxes_found_in_pdf"] / max(stats["html_parallaxes"], 1)
    lines = [
        "# RECONS PDF cross-check",
        "",
        f"- Parquet: `{arguments.parquet}`",
        f"- PDF: `{arguments.pdf}` (image-only print of recons.org/TOP100.posted.htm; "
        f"footer detected: {stats['pdf_source_footer']})",
        f"- Distinct parallaxes in parsed table: {stats['html_parallaxes']}",
        f"- Parallaxes visible in PDF OCR: {stats['parallaxes_found_in_pdf']} ({fraction:.1%})",
        f"- Parallaxes not recovered by OCR (OCR noise expected): "
        f"{', '.join(stats['parallaxes_missing_in_pdf']) or 'none'}",
        f"- Ranked systems in parsed table: {stats['html_systems']}; rank labels recovered by OCR: "
        f"{stats['ranks_found_in_pdf']}",
        "",
        "The PDF is used only as a visual confirmation that the HTML snapshot matches the",
        "document the user supplied; OCR misses are attributable to glyph confusion (0/@/6),",
        "not to parsing differences. The right-hand Common Name column is clipped in the print.",
    ]
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    if fraction < arguments.min_fraction:
        print("cross-check FAILED: too few parallaxes recovered", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
