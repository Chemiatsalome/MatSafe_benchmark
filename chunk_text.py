"""
Stage 4: CHUNK — turn cleaned_text/ into chunk sets under two strategies,
each swept across three target sizes. Chunk strategy is an experimental
variable (see CORPUS_LOG.md Stage 7 grid: encoder x retriever x k x
chunk-strategy), so this stage's job is to produce multiple honestly
comparable chunkings, not to pick a single "best" one.

Strategies:
  fixed  — sliding character window with overlap. The naive baseline most
           RAG systems actually use in production. Can split mid-sentence.
  para   — paragraph/sentence-aware. Never splits a sentence: sentences are
           greedily packed into a chunk up to the target size, and a chunk
           is closed (even under-full) rather than cut mid-sentence. If a
           single sentence exceeds the target size, it becomes its own
           over-target chunk rather than being truncated.

Sizes swept for both: 300 / 500 / 800 characters.

Page provenance: cleaned_text/*.txt still contains literal "[PAGE n]"
markers (Stage 3 keeps them deliberately). Both strategies record which
page(s) each chunk came from. For `para`, a paragraph is never split
across pages by construction (each page's body is parsed independently),
so a paragraph that truly continues across a page break will appear as
two chunks with adjacent page numbers rather than one — a known,
documented limitation, not a silent one.

Sentence splitting is a regex heuristic (`SENTENCE_SPLIT_RE`): splits on
.!? followed by whitespace and a capital letter/opening paren. This will
occasionally mis-split on abbreviations (e.g. "Dr. Russell", "No. 5") —
acceptable for a first pass, documented rather than hidden.

Run:  python chunk_text.py
"""
import csv
import os
import re
from bisect import bisect_right

ROOT = "Maternal_RAG_Corpus"
IN = os.path.join(ROOT, "cleaned_text")
OUT = os.path.join(ROOT, "chunks")

PAGE_MARKER_RE = re.compile(r"\[PAGE (\d+)\]\n")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")

SIZES = [300, 500, 800]
FIXED_OVERLAP_FRAC = 0.15


def parse_pages(cleaned_text):
    """'[PAGE n]\\nbody...' repeated -> [(page_num:int, body:str), ...]"""
    parts = PAGE_MARKER_RE.split(cleaned_text)[1:]  # drop text before first marker (should be empty)
    pages = []
    for i in range(0, len(parts), 2):
        pages.append((int(parts[i]), parts[i + 1].strip()))
    return pages


# ---------- fixed-size ----------

def flatten_for_fixed(pages):
    """Concatenate page bodies; return (flat_text, boundaries) where
    boundaries[i] = (start_offset_of_page_i, page_num)."""
    flat = []
    boundaries = []
    offset = 0
    for page_num, body in pages:
        boundaries.append((offset, page_num))
        flat.append(body)
        offset += len(body) + 1  # +1 for the join separator below
        flat.append(" ")
    return "".join(flat), boundaries


def page_for_offset(boundaries, offset):
    starts = [b[0] for b in boundaries]
    idx = bisect_right(starts, offset) - 1
    idx = max(0, min(idx, len(boundaries) - 1))
    return boundaries[idx][1]


def fixed_size_chunks(pages, size):
    flat, boundaries = flatten_for_fixed(pages)
    overlap = int(size * FIXED_OVERLAP_FRAC)
    step = max(size - overlap, 1)

    chunks = []
    i = 0
    while i < len(flat):
        text = flat[i:i + size].strip()
        if len(text) >= 20:  # skip trailing scraps
            start_page = page_for_offset(boundaries, i)
            end_page = page_for_offset(boundaries, min(i + len(text) - 1, len(flat) - 1))
            chunks.append({
                "text": text, "start_page": start_page, "end_page": end_page,
            })
        if i + size >= len(flat):
            break  # last window already consumed the remainder via slice truncation
        i += step
    return chunks


# ---------- paragraph/sentence-aware ----------

def split_sentences(block):
    sentences = SENTENCE_SPLIT_RE.split(block.strip())
    return [s.strip() for s in sentences if s.strip()]


def page_blocks(pages):
    """[(page_num, block_text), ...] — a block is a blank-line-separated
    unit within one page, with internal line-wraps reflowed to spaces."""
    out = []
    for page_num, body in pages:
        for raw_block in re.split(r"\n\s*\n", body):
            reflowed = " ".join(l.strip() for l in raw_block.split("\n") if l.strip())
            if reflowed:
                out.append((page_num, reflowed))
    return out


def paragraph_aware_chunks(pages, target_size):
    blocks = page_blocks(pages)
    units = []  # (page_num, sentence_text)
    for page_num, block in blocks:
        for sent in split_sentences(block):
            units.append((page_num, sent))

    chunks = []
    cur_texts, cur_pages = [], []
    cur_len = 0

    def close_chunk():
        if cur_texts:
            text = " ".join(cur_texts)
            chunks.append({
                "text": text,
                "start_page": cur_pages[0],
                "end_page": cur_pages[-1],
            })

    for page_num, sent in units:
        added_len = len(sent) + (1 if cur_texts else 0)
        if cur_texts and cur_len + added_len > target_size:
            close_chunk()
            cur_texts, cur_pages, cur_len = [], [], 0
            added_len = len(sent)
        cur_texts.append(sent)
        cur_pages.append(page_num)
        cur_len += added_len
    close_chunk()
    return chunks


# ---------- driver ----------

def write_chunks(doc_id, strategy, size, chunks, writer):
    for idx, c in enumerate(chunks):
        writer.writerow({
            "chunk_id": f"{doc_id}__{strategy}_{size}__{idx:04d}",
            "document_id": doc_id,
            "strategy": strategy,
            "size_param": size,
            "chunk_index": idx,
            "start_page": c["start_page"],
            "end_page": c["end_page"],
            "char_count": len(c["text"]),
            "text": c["text"],
        })


def main():
    os.makedirs(OUT, exist_ok=True)
    doc_ids = sorted(
        f[:-4] for f in os.listdir(IN) if f.endswith(".txt")
    )

    fieldnames = ["chunk_id", "document_id", "strategy", "size_param",
                  "chunk_index", "start_page", "end_page", "char_count", "text"]

    summary = []
    for strategy in ("fixed", "para"):
        for size in SIZES:
            out_path = os.path.join(OUT, f"{strategy}_{size}.csv")
            with open(out_path, "w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=fieldnames)
                writer.writeheader()
                n_chunks = 0
                for doc_id in doc_ids:
                    with open(os.path.join(IN, f"{doc_id}.txt"), encoding="utf-8") as src:
                        pages = parse_pages(src.read())
                    if strategy == "fixed":
                        chunks = fixed_size_chunks(pages, size)
                    else:
                        chunks = paragraph_aware_chunks(pages, size)
                    write_chunks(doc_id, strategy, size, chunks, writer)
                    n_chunks += len(chunks)
            summary.append((strategy, size, n_chunks, out_path))

    print(f"{'strategy':10s} {'size':>6s} {'n_chunks':>10s}  file")
    print("-" * 60)
    for strategy, size, n_chunks, out_path in summary:
        print(f"{strategy:10s} {size:6d} {n_chunks:10d}  {out_path}")


if __name__ == "__main__":
    main()
