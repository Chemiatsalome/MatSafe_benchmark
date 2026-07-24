"""One-time fix: make the CSV's filename column match how the PDFs are actually named."""
import csv, os

META = os.path.join("Maternal_RAG_Corpus", "metadata.csv")

with open(META, encoding="utf-8") as fh:
    rows = list(csv.DictReader(fh))
    headers = rows[0].keys()

for r in rows:
    r["filename"] = r["document_id"] + ".pdf"

with open(META, "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=headers)
    w.writeheader()
    w.writerows(rows)

print("Fixed. filename is now document_id + .pdf for all", len(rows), "rows.")