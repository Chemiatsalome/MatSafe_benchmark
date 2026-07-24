"""
Stage 4b: TAG CHUNKS — assign care_phase and stance to every chunk, purely
by keyword/regex rule (NO ML, NO LLM). This is deliberate, not a shortcut:
Section D's safety-labelling protocol consumes these tags, and Section D
commits to "no LLM in ground truth construction." If a model shaped these
tags, that claim would be true only one hop removed from false. See
CORPUS_LOG.md Stage 4b entry for the full reasoning.

Rules are topic-agnostic (same lexicon regardless of pph/hypertension/
sepsis/labour/postnatal) — the language of urgency ("call immediately")
and reassurance ("this is normal") doesn't meaningfully vary by symptom,
and a single auditable rule set is easier for a clinician to validate than
five topic-specific ones.

stance:
  alarm cues only     -> alarm
  reassure cues only  -> reassure
  both present         -> mixed
  neither              -> neutral   (expected majority: most guideline
                                      prose is neutral clinical procedure)

care_phase: checked in this precedence order, first match wins. The order
itself is a safety-first value judgment — an ambiguous chunk is presumed
"recognition" before it is presumed "background":
  1. recognition  2. acute  3. treatment  4. prevention  5. recovery
  6. background (fallback, no pattern needed)

Output: chunks_tagged/{strategy}_{size}.csv — same rows as chunks/, plus
care_phase and stance columns. chunks/ itself is left untouched, matching
every other stage transition in this pipeline.

Also writes validation_sample.csv: a stratified sample (~20 chunks per
topic, drawn from the para_500 chunk set) with the rule's output shown
alongside chunk text and blank columns for a clinician to mark agree/
disagree. This is the "clinician validates the RULES and a sample" step
the pipeline has committed to since Stage 4b was first scoped.

Run:  python tag_chunks.py
"""
import csv
import os
import random
import re

ROOT = "Maternal_RAG_Corpus"
CHUNKS_IN = os.path.join(ROOT, "chunks")
CHUNKS_OUT = os.path.join(ROOT, "chunks_tagged")
RANDOM_STATE = 42

ALARM_PATTERNS = [
    r"\bcall\b[^.]{0,40}\b(immediately|right away|urgently|now)\b",
    r"\bseek\b[^.]{0,20}\b(emergency|immediate|urgent)\b[^.]{0,20}\b(care|medical attention|help)\b",
    r"\bgo to\b[^.]{0,20}\b(hospital|a&e|emergency room|er)\b",
    r"\bcall\s+(911|999|112)\b",
    r"\b(danger|warning) sign",
    r"\bdo not wait\b",
    r"\blife-threatening\b",
    r"\bcan be fatal\b",
    r"\bcan lead to death\b",
    r"\burgent(ly)?\b",
    r"\bdon.?t delay\b",
    r"\bget (medical )?help\b[^.]{0,20}\b(right away|immediately|straight away|as soon as possible)\b",
    r"\bcontact your\b[^.]{0,30}\b(immediately|urgently|straight away|right away|as soon as possible)\b",
]

REASSURE_PATTERNS = [
    r"\b(is|'s)\s+normal\b",  # catches "is normal" AND the contraction "It's normal" —
                               # the latter was missed entirely in the first two passes,
                               # including on the project's own flagship example sentence
                               # ("It's normal to get some swelling in pregnancy").
    r"\bis common\b",
    r"\bnothing to worry about\b",
    r"\bgoes? away on (its|their) own\b",
    r"\bno need to worry\b",
    r"\bnot a cause for concern\b",
    r"\btypically (mild|harmless|temporary)\b",
    r"\bvery common\b",
    r"\bquite common\b",
    r"\busually (disappear|resolve|settle|go away|clear up|painless|mild|harmless|gets? better|improves?)\b",
    r"\b(more )?likely to (get better|improve)\b",
    r"\bvery unlikely\b",
    r"\bshould (get better|improve|settle) (on its own|by itself|within)\b",
    r"\bpart of (the )?normal\b",
]

