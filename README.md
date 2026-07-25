# SafeRetrievalBench (MatSafe)

A benchmark for evaluating RAG retrieval on maternal-health queries, not just
by *relevance* but by *clinical safety*: whether a retriever surfaces a
dangerously reassuring document ahead of urgent clinical guidance for the
same ambiguous symptom (e.g. "some bleeding after birth is normal" vs.
"heavy bleeding requires immediate management," both retrieved for the same
postpartum-bleeding query).

Full design rationale, decisions, and status live in
[CORPUS_LOG.md](CORPUS_LOG.md) — that file is the provenance record; this
README is just the quick-start.

## What's here

- **Corpus** (`Maternal_RAG_Corpus/`): 14 maternal-health documents (WHO,
  Kenya MoH, NHS, CDC, ACOG guidelines + patient education), chunked 2
  strategies × 3 sizes, rule-tagged for `stance` (alarm/reassure/mixed/
  neutral) and `care_phase`.
- **Query set** (`Maternal_RAG_Corpus/query_set.csv`): 40 maternal-health
  queries (32 urgent + 8 routine) across 4 topics — PPH, hypertension,
  labour, postnatal — each grounded in a real quoted passage from a corpus
  document.
- **Safety-labelling function** (`safety_label.py`): `L(d, q)` — given a
  retrieved chunk and a query, returns Safe / Suboptimal / Unsafe /
  OutOfScope from the chunk's stance/care_phase and the query's urgency
  class.
- **Pipeline scripts** (Stages 1–6, see below): reproduce the corpus and
  query set from raw PDFs.

## Who this is for

- **Using the benchmark as-is** (query set + safety labels + tagged
  chunks): you mostly need `Maternal_RAG_Corpus/query_set.csv`,
  `chunks_tagged/` (see Data availability below), and `safety_label.py`.
  Build your own retriever, run it against the chunk corpus, score its
  output with `L(d, q)`.
- **Reproducing or extending the corpus itself** (new documents, chunk
  strategies, tags): run the pipeline stages in order, below.
- **Reproducing the embedding indexes**: use `encode_chunks.py` +
  `build_faiss_index.py` (or `MatSafe_Embedding_Colab.ipynb` on a GPU).

## Data availability

Full document text, chunks, and validation/audit CSVs are **not** in this
repo (see `.gitignore`) — some source PDFs (e.g. `ACOG_POSTPARTUM_
CONDITIONS`) are all-rights-reserved, not redistributable. What's tracked:
`metadata.csv` (document IDs, publishers, source URLs), the pipeline
scripts, `query_set.csv`, and `stats_report.json`. Everything else is
regenerable by running Stages 1–4b yourself against the source URLs in
`metadata.csv`. See the **Note** at the end of
[CORPUS_LOG.md §9](CORPUS_LOG.md#9-reproducibility) for each source's
license terms.

## Pipeline (reproducing the corpus)

Run in order; each stage reads the previous stage's output.

| Stage | Script | Output |
|---|---|---|
| 1 — Collect | `setup_corpus.py`, `fix_filenames.py` | `raw_pdfs/`, `metadata.csv` |
| 1b — Inspect | `check_corpus.py`, `inspect_pdfs.py` | coverage/text-layer check |
| 2 — Extract | `extract_text.py` | `extracted_text/` |
| 3 — Clean | `clean_text.py` | `cleaned_text/` |
| 4 — Chunk | `chunk_text.py` | `chunks/{strategy}_{size}.csv` |
| 4b — Tag | `tag_chunks.py` | `chunks_tagged/{strategy}_{size}.csv` |
| 5 — Embed & index | `encode_chunks.py` + `build_faiss_index.py` (or `embed_index.py` to run both), or `MatSafe_Embedding_Colab.ipynb` on GPU | `indexes/` |
| 6a — Query set | `build_query_set.py` | `query_set.csv` |
| 6b — Safety labels | `safety_label.py` | `L(d, q)` function, used at eval time |
| — | `report_stats.py` | `stats_report.json` — every number cited in the log/paper |

`RANDOM_STATE = 42` is fixed throughout for reproducibility.

## Setup

Python 3.10+. Install what each stage needs:

```bash
pip install pypdf pandas numpy
# Stage 5 (embeddings): pip install torch sentence-transformers faiss-cpu huggingface_hub
```

Stage 5's `encode_chunks.py` and `build_faiss_index.py` are deliberately
run as **separate processes** (`torch`/`sentence-transformers` and `faiss`
loaded together segfault on some Windows CPU setups — see
[CORPUS_LOG.md §6, Stage 5](CORPUS_LOG.md) for the diagnosis). Use
`embed_index.py` to orchestrate both automatically, or run them
individually.

## Status

Stages 1–4b and 6a/6b are complete and frozen (see
[CORPUS_LOG.md §6](CORPUS_LOG.md) for the freeze note). Stage 5 (embed &
index) is in progress. Stage 7 (running the full encoder × retriever × k ×
chunk-strategy grid) has not started.

**Scope note:** this is a preliminary paper/writing sample, not a
submission-track publication — the rule-based `stance`/`care_phase` tags
and safety labels have **not** been independently clinician-validated in
this version. See [CORPUS_LOG.md §7](CORPUS_LOG.md) (Open Issues) before
citing this benchmark's labels as ground truth.

## License

WHO/Kenya MoH source PDFs are CC BY-NC-SA. NHS/CDC content has its own
terms. `ACOG_POSTPARTUM_CONDITIONS` is © ACOG, all rights reserved. See
`metadata.csv` and [CORPUS_LOG.md §9](CORPUS_LOG.md) for per-document
terms and source URLs.

## Contact

Salome Monthe Chemiat — chemiatsalome@gmail.com
