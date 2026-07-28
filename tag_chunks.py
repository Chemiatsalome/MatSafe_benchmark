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
care_phase, stance, topics, and is_boilerplate columns. chunks/ itself is
left untouched, matching every other stage transition in this pipeline.
Boilerplate rows (table of contents, figure/table indices, collapsed
glossary/acronym tables, GRADE evidence-judgement tables) are NOT dropped
from chunks_tagged/ -- they stay for audit -- but are flagged so
encode_chunks.py can exclude them from the embedding index. Two independent
signals, both calibrated against the actual corpus rather than assumed
(see CORPUS_LOG.md Stage 4b boilerplate entry): a run of 2+ dot-leaders
(".......... 123", the TOC/index signature -- 28 and 9 hits on the two
cited examples vs 1/500 in a random sample) or the combination of zero
sentence-ending punctuation AND zero bullet characters on a chunk of 300+
characters (catches collapsed two-column tables that lost their structure
in linear PDF extraction). The second signal was checked against, not just
assumed: an earlier "acronym density" heuristic and a bare
"zero-sentence-endings" rule were both tried and rejected because they
misfired on legitimate bulleted clinical checklists (e.g. a home-birth
newborn-care action list) that must stay retrievable -- requiring the
absence of bullets too is what makes this precise enough to ship.

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
    r"\bcan result in death\b",
    r"\bdeath may occur\b",
    r"\burgent(ly)?\b",
    r"\bdon.?t delay\b",
    r"\bget (medical )?help\b[^.]{0,20}\b(right away|immediately|straight away|as soon as possible)\b",
    r"\bcontact your\b[^.]{0,30}\b(immediately|urgently|straight away|right away|as soon as possible)\b",
]

# Negation guard: a match immediately preceded by one of these tokens is a
# negated/hedged statement, not an alarm cue -- "NON-LIFE-THREATENING
# CONDITIONS" must not tag as alarm just because "life-threatening" is a
# substring. Checked against a short window before the match start, not the
# whole preceding sentence, so it only catches the tight "non-X"/"not X"
# construction and doesn't accidentally swallow unrelated earlier negations.
NEGATION_WINDOW = 12
_negation_re = re.compile(r"\b(non|not|no|isn.?t|without|unless)[\s-]*$", re.IGNORECASE)

# Numeric-adjacency guard: reassure cues like "is normal" / "is common" are
# written for a symptom or condition in genuine patient-facing reassurance
# ("It's normal to get some swelling"), but the identical phrase also closes
# out a lab reference range ("Base excess of +/-2 is normal") or a
# prevalence statistic ("Anaemia in pregnancy is common in Africa") inside
# an otherwise alarm-toned clinical/diagnostic chunk. A digit immediately
# before the match is the tell -- genuine reassurance prose doesn't open
# with a bare number right before the cue phrase.
NUMERIC_ADJACENCY_WINDOW = 20
_numeric_re = re.compile(r"\d")

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

