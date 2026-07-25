"""
Stage 5a: ENCODE -- compute embeddings for every (model x chunk set) pair.
Deliberately imports ONLY torch/sentence-transformers, never faiss: on this
Windows setup, loading faiss and PyTorch in the same process segfaults
(reproduced directly -- see CORPUS_LOG.md). Splitting encode and index into
separate process invocations (encode_chunks.py, then build_faiss_index.py,
each run as its own python subprocess by embed_index.py) avoids the two
native libraries ever coexisting in one process's memory space.

Models (2-3, per the paper's V.A plan -- cut the biomedical one first if
compute/download forces a cut; the "not an artefact of one encoder" claim
needs at least two general-purpose models, not one):

  small general:  sentence-transformers/all-MiniLM-L6-v2
                  no documented query/passage prefix convention.
  strong general: intfloat/e5-base-v2
                  REQUIRES "query: " / "passage: " prefixes on queries and
                  passages respectively (https://huggingface.co/intfloat/e5-base-v2).
                  Omitting these silently degrades retrieval in a way that
                  would look like a semantic-similarity failure but would
                  actually be a misconfigured encoder. Applied here on the
                  passage side; queries get "query: " at retrieval time in
                  Stage 7, not here.
  biomedical:     pritamdeka/S-PubMedBert-MS-MARCO (added only if it loads
                  within budget -- checked before committing: ~439MB,
                  retrieval-tuned, no documented prefix requirement).

Chunks are embedded from chunks_tagged/ (the frozen, tagged corpus), not
chunks/, so a retrieved vector's ID always joins back to care_phase/stance
for safety labelling without a separate lookup table.

Output per (model, chunk_set): Maternal_RAG_Corpus/indexes/{key}__{chunk_set}/
  embeddings.npy, chunk_ids.json, encode_manifest.json (model-side info only;
  build_faiss_index.py fills in the rest).

Run:  python encode_chunks.py
"""
import csv
import json
import os
import subprocess
import time

import numpy as np
from huggingface_hub import HfApi
from sentence_transformers import SentenceTransformer

ROOT = "Maternal_RAG_Corpus"
CHUNKS_TAGGED = os.path.join(ROOT, "chunks_tagged")
INDEX_ROOT = os.path.join(ROOT, "indexes")

MODELS = [
    {
        "key": "minilm",
        "hf_name": "sentence-transformers/all-MiniLM-L6-v2",
        "passage_prefix": "",
        "query_prefix": "",
        "tier": "small_general",
    },
    {
        "key": "e5-base",
        "hf_name": "intfloat/e5-base-v2",
        "passage_prefix": "passage: ",
        "query_prefix": "query: ",
        "tier": "strong_general",
    },
    {
        "key": "pubmedbert-msmarco",
        "hf_name": "pritamdeka/S-PubMedBert-MS-MARCO",
        "passage_prefix": "",
        "query_prefix": "",
        "tier": "biomedical",
    },
]


def git_commit_hash():
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except Exception:
        return None


def load_chunk_set(fname):
    with open(os.path.join(CHUNKS_TAGGED, fname), encoding="utf-8") as f:
        return list(csv.DictReader(f))


def encode_one(model, model_sha, load_s, model_spec, chunk_set_name, rows, corpus_commit):
    out_dir = os.path.join(INDEX_ROOT, f"{model_spec['key']}__{chunk_set_name}")
    os.makedirs(out_dir, exist_ok=True)

    texts = [model_spec["passage_prefix"] + r["text"] for r in rows]
    chunk_ids = [r["chunk_id"] for r in rows]

    t0 = time.time()
    embeddings = model.encode(
        texts, batch_size=64, show_progress_bar=False, convert_to_numpy=True,
    )
    encode_s = round(time.time() - t0, 1)

    # L2-normalize here; build_faiss_index.py uses inner product on these
    # already-normalized vectors, which is mathematically == cosine similarity.
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    embeddings = (embeddings / norms).astype("float32")

    np.save(os.path.join(out_dir, "embeddings.npy"), embeddings)
    with open(os.path.join(out_dir, "chunk_ids.json"), "w", encoding="utf-8") as f:
        json.dump(chunk_ids, f)

    manifest = {
        "model_hf_name": model_spec["hf_name"],
        "model_hf_commit_sha": model_sha,
        "model_tier": model_spec["tier"],
        "embedding_dimension": embeddings.shape[1],
        "normalization": "L2-normalized here; inner product at index-build time == cosine similarity",
        "passage_prefix_applied": model_spec["passage_prefix"] or "(none)",
        "query_prefix_to_apply_at_retrieval": model_spec["query_prefix"] or "(none)",
        "chunk_set": chunk_set_name,
        "n_chunks": len(rows),
        "corpus_git_commit": corpus_commit,
        "encode_time_seconds": encode_s,
        "model_load_time_seconds": load_s,
    }
    with open(os.path.join(out_dir, "encode_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"    {len(rows)} chunks -> dim {embeddings.shape[1]}, encode {encode_s}s -> {out_dir}")
    return manifest


def main():
    os.makedirs(INDEX_ROOT, exist_ok=True)
    corpus_commit = git_commit_hash()
    print(f"Corpus git commit: {corpus_commit}")

    chunk_set_files = sorted(os.listdir(CHUNKS_TAGGED))
    built, skipped = [], []

    for model_spec in MODELS:
        print(f"\n=== {model_spec['key']} ({model_spec['hf_name']}) ===")
        print(f"  loading (once, reused across all {len(chunk_set_files)} chunk sets)...")
        t0 = time.time()
        try:
            model = SentenceTransformer(model_spec["hf_name"])
        except Exception as e:
            print(f"  SKIPPING {model_spec['key']}: failed to load ({e})")
            skipped.append(model_spec["key"])
            continue
        load_s = round(time.time() - t0, 1)
        print(f"  loaded in {load_s}s")

        try:
            model_sha = HfApi().model_info(model_spec["hf_name"]).sha
        except Exception:
            model_sha = None

        for fname in chunk_set_files:
            chunk_set_name = fname[:-4]
            rows = load_chunk_set(fname)
            manifest = encode_one(model, model_sha, load_s, model_spec, chunk_set_name, rows, corpus_commit)
            built.append(manifest)

    print(f"\nEncoded {len(built)} (model, chunk_set) pairs. Skipped models: {skipped or 'none'}")
    with open(os.path.join(INDEX_ROOT, "encode_summary.json"), "w", encoding="utf-8") as f:
        json.dump({"built": built, "skipped_models": skipped}, f, indent=2)


if __name__ == "__main__":
    main()
