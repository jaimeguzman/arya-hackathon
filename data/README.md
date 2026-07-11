# Data — Sources, Licensing, and Usage

## ✅ Status: DONE — safe to build against right now, in parallel

All seed/reference data for both entry channels (voice call + fax) is finished, validated, and committed. **Nobody needs to wait on anyone else to start building against this data** — grab your files below and go. This is pre-work per [`PROJECT.md`](../PROJECT.md#hackathon-build-plan) (data prep and scaffolding, no application logic), matching the 4-developer phase split from that build plan.

| Role (per `PROJECT.md` build plan) | Grab these files | You can start building |
|---|---|---|
| **Person 1 — Voice Agent** | [`reference/payer_coverage_rules.json`](reference/payer_coverage_rules.json), [`reference/agency_configuration.json`](reference/agency_configuration.json), [`synthetic/referral_source_directory.json`](synthetic/referral_source_directory.json), [`synthetic/sample_referrals.json`](synthetic/sample_referrals.json) | Provider/Family/Outbound conversation flows, caller-personalization script ("Hi Sarah, calling from Mount Sinai?"), test call scripts against the 4 sample scenarios |
| **Person 2 — Document Pipeline** | [`synthetic/referral_faxes/`](synthetic/referral_faxes/) (3 real PDFs — one is a genuinely degraded scan, no text layer), [`synthetic/sample_referrals.json`](synthetic/sample_referrals.json) (ground truth to check extraction accuracy against), [`reference/icd10_top30_home_health.json`](reference/icd10_top30_home_health.json) | OCR/vision extraction, Validation/Correction/Cross-Reference agents, confidence scoring — run the pipeline on real PDFs and diff the output against the ground-truth JSON |
| **Person 3 — Eligibility Agent + DB** | Everything in [`reference/`](reference/) and [`synthetic/`](synthetic/) | PostgreSQL migrations + Neo4j Cypher seed scripts that load this data, `check_eligibility()` implementation — this is the only role that needs *all* of it |
| **Person 4 — Orchestrator + Follow-up** | [`synthetic/referral_source_directory.json`](synthetic/referral_source_directory.json), [`synthetic/sample_referrals.json`](synthetic/sample_referrals.json) | LangGraph state machine routing logic, retry/escalation scheduling — use the 4 sample scenarios to test routing decisions end-to-end before real calls/faxes exist |

Everyone can develop against the raw files directly today; swapping to real DB-backed queries once Person 3's loaders exist is a drop-in change, not a rewrite — the JSON *is* the schema.

---

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
| [`reference/agency_configuration.json`](reference/agency_configuration.json) | The agency's own service-area zip list, operating hours, phone/fax, service types offered, and accepted payers — the "do *we* serve this zip" fact the Eligibility Agent checks, independent of any single caregiver's assignment (previously only existed implicitly as the union of caregiver zips). |
| [`synthetic/caregiver_roster.json`](synthetic/caregiver_roster.json) | 25 fictional caregivers (RN/LPN/PT/OT/Speech/HHA) with certifications, zip coverage, availability, languages, patient load. Matches `PROJECT.md`'s "20-30 caregivers" spec. |
| [`synthetic/sample_referrals.json`](synthetic/sample_referrals.json) | 4 fictional referral scenarios, varying quality/completeness: a clean complete referral, a referral missing F2F documentation, a messy scanned fax with OCR ambiguity (tests the Validation/Correction Agent), and a minimal-info family phone call. This is the *structured JSON* — the extracted ground truth each scenario should produce — for testing the Eligibility Agent and dashboard directly. |
| [`synthetic/referral_faxes/`](synthetic/referral_faxes/) | The actual rendered fax **PDF documents** for 3 of the 4 scenarios above (REF-1001 clean, REF-1002 missing F2F, REF-1003 messy/degraded scan), for exercising the real Document Pipeline (OCR/vision extraction) end-to-end, not just the pre-extracted JSON. REF-1004 has no fax — it's phone-only (family call), by design. REF-1003 is a genuine image-only PDF (rasterized, rotated, JPEG-degraded, no embedded text layer) so it actually exercises the vision-OCR path (Path C) instead of being trivially text-extractable. |
| [`synthetic/referral_source_directory.json`](synthetic/referral_source_directory.json) | 6 fictional referral sources (hospitals + 1 SNF) with contact info, referral history, and acceptance rate — powers Feature 5 (Caller Personalization), e.g. "Hi Sarah, calling from Mount Sinai?" Facility names are real NYC hospitals used only as realistic labels; all contacts/history are fictional. |

## Status: complete for the hackathon's two entry channels

Both `WORKFLOW.md` paths (voice call and fax) now have everything the Eligibility Agent, Voice Agent, and Document Pipeline need to run against: diagnosis/service/certification grounding, payer rules, agency service area, caregiver roster, referral source history, and — for the fax path — actual PDF documents to extract from, not just pre-extracted JSON.

**Still separate, deliberately not seed data**: loading `reference/` + `synthetic/` JSON into PostgreSQL tables and Neo4j nodes/relationships (per `PROJECT.md`'s Database Architecture) is scaffolding work, owned by whoever takes Phase 1 / Person 3 in the build plan — this directory provides the data, not the loaders.