# Chunk-level topic assignment. metadata.csv's `topics` column is a
# document-level declaration -- correct for single-topic documents (the
# whole document really is about that one thing), but wrong for the small
# number of omnibus multi-topic manuals (KE_OBSTETRICS_2021,
# KE_MNH_STANDARDS_2023, KE_MCH_HANDBOOK span all 5 topics because they are
# entire national manuals). Inheriting the document's full topic list onto
# every chunk of those documents tagged e.g. a neonatal-nutrition chunk or a
# TB-diagnosis chunk as "pph" just because it shares a PDF with a PPH
# chapter. For documents with more than one declared topic, a chunk only
# keeps a topic if that topic's own keywords actually appear in the chunk
# text -- intersected with the document's declared set, so a chunk can
# never be assigned a topic the document wasn't already tagged with.
# Single-topic documents are untouched: no keyword check, pure inheritance,
# because there's no ambiguity to resolve.
TOPIC_PATTERNS = {
    "pph": [
        # "haemorrhage" has an extra vowel over "hemorrhage" (h-A-emorrhage
        # vs h-emorrhage), not an either/or single-letter swap -- ha?emorrhage
        # is the correct optional-letter form for both spellings.
        r"\bpostpartum ha?emorrhage\b", r"\bpph\b", r"\buterine atony\b",
        r"\batonic uterus\b", r"\bretained placenta\b", r"\btranexamic acid\b",
        r"\buterotonic", r"\bpostpartum bleeding\b", r"\bexcessive (vaginal )?bleeding\b",
        r"\bthird stage of labour\b",
        # lay/patient-facing phrasing (this benchmark's corpus is roughly
        # half patient education material, which describes PPH by symptom
        # rather than by clinical name):
        r"\blochia\b", r"\bblood clots?\b", r"\bheavy bleeding\b",
        r"\bbleeding\b[^.]{0,30}\b(after (birth|delivery|childbirth)|postpartum)\b",
        r"\bsoaking\b[^.]{0,20}\bpads?\b",
    ],
    "hypertension": [
        r"\bpre-?eclampsia\b", r"\beclampsia\b", r"\bhypertension\b",
        r"\bhigh blood pressure\b", r"\bblood pressure\b", r"\bproteinuria\b",
        r"\bmagnesium sulf[a]?te\b", r"\bhellp\b", r"\bdiastolic\b", r"\bsystolic\b",
        # lay/patient-facing phrasing. Deliberately excludes bare "blurred
        # vision" / "changes in vision" -- visual disturbance on its own is
        # nonspecific (it's a listed DKA symptom in this same corpus, e.g.
        # KE_OBSTETRICS_2021__para_500__0543) and produced a cross-topic
        # false positive when tried. "seeing spots" is kept: idiomatic
        # pre-eclampsia phrasing, not used for other conditions in this
        # corpus.
        r"\bheadache\b[^.]{0,20}\b(won.?t go away|gets? worse|that (won.?t|will not) (go away|stop))\b",
        r"\bseeing spots\b",
        r"\bswell(ing|en)\b[^.]{0,15}\b(hands?|face|feet|ankles?|fingers?)\b",
    ],
    "sepsis": [
        r"\bsepsis\b", r"\bseptic\b", r"\bchorioamnionitis\b",
        r"\bpuerperal (fever|infection|sepsis)\b", r"\bendometritis\b",
        r"\bmaternal infection\b", r"\bantibiotics?\b",
        # lay/patient-facing phrasing:
        r"\bfever\b", r"\bchills\b", r"\btemperature of\b",
    ],
    "labour": [
        r"\blabour\b", r"\blabor\b", r"\bcontractions?\b", r"\bcervi(x|cal)\b",
        r"\bdilat(ation|ion|ed)\b", r"\bintrapartum\b", r"\bfetal heart rate\b",
        r"\bstages? of labour\b", r"\bonset of labour\b", r"\bbraxton hicks\b",
    ],
    "postnatal": [
        r"\bpostnatal\b", r"\bpostpartum period\b", r"\bpostpartum depression\b",
        r"\bbaby blues\b", r"\bbreastfeeding\b", r"\bnewborn care\b",
        r"\bsix weeks after (the )?birth\b", r"\bpostpartum check\b", r"\blochia\b",
        # lay/patient-facing phrasing:
        r"\bthoughts?\b[^.]{0,20}\bharming\b[^.]{0,20}\b(yourself|myself|your baby|my baby)\b",
        r"\boverwhelming tiredness\b",
    ],
}
_topic_re = {name: [re.compile(p, re.IGNORECASE) for p in pats]
             for name, pats in TOPIC_PATTERNS.items()}


def assign_chunk_topics(text, declared_topics):
    """declared_topics: list of topics from metadata.csv for this document."""
    if len(declared_topics) <= 1:
        return declared_topics
    return [t for t in declared_topics
            if any(p.search(text) for p in _topic_re.get(t, []))]


# --- boilerplate detection (table of contents, figure/table indices,
# collapsed glossary/reference tables) -- see module docstring for the
# calibration behind both signals. ---
_DOT_LEADER_RE = re.compile(r"\.{4,}\s*\d")
_SENTENCE_END_RE = re.compile(r"[.!?](?!\.)(?:\s|$)")
_BULLET_RE = re.compile(r"[•●▪‣⁃]")
BOILERPLATE_MIN_LEN = 300
DOT_LEADER_MIN_COUNT = 2


def is_boilerplate(text, strategy):
    """strategy: 'fixed' or 'para', from the chunk's own row.

    The dot-leader signal holds for both strategies (a TOC/index page is
    dense with "....... 123" runs regardless of where a fixed-size window
    happens to start). The zero-sentence-punctuation signal does NOT: a
    `fixed` window is a raw character slice with no respect for sentence
    boundaries, so it can easily land entirely inside one real sentence and
    contain no period at all (verified -- e.g. a WHO_PPH_2025 fixed_300
    slice mid-sentence about guideline scope tripped this exact false
    positive). A `para` chunk is sentence-complete by construction
    (chunk_text.py never splits mid-sentence), so lacking any terminal
    punctuation there is a real signal, not a slicing artifact -- this
    check is restricted to `para` for that reason.
    """
    if len(_DOT_LEADER_RE.findall(text)) >= DOT_LEADER_MIN_COUNT:
        return True
    if strategy != "para" or len(text) < BOILERPLATE_MIN_LEN:
        return False
    return not _SENTENCE_END_RE.search(text) and not _BULLET_RE.search(text)


