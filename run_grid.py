"""
Stage 7: RUN THE GRID -- the actual evaluation. encoder x chunk-strategy x k,
40 queries each, safety labels via L(d,q). Deliberately imports ONLY
faiss/numpy, never torch/sentence-transformers (query embeddings were
already computed by encode_queries.py) -- same process-separation reasoning
as build_faiss_index.py.

Retriever == encoder for this preliminary paper (no separate reranking/
hybrid retrieval layer built); k in {1, 3, 5}; relevance == NOT OutOfScope
under L(d,q)'s existing topic-match check. All three decisions confirmed
before this script was written -- see CORPUS_LOG.md Stage 7 entry.

Per query, per grid cell (encoder, chunk_set), per k:
  n_relevant  = count of top-k results with label != OutOfScope
  n_safe      = count of top-k results with label == Safe
  n_unsafe    = count of top-k results with label == Unsafe
  Precision@k     = n_relevant / k
  SafePrecision@k = n_safe / k       (Safe implies relevant by construction --
                                       OutOfScope is the only non-relevant
                                       label, so no separate AND is needed)
  Unsafe@k        = n_unsafe / k
  SafetyGap@k     = Precision@k - SafePrecision@k
Safety@1 / Unsafe@1 (Section III.D headline metrics) are exactly
SafePrecision@1 / Unsafe@1 -- computed once, reported under both names in
the aggregate table for direct use in the paper.

Outputs (Maternal_RAG_Corpus/results/):
  raw_retrievals.csv    -- every retrieved chunk, every grid cell, every
                            query. Case-study material for Section V.C.
  query_metrics.csv     -- per (query, encoder, chunk_set, k) metric row.
  aggregate_results.csv -- mean across all 40 queries per (encoder,
                            chunk_set, k). The Section V.B baseline table.
  topic_breakdown.csv, urgency_breakdown.csv -- for Section V.D analysis.

Run:  python run_grid.py   (after encode_queries.py has completed)
"""
import csv
import json
import os
from collections import defaultdict

import faiss
import numpy as np

from safety_label import label, SAFE, UNSAFE, OUT_OF_SCOPE

ROOT = "Maternal_RAG_Corpus"
INDEX_ROOT = os.path.join(ROOT, "indexes")
QUERY_EMB_DIR = os.path.join(ROOT, "query_embeddings")
RESULTS_DIR = os.path.join(ROOT, "results")
K_VALUES = [1, 3, 5]
K_MAX = max(K_VALUES)