CARE_PHASE_PATTERNS = [
    ("recognition", [
        r"\bsigns? of\b", r"\bsymptoms? of\b", r"\bwatch for\b",
        r"\bdanger signs? include\b",
    ]),
    ("acute", [
        r"\bemergency\b", r"\bimmediately\b", r"\burgent(ly)?\b",
        r"\bcall\b[^.]{0,20}\bnow\b",
    ]),
    ("treatment", [
        r"\btreated with\b", r"\bmanagement includes\b", r"\badminister(ed)?\b",
        r"\bdose\b", r"\biv\b", r"\bsurgery\b", r"\bwith treatment\b",
        r"\btreatment (can|will|usually) help\b",
    ]),
    ("prevention", [
        r"\bto prevent\b", r"\bprophylactic\b", r"\breduce the risk of\b",
    ]),
    ("recovery", [
        r"\bafter birth\b", r"\bpostpartum period\b", r"\breturn to normal\b",
    ]),
]

_alarm_re = [re.compile(p, re.IGNORECASE) for p in ALARM_PATTERNS]
_reassure_re = [re.compile(p, re.IGNORECASE) for p in REASSURE_PATTERNS]
_care_phase_re = [(name, [re.compile(p, re.IGNORECASE) for p in pats])
                   for name, pats in CARE_PHASE_PATTERNS]


def tag_stance(text):
    has_alarm = any(p.search(text) for p in _alarm_re)
    has_reassure = any(p.search(text) for p in _reassure_re)
    if has_alarm and has_reassure:
        return "mixed"
    if has_alarm:
        return "alarm"
    if has_reassure:
        return "reassure"
    return "neutral"


def tag_care_phase(text):
    for name, patterns in _care_phase_re:
        if any(p.search(text) for p in patterns):
            return name
    return "background"


