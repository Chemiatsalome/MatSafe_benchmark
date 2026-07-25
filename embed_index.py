"""
Stage 5: EMBED & INDEX -- orchestrator. Runs encode_chunks.py and
build_faiss_index.py as two SEPARATE python subprocesses (not two imports
in this process), because faiss + torch loaded together in one process
segfaults reproducibly on this setup (confirmed directly, see
CORPUS_LOG.md). Process-level separation guarantees the two native
libraries never share a memory space, regardless of Python import caching.

LOCAL RUN ABANDONED 2026-07-23: after the segfault fix, a real local test
showed CPU-only encoding across 3 models x 6 chunk sets (55,597 total
chunks) would take an estimated 6-8 hours -- MiniLM alone took ~50min for
its 6 sets before the run was intentionally stopped in favor of GPU. See
CORPUS_LOG.md and MatSafe_Embedding_Colab.ipynb. This script and
encode_chunks.py / build_faiss_index.py are unchanged and remain correct
for local use (e.g. a future machine with a working faiss/torch
combination and/or GPU) -- only the *environment* changed, not the logic.

Run:  python embed_index.py
"""
import subprocess
import sys


def run(script):
    print(f"\n{'=' * 70}\nRunning {script}\n{'=' * 70}")
    result = subprocess.run([sys.executable, script])
    if result.returncode != 0:
        raise SystemExit(f"{script} failed with exit code {result.returncode}")


if __name__ == "__main__":
    run("encode_chunks.py")
    run("build_faiss_index.py")
    print("\nStage 5 complete.")
