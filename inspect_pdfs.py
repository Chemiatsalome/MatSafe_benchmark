"""
Stage 2, Step 1: INSPECT the PDFs before extracting anything.

Tells you, for each PDF:
  - how many pages
  - whether it has real text inside, or is just photos of pages (scanned)
  - a preview of what the text looks like

Run:  python inspect_pdfs.py
Needs: pip install pypdf
"""
import csv
import os

from pypdf import PdfReader

ROOT = "Maternal_RAG_Corpus"
RAW = os.path.join(ROOT, "raw_pdfs")


def inspect(path):
    """Return (pages, chars_per_page, verdict, preview)."""
    try:
        reader = PdfReader(path)
    except Exception as e:
        return 0, 0, "BROKEN", str(e)[:60]

    n_pages = len(reader.pages)

    # sample up to 5 pages spread through the document
    sample_idx = sorted(set(
        [0, n_pages // 4, n_pages // 2, (3 * n_pages) // 4, n_pages - 1]
    ))
    sample_idx = [i for i in sample_idx if 0 <= i < n_pages]

    total_chars = 0
    preview = ""
    for i in sample_idx:
        try:
            t = reader.pages[i].extract_text() or ""
        except Exception:
            t = ""
        total_chars += len(t.strip())
        if not preview and t.strip():
            preview = " ".join(t.split())[:70]

    chars_per_page = total_chars / max(len(sample_idx), 1)

    # A normal text page has 1000-3000 characters.
    # Near zero means the PDF is images of pages -> needs OCR.
    if chars_per_page < 50:
        verdict = "SCANNED - needs OCR"
    elif chars_per_page < 300:
        verdict = "SPARSE - check it"
    else:
        verdict = "text OK"

    return n_pages, chars_per_page, verdict, preview


def main():
    with open(os.path.join(ROOT, "metadata.csv"), encoding="utf-8") as fh:
        docs = list(csv.DictReader(fh))

    print(f"{'document_id':24s} {'pages':>6s} {'chars/pg':>9s}  {'verdict':20s} preview")
    print("-" * 110)

    problems = []
    for d in docs:
        path = os.path.join(RAW, d["filename"])
        if not os.path.exists(path):
            print(f"{d['document_id']:24s}  (file not found)")
            continue

        pages, cpp, verdict, preview = inspect(path)
        print(f"{d['document_id']:24s} {pages:6d} {cpp:9.0f}  {verdict:20s} {preview}")

        if verdict != "text OK":
            problems.append((d["document_id"], verdict, pages))

    print("\n" + "=" * 60)
    if problems:
        print("NEEDS ATTENTION:")
        for doc_id, verdict, pages in problems:
            print(f"  {doc_id:24s} {verdict}  ({pages} pages)")
    else:
        print("All PDFs have extractable text. Good to proceed.")

    print("\nSANITY CHECK - open these and confirm the page count looks right:")
    print("  A full WHO guideline is usually 100-250 pages.")
    print("  If one is 5-20 pages, you probably downloaded a SUMMARY, not the guideline.")


if __name__ == "__main__":
    main()