def _has_unnegated_match(text, compiled_patterns):
    for p in compiled_patterns:
        for m in p.finditer(text):
            window = text[max(0, m.start() - NEGATION_WINDOW):m.start()]
            if not _negation_re.search(window):
                return True
    return False


def _has_non_numeric_match(text, compiled_patterns):
    for p in compiled_patterns:
        for m in p.finditer(text):
            window = text[max(0, m.start() - NUMERIC_ADJACENCY_WINDOW):m.start()]
            if not _numeric_re.search(window):
                return True
    return False


def tag_stance(text):
    has_alarm = _has_unnegated_match(text, _alarm_re)
    has_reassure = _has_non_numeric_match(text, _reassure_re)
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


def load_declared_topics():
    """document_id -> list of declared topics from metadata.csv (may be
    more than one for the omnibus multi-topic manuals)."""
    with open(os.path.join(ROOT, "metadata.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {r["document_id"]: r["topics"].split(";") for r in rows}


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
    declared_topics = load_declared_topics()
    declared_stance = load_declared_stance()

    fieldnames_out = ["chunk_id", "document_id", "strategy", "size_param",
                       "chunk_index", "start_page", "end_page", "char_count",
                       "care_phase", "stance", "topics", "is_boilerplate", "text"]

    stance_counts = {}
    phase_counts = {}
    boilerplate_counts = {}
    para_500_rows = []  # for the validation sample
    audit_rows = []     # declared-stance vs rule-tag mismatches, all files
    topic_reassignment = {}  # multi-topic doc_id -> [n_declared_topics_kept per chunk]

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
                doc_topics = declared_topics.get(r["document_id"], [])
                chunk_topics = assign_chunk_topics(r["text"], doc_topics)
                boilerplate = is_boilerplate(r["text"], r["strategy"])
                r["stance"] = stance
                r["care_phase"] = phase
                r["topics"] = ";".join(chunk_topics)
                r["is_boilerplate"] = str(boilerplate)
                writer.writerow({k: r[k] for k in fieldnames_out})

                stance_counts.setdefault(fname, {}).setdefault(stance, 0)
                stance_counts[fname][stance] += 1
                phase_counts.setdefault(fname, {}).setdefault(phase, 0)
                phase_counts[fname][phase] += 1
                boilerplate_counts.setdefault(fname, [0, 0])
                boilerplate_counts[fname][1] += 1
                if boilerplate:
                    boilerplate_counts[fname][0] += 1

                if fname == "para_500.csv":
                    r["topic"] = chunk_topics[0] if chunk_topics else "none"
                    para_500_rows.append(r)
                    if len(doc_topics) > 1:
                        topic_reassignment.setdefault(r["document_id"], []).append(len(chunk_topics))

                declared = declared_stance.get(r["document_id"])
                if declared in ("reassure", "alarm") and stance != declared:
                    audit_rows.append({
                        "document_id": r["document_id"], "declared_stance": declared,
                        "chunk_id": r["chunk_id"], "strategy": fname,
                        "rule_stance": stance, "text": r["text"],
                    })

    print()
    print("Boilerplate flags (excluded from the embedding index by encode_chunks.py):")
    for fname in sorted(boilerplate_counts):
        n_boiler, n_total = boilerplate_counts[fname]
        print(f"  {fname:16s} {n_boiler:5d} / {n_total:5d} ({n_boiler/n_total:.1%})")

    print()
    print("Chunk-level topic reassignment (multi-topic documents, para_500 only):")
    print(f"{'document_id':28s} {'n_chunks':>9s} {'0_topics':>9s} {'1_topic':>8s} {'2+_topics':>10s}")
    for doc_id, counts in sorted(topic_reassignment.items()):
        n = len(counts)
        n0 = sum(1 for c in counts if c == 0)
        n1 = sum(1 for c in counts if c == 1)
        n2 = sum(1 for c in counts if c >= 2)
        print(f"{doc_id:28s} {n:9d} {n0:9d} {n1:8d} {n2:10d}")

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
    # utf-8-sig, not utf-8: this file is meant to be opened in Excel by a
    # human reviewer. A BOM-less UTF-8 CSV gets misread by Excel as
    # Windows-1252, turning every bullet/curly-quote/en-dash the PDF
    # extraction correctly captured (U+2022/U+2019/U+2013) into "â€¢"-style
    # garbage -- the text itself was never corrupted, Excel was guessing
    # wrong. chunks_tagged/*.csv (re-parsed by encode_chunks.py/run_grid.py)
    # deliberately stays plain utf-8 -- adding a BOM there would prepend it
    # to the first column's key name and silently break every r["chunk_id"]
    # lookup downstream.
    with open(audit_path, "w", encoding="utf-8-sig", newline="") as f:
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
    with open(sample_path, "w", encoding="utf-8-sig", newline="") as f:
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
