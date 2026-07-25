"""
Stage 5b: BUILD FAISS INDEX -- reads the embeddings.npy files written by
encode_chunks.py and builds a FAISS index for each. Deliberately imports
ONLY faiss/numpy, never torch/sentence-transformers -- see encode_chunks.py's
docstring for why (they segfault together in one process on this setup).

Normalization: embeddings were already L2-normalized in encode_chunks.py;
FAISS IndexFlatIP (inner product) on normalized vectors is mathematically
identical to cosine similarity. Stated explicitly, here and in every
manifest, so no downstream code has to guess which convention was used.

Run:  python build_faiss_index.py   (after encode_chunks.py has completed)
"""
import json
import os

import faiss
import numpy as np

ROOT = "Maternal_RAG_Corpus"
INDEX_ROOT = os.path.join(ROOT, "indexes")


def main():
    built = []
    for name in sorted(os.listdir(INDEX_ROOT)):
        out_dir = os.path.join(INDEX_ROOT, name)
        emb_path = os.path.join(out_dir, "embeddings.npy")
        encode_manifest_path = os.path.join(out_dir, "encode_manifest.json")
        if not (os.path.isfile(emb_path) and os.path.isfile(encode_manifest_path)):
            continue

        embeddings = np.load(emb_path)
        with open(encode_manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)

        index = faiss.IndexFlatIP(embeddings.shape[1])
        index.add(embeddings)
        faiss.write_index(index, os.path.join(out_dir, "index.faiss"))

        manifest["normalization"] = (
            "L2-normalized vectors (encode_chunks.py), inner product "
            "(FAISS IndexFlatIP, this script) == cosine similarity"
        )
        manifest["faiss_index_type"] = "IndexFlatIP"
        with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        print(f"  {name}: {index.ntotal} vectors indexed -> {out_dir}/index.faiss")
        built.append(name)

    print(f"\nBuilt {len(built)} FAISS indexes.")
    with open(os.path.join(INDEX_ROOT, "index_summary.json"), "w", encoding="utf-8") as f:
        json.dump({"built": built}, f, indent=2)


if __name__ == "__main__":
    main()
