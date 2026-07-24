"""
Stage 7a: ENCODE QUERIES -- embed all 40 frozen queries with each of the 3
models, applying each model's documented query-prefix convention (imported
from encode_chunks.py's MODELS list, not redefined here, so the two can't
drift apart). torch/sentence-transformers only, never faiss -- same
process-separation reasoning as encode_chunks.py (see CORPUS_LOG.md Stage 5
entry for the segfault this avoids).

Output: Maternal_RAG_Corpus/query_embeddings/{model_key}.npy (rows in the
same order as query_set.csv) + query_embeddings/{model_key}_query_ids.json.

Run:  python encode_queries.py
"""
import csv
import json
import os

import numpy as np
from sentence_transformers import SentenceTransformer

from encode_chunks import MODELS

ROOT = "Maternal_RAG_Corpus"
OUT_DIR = os.path.join(ROOT, "query_embeddings")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    with open(os.path.join(ROOT, "query_set.csv"), encoding="utf-8") as f:
        queries = list(csv.DictReader(f))
    query_ids = [q["query_id"] for q in queries]

    for model_spec in MODELS:
        print(f"=== {model_spec['key']} ({model_spec['hf_name']}) ===")
        try:
            model = SentenceTransformer(model_spec["hf_name"])
        except Exception as e:
            print(f"  SKIPPING {model_spec['key']}: failed to load ({e})")
            continue

        texts = [model_spec["query_prefix"] + q["query_text"] for q in queries]
        embeddings = model.encode(texts, convert_to_numpy=True)

        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        embeddings = (embeddings / norms).astype("float32")

        np.save(os.path.join(OUT_DIR, f"{model_spec['key']}.npy"), embeddings)
        with open(os.path.join(OUT_DIR, f"{model_spec['key']}_query_ids.json"), "w", encoding="utf-8") as f:
            json.dump(query_ids, f)

        print(f"  encoded {len(queries)} queries, dim {embeddings.shape[1]}, "
              f"prefix applied: {model_spec['query_prefix'] or '(none)'}")

    print("\nDone.")


if __name__ == "__main__":
    main()
