"""
Stage 1 check: which PDFs have I actually downloaded?
Run any time:  python check_corpus.py
"""
import csv
import os

ROOT = "Maternal_RAG_Corpus"
RAW = os.path.join(ROOT, "raw_pdfs")


def main():
    with open(os.path.join(ROOT, "metadata.csv"), encoding="utf-8") as fh:
        docs = list(csv.DictReader(fh))

    have, missing = [], []
    for d in docs:
        path = os.path.join(RAW, d["filename"])
        (have if os.path.exists(path) else missing).append(d)

    print(f"HAVE ({len(have)}/{len(docs)}):")
    for d in have:
        size = os.path.getsize(os.path.join(RAW, d["filename"])) / 1e6
        print(f"   {d['document_id']:24s} {size:6.1f} MB")

    print(f"\nMISSING ({len(missing)}):")
    for d in missing:
        print(f"   {d['document_id']:24s} {d['url']}")

    # coverage check: does every topic have a guideline AND patient material?
    print("\nCOVERAGE (guideline / patient education per topic):")
    topics = ["pph", "hypertension", "sepsis", "labour", "postnatal"]
    for t in topics:
        g = [d["document_id"] for d in have
             if t in d["topics"].split(";") and d["document_type"] in ("guideline", "standard")]
        p = [d["document_id"] for d in have
             if t in d["topics"].split(";") and d["document_type"] == "patient_education"]
        flag = "" if (g and p) else "   <-- GAP"
        print(f"   {t:14s} guideline={len(g)}  patient={len(p)}{flag}")

    print("\nA topic needs BOTH to produce the ambiguity you're studying.")


if __name__ == "__main__":
    main()
