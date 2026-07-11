# Data — Sources, Licensing, and Usage

This directory holds the pre-work data described in [`PROJECT.md`](../PROJECT.md#hackathon-build-plan) (Pre-work section). Per that plan, pre-work is limited to data prep and scaffolding — no application logic.

## What's real vs. what's synthetic

### Real, public reference data (safe to use as-is)

These are grounded in actual public datasets. Where we didn't bulk-download the full dataset, the file documents how to pull it live during the hackathon.

| File | Source | Access |
|---|---|---|
| [`reference/icd10_top30_home_health.json`](reference/icd10_top30_home_health.json) | CMS/CDC FY2026 ICD-10-CM code set | Free, no license. Full code set: [CDC ICD-10-CM files](https://www.cdc.gov/nchs/icd/icd-10-cm/files.html). This file is a curated subset of the ~70,000 codes — the top 30 diagnoses most common in home health referrals, per CMS coding guides. |

**NPI validation** — not bulk-downloaded (9M+ providers). Use the [NPPES NPI Registry API](https://npiregistry.cms.hhs.gov/api-page) live: free, public, no auth, no rate-limit key required. This is what the Validation Agent (PROJECT.md Layer 5) should call to verify a physician's NPI via Luhn check + registry lookup.

**RxNorm medication data** — not bulk-downloaded. Use the [RxNorm API](https://lhncbc.nlm.nih.gov/RxNav/APIs/RxNormAPIs.html) (RxNav) live: free, no UMLS license needed for API access (only needed for bulk `.RRF` file downloads). Use this for medication name normalization and dosage-range sanity checks in the Correction Agent.

**SNOMED CT → ICD-10-CM mapping** — **not included, and flagged as a friction point.** The real mapping requires a free [UMLS Terminology Services (UTS) account](https://www.nlm.nih.gov/research/umls/mapping_projects/snomedct_to_icd10cm.html) with a signed license agreement — this is not instant-access on hackathon morning unless someone on the team already has an account from prior work. If nobody has a UTS account going in, treat SNOMED mapping as out of scope for the demo and rely on the hand-built `diagnosis_service_certification_mapping.json` instead (which only needs ICD-10, not SNOMED).

**CMS Medicare home health coverage rules** — real conditions of payment (homebound status required, face-to-face encounter required, no prior authorization) are encoded into the `Medicare Part A` entry in `reference/payer_coverage_rules.json`. Source: [CMS ICD-10/coverage guidance](https://www.cms.gov/medicare/coding-billing/icd-10-codes).

### Synthetic data (generated for this project, not sourced from any real dataset)

Per [`must-have.md`](../must-have.md) Part 1 Rule #1 ("Fake Data Only — No Real PHI Ever Touches the System"), this data **must** be synthetic even though nothing prevented us from using real public examples — patient, caregiver, and payer-contract data is exactly the category that rule exists to keep out of the system. Every record below carries `is_synthetic: true`.

| File | Contents |
|---|---|
| [`reference/diagnosis_service_certification_mapping.json`](reference/diagnosis_service_certification_mapping.json) | Diagnosis → required service type → required certification mapping for the 30 diagnoses above. Hand-authored clinical logic (uses real ICD-10 codes; the mapping decisions are authored for this project). |
| [`reference/payer_coverage_rules.json`](reference/payer_coverage_rules.json) | 5 payers, 8 plans. Medicare Part A rules are real; Medicare Advantage/commercial plan names and specific rules (visit limits, prior-auth flags) are simulated but structured realistically, per `PROJECT.md`'s "simulated but realistic (4-5 payers, 2-3 plans each)" spec. |
| [`synthetic/caregiver_roster.json`](synthetic/caregiver_roster.json) | 25 fictional caregivers (RN/LPN/PT/OT/Speech/HHA) with certifications, zip coverage, availability, languages, patient load. Matches `PROJECT.md`'s "20-30 caregivers" spec. |
| [`synthetic/sample_referrals.json`](synthetic/sample_referrals.json) | 4 fictional referral scenarios, varying quality/completeness, matching `PROJECT.md`'s "3-4 sample referral PDFs" spec: a clean complete referral, a referral missing F2F documentation, a messy scanned fax with OCR ambiguity (tests the Validation/Correction Agent), and a minimal-info family phone call. Represents the *structured JSON output* the 7-layer document pipeline would produce, not rendered PDF/fax images — useful for building and testing the Eligibility Agent and dashboard before real fax samples exist. |

## Next steps (not done here — flagging for whoever picks this up)

- If actual PDF/TIFF fax mockups are needed for a live OCR pipeline demo (Layer 1-4), someone needs to render `synthetic/sample_referrals.json` into fax-realistic PDF images (varying rotation/noise for the messy scenario). This file only covers the *data*, not document rendering.
- Loading `reference/` + `synthetic/` JSON into PostgreSQL tables and Neo4j nodes/relationships (per `PROJECT.md`'s Database Architecture) is separate scaffolding work, owned by whoever takes Phase 1 / Person 3 in the build plan.
