# Read100

Private source-of-truth repository baseline for **Read100 v1.5 Evidence Loop**.

## Baseline policy
- GitHub is intended to become the source of truth for source/config templates.
- This baseline performs **no AWS, GENCOW, Staging, or Production mutation**.
- Existing age-adaptive UI/content and Evidence Loop source are preserved from the validated reference package.
- Pilot invite codes, Owner/Observer PINs, secrets, runtime DBs, and evidence exports must never be committed.
- Human Acceptance remains a required release gate.

## Local configuration
Copy `config.example.json` to `config.json` and provision real credentials outside Git.

## Initial source provenance
See `BASELINE_PROVENANCE.json`.
