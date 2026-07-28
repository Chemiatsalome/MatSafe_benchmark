"""
Print Stage 7 grid results to console. Reads Maternal_RAG_Corpus/results/
(written by run_grid.py) -- run this any time you want to eyeball current
numbers without opening the CSVs.

Run:  python show_results.py
"""
import csv
import os

ROOT = "Maternal_RAG_Corpus"
RESULTS = os.path.join(ROOT, "results")


def main():
    path = os.path.join(RESULTS, "aggregate_results.csv")
    if not os.path.exists(path):
        print(f"No results yet -- run run_grid.py first ({path} not found).")
        return

    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    for k in sorted({r["k"] for r in rows}, key=int):
        print(f"\n=== k={k} ===")
        print(f"{'encoder':20s} {'chunk_set':10s} {'precision@k':>12s} "
              f"{'safe_prec@k':>12s} {'unsafe@k':>9s} {'safety_gap@k':>13s}")
        for r in sorted((r for r in rows if r["k"] == k),
                         key=lambda r: (r["encoder"], r["chunk_set"])):
            print(f"{r['encoder']:20s} {r['chunk_set']:10s} "
                  f"{r['precision_at_k']:>12s} {r['safe_precision_at_k']:>12s} "
                  f"{r['unsafe_at_k']:>9s} {r['safety_gap_at_k']:>13s}")


if __name__ == "__main__":
    main()
