"""
Stage 1 setup: create the corpus skeleton + metadata template.
Run once:  python setup_corpus.py
"""
import csv
import os

ROOT = "Maternal_RAG_Corpus"

FOLDERS = [
    "raw_pdfs",        # the PDFs, exactly as downloaded. NEVER edit these.
    "extracted_text",  # Stage 2 output: one .txt per PDF, raw extraction
    "cleaned_text",    # Stage 3 output: one .txt per PDF, cleaned
]

# document_id, filename, title, publisher, document_type, audience,
# country, year, topics, url, notes
DOCUMENTS = [
    # ---------------- CLINICAL GUIDELINES ----------------
    ("WHO_PPH_2025", "WHO_PPH_2025.pdf",
     "Consolidated guidelines for the prevention, diagnosis and treatment of postpartum haemorrhage",
     "WHO", "guideline", "clinician", "Global", 2025, "pph",
     "https://www.who.int/publications/i/item/9789240115637",
     "WHO+FIGO+ICM joint, 51 recommendations. Supersedes older PPH guidance."),

    ("WHO_PRE_2011", "WHO_Preeclampsia_2011.pdf",
     "WHO recommendations for prevention and treatment of pre-eclampsia and eclampsia",
     "WHO", "guideline", "clinician", "Global", 2011, "hypertension",
     "https://www.who.int/publications/i/item/9789241548335",
     "Base guideline. Has 2018/2020/2021 updates - fetch those too."),

    ("WHO_INTRAPARTUM_2018", "WHO_Intrapartum_2018.pdf",
     "WHO recommendations: intrapartum care for a positive childbirth experience",
     "WHO", "guideline", "clinician", "Global", 2018, "labour",
     "https://iris.who.int/server/api/core/bitstreams/7e9a5c8e-4bcc-4eb7-af5f-3381d52e0382/content",
     ""),

    ("WHO_POSTNATAL_2022", "WHO_Postnatal_2022.pdf",
     "WHO recommendations on maternal and newborn care for a positive postnatal experience",
     "WHO", "guideline", "clinician", "Global", 2022, "postnatal",
     "https://www.ncbi.nlm.nih.gov/books/NBK579653/",
     "Birth to 6 weeks. Includes perinatal mental health."),

    ("WHO_SEPSIS_2015", "WHO_Peripartum_Infections_2015.pdf",
     "WHO recommendations for prevention and treatment of maternal peripartum infections",
     "WHO", "guideline", "clinician", "Global", 2015, "sepsis",
     "SEARCH WHO IRIS - verify current version before downloading",
     "Replaces the law-firm infection docs. VERIFY there is no newer edition."),

    # ---------------- KENYA (local layer, spans ALL topics) ----------------
    ("KE_OBSTETRICS_2021", "Kenya_MOH_Obstetrics_2021.pdf",
     "National Guidelines on Quality Obstetrics and Perinatal Care",
     "Kenya MoH", "guideline", "clinician", "Kenya", 2021,
     "pph;hypertension;sepsis;labour;postnatal",
     "https://repository.familyhealth.go.ke/xmlui/handle/123456789/60",
     "SPANS ALL 5 TOPICS - this is why we don't use topic folders. 2021 > the 2015 you had."),

    ("KE_MNH_STANDARDS_2023", "Kenya_MOH_MNH_Standards_2023.pdf",
     "Maternal and Newborn Health Standards",
     "Kenya MoH", "standard", "clinician", "Kenya", 2023,
     "pph;hypertension;sepsis;labour;postnatal",
     "https://repository.familyhealth.go.ke/xmlui/handle/123456789/60",
     "Also spans all topics."),

    # ---------------- PATIENT EDUCATION (the 'reassuring voice') ----------------
    ("KE_MCH_HANDBOOK", "Kenya_Mother_Child_Handbook.pdf",
     "Mother and Child Health Handbook",
     "Kenya MoH", "patient_education", "patient", "Kenya", 2020,
     "pph;hypertension;sepsis;labour;postnatal",
     "https://health.go.ke/sites/default/files/2023-05/Mother%20Child%20Health%20Handbook%20MOH-FOR%20PRINT.pdf",
     "You already had this URL. Local + patient-facing = important."),

    ("CDC_HEAR_HER", "CDC_Hear_Her_Warning_Signs.pdf",
     "Hear Her: Urgent Maternal Warning Signs",
     "CDC", "patient_education", "patient", "USA", 2024,
     "pph;hypertension;sepsis;postnatal",
     "https://www.cdc.gov/hearher/resources/download-share/docs/pdf/Warning-Signs-Poster-LTR-English.pdf",
     "You already had this. The 'alarm' voice."),

    ("UNICEF_DANGER_SIGNS", "UNICEF_Danger_Signs.pdf",
     "Danger signs for women",
     "UNICEF", "patient_education", "patient", "Global", 2024,
     "pph;hypertension;sepsis;labour",
     "https://www.unicef.org/timorleste/media/2386/file/Danger%20signs%20for%20women%20-%20English%20.pdf",
     "You already had this."),

    # ---------------- TODO ----------------
    # We still need a PATIENT-EDUCATION source with a REASSURING voice --
    # something that says "this is normal". Without it you have no ambiguity

   # ---------------- PATIENT EDUCATION: the REASSURING voice ----------------
    ("NHS_POSTNATAL", "NHS_Your_Body_After_Birth.pdf",
     "Your Body After the Birth", "NHS", "patient_education",
     "patient", "UK", 2024, "pph;postnatal",
     "https://www.nhs.uk/pregnancy/labour-and-birth/your-body/", "REASSURE: lochia is normal"),

    ("NHS_SWELLING", "NHS_Swollen_Ankles.pdf",
     "Swollen ankles, feet and fingers in pregnancy", "NHS", "patient_education",
     "patient", "UK", 2024, "hypertension",
     "https://www.nhs.uk/pregnancy/common-symptoms/swollen-ankles-feet-and-fingers/",
     "REASSURE: swelling is normal"),

    ("NHS_LABOUR_SIGNS", "NHS_Signs_Labour_Begun.pdf",
     "Signs that labour has begun", "NHS", "patient_education",
     "patient", "UK", 2024, "labour",
     "https://www.nhs.uk/pregnancy/labour-and-birth/signs-of-labour/signs-that-labour-has-begun/",
     "REASSURE: Braxton Hicks are normal"),

    ("NHS_BABY_BLUES", "NHS_Feeling_Depressed_After_Birth.pdf",
     "Feeling depressed after childbirth", "NHS", "patient_education",
     "patient", "UK", 2024, "postnatal",
     "SEARCH nhs.uk - verify URL", "REASSURE: baby blues pass in 2 weeks"),
]

