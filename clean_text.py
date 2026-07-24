"""
Stage 3: CLEAN — strip running headers and standalone page-number lines,
fix line-wrap hyphenation, collapse whitespace. Reads extracted_text/,
writes cleaned_text/. [PAGE n] markers are kept for provenance.

Deliberately does NOT strip footers by frequency. In multi-column
recommendation tables (e.g. WHO_PPH_2025), pypdf's linear text extraction
puts the table's "recommendation strength" cell (REVALIDATED / UPDATED /
NEW / EDITED) last on the page — verbatim-repeated real content that a
naive footer-frequency filter would delete along with true footers. Only
running headers (checked against the SAME frequency logic, tested to be
free of this artifact — see CORPUS_LOG.md Stage 3 notes) and
standalone page-number/roman-numeral lines are stripped.

Also collapses immediately-consecutive duplicate lines within a page (e.g.
UNICEF_DANGER_SIGNS has a decorative background phrase repeated dozens of
times per page, extracted as dozens of identical consecutive lines). This
is narrower than the header/footer logic: it only fires when a line
repeats back-to-back with nothing else between occurrences, which real
prose/table content never does — the REVALIDATED-style table labels above
are separated by other row content, so they are unaffected by this step.

Run:  python clean_text.py
"""
import csv
import os
import re
from collections import Counter

ROOT = "Maternal_RAG_Corpus"
IN = os.path.join(ROOT, "extracted_text")
OUT = os.path.join(ROOT, "cleaned_text")

PAGE_MARKER_RE = re.compile(r"^\[PAGE (\d+)\]$")
PAGE_NUMBER_LINE_RE = re.compile(r"^(\d{1,4}|[ivxlcdm]{1,8})$", re.IGNORECASE)

HEADER_MIN_FRAC = 0.10   # a first-line repeated on >=10% of pages is a running header
HEADER_MAX_LEN = 150     # ignore implausibly long "headers" (probably a real paragraph)


def split_pages(text):
    """[(page_num:int, lines:list[str]), ...]"""
    pages = []
    num, lines = None, []
    for line in text.split("\n"):
        m = PAGE_MARKER_RE.match(line.strip())
        if m:
            if num is not None:
                pages.append((num, lines))
            num, lines = int(m.group(1)), []
        else:
            lines.append(line)
    if num is not None:
        pages.append((num, lines))
    return pages


def strip_page_number_lines(lines):
    return [l for l in lines if not PAGE_NUMBER_LINE_RE.match(l.strip())]


def detect_running_headers(pages):
    counter = Counter()
    for _, lines in pages:
        nonempty = [l.strip() for l in lines if l.strip()]
        if nonempty:
            counter[nonempty[0]] += 1
    n = len(pages) or 1
    return {
        # count >= 2 is required, not just the fraction: on a short document
        # (e.g. a 5-page leaflet) a single unique line already clears 10% of
        # pages, which would wrongly flag one-off content as a "running" header.
        text for text, count in counter.items()
        if count >= 2 and count / n >= HEADER_MIN_FRAC and len(text) <= HEADER_MAX_LEN
    }


def strip_running_headers(pages, headers):
    out = []
    for num, lines in pages:
        new_lines = [l for l in lines if l.strip() not in headers]
        out.append((num, new_lines))
    return out


def collapse_consecutive_duplicates(lines):
    out = []
    prev = None
    for l in lines:
        stripped = l.strip()
        if stripped and stripped == prev:
            continue
        out.append(l)
        if stripped:
            prev = stripped
    return out


def fix_hyphenation(text):
    # line-wrap hyphen: "post-\npartum" -> "postpartum". Only when the next
    # line starts lowercase, to avoid merging genuine end-of-sentence hyphens.
    return re.sub(r"(\w)-\n(?=[a-z])", r"\1", text)


def collapse_whitespace(text):
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_document(raw_text):
    pages = split_pages(raw_text)
    pages = [(n, strip_page_number_lines(l)) for n, l in pages]
    headers = detect_running_headers(pages)
    pages = strip_running_headers(pages, headers)
    pages = [(n, collapse_consecutive_duplicates(l)) for n, l in pages]

    parts = [f"[PAGE {n}]\n{chr(10).join(l).strip()}" for n, l in pages]
    text = "\n\n".join(parts)
    text = fix_hyphenation(text)
    text = collapse_whitespace(text)
    return text, headers


def main():
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(ROOT, "metadata.csv"), encoding="utf-8") as fh:
        docs = list(csv.DictReader(fh))

    print(f"{'document_id':24s} {'chars_in':>9s} {'chars_out':>9s} {'reduction':>9s}  headers stripped")
    print("-" * 90)

    for d in docs:
        doc_id = d["document_id"]
        src = os.path.join(IN, f"{doc_id}.txt")
        dst = os.path.join(OUT, f"{doc_id}.txt")

        if not os.path.exists(src):
            print(f"{doc_id:24s}  MISSING extracted text — run extract_text.py first")
            continue

        raw = open(src, encoding="utf-8").read()
        cleaned, headers = clean_document(raw)

        with open(dst, "w", encoding="utf-8") as out_fh:
            out_fh.write(cleaned)

        reduction = 1 - len(cleaned) / max(len(raw), 1)
        header_preview = "; ".join(sorted(headers))[:60]
        print(f"{doc_id:24s} {len(raw):9d} {len(cleaned):9d} {reduction:8.1%}  {header_preview}")

    print("\nDone. cleaned_text/ written. Footers were NOT frequency-stripped — see")
    print("module docstring for why (table-content collision risk).")


if __name__ == "__main__":
    main()
