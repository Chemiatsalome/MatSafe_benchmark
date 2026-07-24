"""
Stage 2: EXTRACT — pull raw text out of each PDF, one .txt per document.

Page boundaries are kept as markers (`[PAGE n]`) so Stage 3 (clean_text.py)
can detect repeated headers/footers by their position on the page, before
those markers are stripped out.

Run:  python extract_text.py
Needs: pip install pypdf
"""
import csv
import os

from pypdf import PdfReader

ROOT = "Maternal_RAG_Corpus"
RAW = os.path.join(ROOT, "raw_pdfs")
OUT = os.path.join(ROOT, "extracted_text")


def extract(path):
    """Return (full_text, n_pages, n_failed_pages)."""
    reader = PdfReader(path)
    n_pages = len(reader.pages)
    parts = []
    n_failed = 0
    for i in range(n_pages):
        try:
            t = reader.pages[i].extract_text() or ""
        except Exception:
            t = ""
            n_failed += 1
        parts.append(f"[PAGE {i + 1}]\n{t}")
    return "\n\n".join(parts), n_pages, n_failed


def main():
    os.makedirs(OUT, exist_ok=True)

    with open(os.path.join(ROOT, "metadata.csv"), encoding="utf-8") as fh:
        docs = list(csv.DictReader(fh))

    print(f"{'document_id':24s} {'pages':>6s} {'chars':>9s} {'failed_pg':>10s}  status")
    print("-" * 70)

    failures = []
    for d in docs:
        doc_id = d["document_id"]
        src = os.path.join(RAW, d["filename"])
        dst = os.path.join(OUT, f"{doc_id}.txt")

        if not os.path.exists(src):
            print(f"{doc_id:24s}  SOURCE PDF NOT FOUND: {src}")
            failures.append((doc_id, "missing PDF"))
            continue

        try:
            text, n_pages, n_failed = extract(src)
        except Exception as e:
            print(f"{doc_id:24s}  EXTRACTION FAILED: {e}")
            failures.append((doc_id, str(e)))
            continue

        with open(dst, "w", encoding="utf-8") as out_fh:
            out_fh.write(text)

        status = "OK" if n_failed == 0 else f"{n_failed} page(s) failed"
        print(f"{doc_id:24s} {n_pages:6d} {len(text):9d} {n_failed:10d}  {status}")

        if len(text.strip()) < 200:
            failures.append((doc_id, "suspiciously little text extracted"))

    print("\n" + "=" * 60)
    if failures:
        print("NEEDS ATTENTION:")
        for doc_id, reason in failures:
            print(f"  {doc_id:24s} {reason}")
    else:
        print(f"All {len(docs)} documents extracted cleanly to {OUT}/")


if __name__ == "__main__":
    main()