HEADERS = ["document_id", "filename", "title", "publisher", "document_type",
           "audience", "country", "year", "topics", "url", "notes"]


def main():
    # --- GUARD: refuse to write duplicates ---
    ids = [d[0] for d in DOCUMENTS]
    files = [d[1] for d in DOCUMENTS]
    dupe_ids = {i for i in ids if ids.count(i) > 1}
    dupe_files = {f for f in files if files.count(f) > 1}
    if dupe_ids or dupe_files:
        print("STOPPED. Fix these first:")
        for i in dupe_ids:
            print(f"   duplicate document_id: {i}")
        for f in dupe_files:
            print(f"   duplicate filename: {f}")
        return

    # --- create the folders ---
    for f in FOLDERS:
        path = os.path.join(ROOT, f)
        os.makedirs(path, exist_ok=True)
        print("created:", path)

    # --- write metadata.csv ---
    meta_path = os.path.join(ROOT, "metadata.csv")
    with open(meta_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(HEADERS)
        w.writerows(DOCUMENTS)
    print("created:", meta_path, f"({len(DOCUMENTS)} documents listed)")

    print("\nNEXT: download each PDF into raw_pdfs/ using the filename in metadata.csv")
    print("      then run check_corpus.py to see what's missing")


if __name__ == "__main__":
    main()