def load_queries():
    with open(os.path.join(ROOT, "query_set.csv"), encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_chunk_lookup(chunk_set):
    with open(os.path.join(ROOT, "chunks_tagged", chunk_set + ".csv"), encoding="utf-8") as f:
        return {r["chunk_id"]: r for r in csv.DictReader(f)}


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    queries = load_queries()
    query_by_id = {q["query_id"]: q for q in queries}

    raw_rows = []
    metric_rows = []

    for index_name in sorted(os.listdir(INDEX_ROOT)):
        out_dir = os.path.join(INDEX_ROOT, index_name)
        if not os.path.isfile(os.path.join(out_dir, "index.faiss")):
            continue
        model_key, chunk_set = index_name.split("__")

        q_emb_path = os.path.join(QUERY_EMB_DIR, f"{model_key}.npy")
        q_ids_path = os.path.join(QUERY_EMB_DIR, f"{model_key}_query_ids.json")
        if not os.path.isfile(q_emb_path):
            print(f"SKIPPING {index_name}: no query embeddings for {model_key} "
                  f"(run encode_queries.py first)")
            continue

        query_embeddings = np.load(q_emb_path)
        with open(q_ids_path, encoding="utf-8") as f:
            query_ids_in_order = json.load(f)

        index = faiss.read_index(os.path.join(out_dir, "index.faiss"))
        with open(os.path.join(out_dir, "chunk_ids.json"), encoding="utf-8") as f:
            index_chunk_ids = json.load(f)
        chunk_lookup = load_chunk_lookup(chunk_set)

        D, I = index.search(query_embeddings, K_MAX)

        print(f"{index_name}: searched {len(query_ids_in_order)} queries")

        for row_i, query_id in enumerate(query_ids_in_order):
            q = query_by_id[query_id]
            labels_in_rank_order = []

            for rank in range(K_MAX):
                pos = I[row_i][rank]
                score = float(D[row_i][rank])
                chunk_id = index_chunk_ids[pos]
                c = chunk_lookup[chunk_id]
                chunk_topics = c["topics"]

                lbl = label(c["stance"], c["care_phase"], chunk_topics,
                            q["topic"], q["urgency_class"])
                labels_in_rank_order.append(lbl)

                raw_rows.append({
                    "query_id": query_id, "encoder": model_key, "chunk_set": chunk_set,
                    "rank": rank + 1, "score": round(score, 4), "chunk_id": chunk_id,
                    "document_id": c["document_id"], "stance": c["stance"],
                    "care_phase": c["care_phase"], "label": lbl,
                    "topic": q["topic"], "urgency_class": q["urgency_class"],
                    "query_text": q["query_text"],
                })

            for k in K_VALUES:
                top_k = labels_in_rank_order[:k]
                n_relevant = sum(1 for l in top_k if l != OUT_OF_SCOPE)
                n_safe = sum(1 for l in top_k if l == SAFE)
                n_unsafe = sum(1 for l in top_k if l == UNSAFE)
                precision_k = n_relevant / k
                safe_precision_k = n_safe / k
                unsafe_k = n_unsafe / k
                metric_rows.append({
                    "query_id": query_id, "encoder": model_key, "chunk_set": chunk_set,
                    "k": k, "topic": q["topic"], "urgency_class": q["urgency_class"],
                    "precision_at_k": round(precision_k, 4),
                    "safe_precision_at_k": round(safe_precision_k, 4),
                    "unsafe_at_k": round(unsafe_k, 4),
                    "safety_gap_at_k": round(precision_k - safe_precision_k, 4),
                })

    raw_path = os.path.join(RESULTS_DIR, "raw_retrievals.csv")
    with open(raw_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(raw_rows[0].keys()))
        writer.writeheader()
        writer.writerows(raw_rows)
    print(f"\n{len(raw_rows)} raw retrieval rows -> {raw_path}")

    metrics_path = os.path.join(RESULTS_DIR, "query_metrics.csv")
    with open(metrics_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(metric_rows[0].keys()))
        writer.writeheader()
        writer.writerows(metric_rows)
    print(f"{len(metric_rows)} query-level metric rows -> {metrics_path}")

    # --- aggregate: mean across all 40 queries, per (encoder, chunk_set, k) ---
    groups = defaultdict(list)
    for r in metric_rows:
        groups[(r["encoder"], r["chunk_set"], r["k"])].append(r)

    agg_rows = []
    for (encoder, chunk_set, k), rows in sorted(groups.items()):
        n = len(rows)
        agg = {
            "encoder": encoder, "chunk_set": chunk_set, "k": k, "n_queries": n,
            "precision_at_k": round(sum(r["precision_at_k"] for r in rows) / n, 4),
            "safe_precision_at_k": round(sum(r["safe_precision_at_k"] for r in rows) / n, 4),
            "unsafe_at_k": round(sum(r["unsafe_at_k"] for r in rows) / n, 4),
            "safety_gap_at_k": round(sum(r["safety_gap_at_k"] for r in rows) / n, 4),
        }
        if k == 1:
            agg["safety_at_1"] = agg["safe_precision_at_k"]
            agg["unsafe_at_1"] = agg["unsafe_at_k"]
        agg_rows.append(agg)

    agg_path = os.path.join(RESULTS_DIR, "aggregate_results.csv")
    all_agg_keys = ["encoder", "chunk_set", "k", "n_queries", "precision_at_k",
                     "safe_precision_at_k", "unsafe_at_k", "safety_gap_at_k",
                     "safety_at_1", "unsafe_at_1"]
    with open(agg_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=all_agg_keys)
        writer.writeheader()
        for row in agg_rows:
            writer.writerow({k: row.get(k, "") for k in all_agg_keys})
    print(f"{len(agg_rows)} aggregate grid-cell rows -> {agg_path}")

    # --- breakdowns for Section V.D: by topic, by urgency_class ---
    for breakdown_key, out_name in [("topic", "topic_breakdown.csv"),
                                     ("urgency_class", "urgency_breakdown.csv")]:
        groups2 = defaultdict(list)
        for r in metric_rows:
            groups2[(r["encoder"], r["chunk_set"], r["k"], r[breakdown_key])].append(r)
        rows2 = []
        for (encoder, chunk_set, k, bval), rows in sorted(groups2.items()):
            n = len(rows)
            rows2.append({
                "encoder": encoder, "chunk_set": chunk_set, "k": k, breakdown_key: bval,
                "n_queries": n,
                "safety_gap_at_k": round(sum(r["safety_gap_at_k"] for r in rows) / n, 4),
                "unsafe_at_k": round(sum(r["unsafe_at_k"] for r in rows) / n, 4),
            })
        path2 = os.path.join(RESULTS_DIR, out_name)
        with open(path2, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows2[0].keys()))
            writer.writeheader()
            writer.writerows(rows2)
        print(f"{len(rows2)} rows -> {path2}")


if __name__ == "__main__":
    main()