def load_topics():
    """document_id -> first topic (for stratified sampling only)."""
    with open(os.path.join(ROOT, "metadata.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {r["document_id"]: r["topics"].split(";")[0] for r in rows}


def load_declared_stance():
    """document_id -> declared document-level stance (reassure/alarm/mixed),
    read from metadata.csv's notes column (REASSURE:/ALARM:/MIXED: prefix).
    This is human-declared ground truth recorded when the corpus was built
    (CORPUS_LOG.md Table 4), not a model output -- using it to cross-check
    Stage 4b's rule-based chunk tags is a metadata comparison, not an ML
    step, so it doesn't touch the no-LLM boundary."""
    with open(os.path.join(ROOT, "metadata.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    declared = {}
    for r in rows:
        notes = r["notes"].upper()
        for label in ("REASSURE", "ALARM", "MIXED"):
            if notes.startswith(label):
                declared[r["document_id"]] = label.lower()
                break
    return declared


def main():
    os.makedirs(CHUNKS_OUT, exist_ok=True)
    topics = load_topics()
    declared_stance = load_declared_stance()

    fieldnames_out = ["chunk_id", "document_id", "strategy", "size_param",
                       "chunk_index", "start_page", "end_page", "char_count",
                       "care_phase", "stance", "text"]

    stance_counts = {}
    phase_counts = {}
    para_500_rows = []  # for the validation sample
    audit_rows = []     # declared-stance vs rule-tag mismatches, all files

    for fname in sorted(os.listdir(CHUNKS_IN)):
        if not fname.endswith(".csv"):
            continue
        in_path = os.path.join(CHUNKS_IN, fname)
        out_path = os.path.join(CHUNKS_OUT, fname)

        with open(in_path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        with open(out_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames_out)
            writer.writeheader()
            for r in rows:
                stance = tag_stance(r["text"])
                phase = tag_care_phase(r["text"])
                r["stance"] = stance
                r["care_phase"] = phase
                writer.writerow({k: r[k] for k in fieldnames_out})

                stance_counts.setdefault(fname, {}).setdefault(stance, 0)
                stance_counts[fname][stance] += 1
                phase_counts.setdefault(fname, {}).setdefault(phase, 0)
                phase_counts[fname][phase] += 1

                if fname == "para_500.csv":
                    r["topic"] = topics.get(r["document_id"], "unknown")
                    para_500_rows.append(r)

                declared = declared_stance.get(r["document_id"])
                if declared in ("reassure", "alarm") and stance != declared:
                    audit_rows.append({
                        "document_id": r["document_id"], "declared_stance": declared,
                        "chunk_id": r["chunk_id"], "strategy": fname,
                        "rule_stance": stance, "text": r["text"],
                    })

    print(f"{'file':16s} {'reassure':>9s} {'alarm':>7s} {'neutral':>8s} {'mixed':>7s}")
    print("-" * 55)
    for fname in sorted(stance_counts):
        c = stance_counts[fname]
        total = sum(c.values())
        print(f"{fname:16s} "
              f"{c.get('reassure', 0):9d} {c.get('alarm', 0):7d} "
              f"{c.get('neutral', 0):8d} {c.get('mixed', 0):7d}   (n={total})")

    print()
    print(f"{'file':16s} {'recognition':>11s} {'acute':>6s} {'treatment':>9s} "
          f"{'prevention':>10s} {'recovery':>8s} {'background':>10s}")
    print("-" * 90)
    for fname in sorted(phase_counts):
        c = phase_counts[fname]
        print(f"{fname:16s} "
              f"{c.get('recognition', 0):11d} {c.get('acute', 0):6d} "
              f"{c.get('treatment', 0):9d} {c.get('prevention', 0):10d} "
              f"{c.get('recovery', 0):8d} {c.get('background', 0):10d}")

    # --- declared-stance cross-check (Table 4 ground truth vs rule tags) ---
    audit_path = os.path.join(ROOT, "stance_audit.csv")
    with open(audit_path, "w", encoding="utf-8", newline="") as f:
        fieldnames = ["document_id", "declared_stance", "chunk_id", "strategy",
                      "rule_stance", "text"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(audit_rows)

    print()
    from collections import Counter
    per_doc = Counter(r["document_id"] for r in audit_rows if r["strategy"] == "para_500.csv")
    print(f"Declared-stance cross-check (para_500 only): "
          f"{sum(per_doc.values())} mismatched chunks -> {audit_path}")
    for doc_id, n in sorted(per_doc.items()):
        print(f"  {doc_id:28s} {n} chunk(s) declared {declared_stance[doc_id]} "
              f"but not rule-tagged {declared_stance[doc_id]}")

    # --- validation sample from para_500, stratified by STANCE not topic ---
    # Stance (not topic) drives the sample: reassure/alarm/mixed are rare
    # (~2% of chunks), so a topic-stratified sample is >95% neutral by
    # chance -- a poor use of a clinician's limited review time, and it
    # would have hidden the false-positive bug found in this same file's
    # docstring (a "reassure" mislabel from "is common" firing on an
    # unrelated sentence). Every non-neutral chunk is included; neutral
    # chunks get a random sample of matched size, for false-negative
    # spot-checking (rules missing real alarm/reassure content).
    random.seed(RANDOM_STATE)
    non_neutral = [r for r in para_500_rows if r["stance"] != "neutral"]
    neutral = [r for r in para_500_rows if r["stance"] == "neutral"]
    k_neutral = min(len(non_neutral), len(neutral))
    sample = non_neutral + random.sample(neutral, k_neutral)
    random.shuffle(sample)

    sample_path = os.path.join(ROOT, "validation_sample.csv")
    with open(sample_path, "w", encoding="utf-8", newline="") as f:
        fieldnames = ["chunk_id", "document_id", "topic", "care_phase", "stance",
                      "text", "clinician_agrees_care_phase",
                      "clinician_agrees_stance", "clinician_notes"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in sample:
            writer.writerow({
                "chunk_id": r["chunk_id"], "document_id": r["document_id"],
                "topic": r["topic"], "care_phase": r["care_phase"],
                "stance": r["stance"], "text": r["text"],
                "clinician_agrees_care_phase": "", "clinician_agrees_stance": "",
                "clinician_notes": "",
            })

    print(f"\nValidation sample: {len(sample)} chunks "
          f"({len(non_neutral)} non-neutral + {k_neutral} neutral) -> {sample_path}")


if __name__ == "__main__":
    main()
