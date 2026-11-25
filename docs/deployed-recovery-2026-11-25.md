# Deployed app recovery — 2026-11-25

App: `homocide-ai-research` at https://homocide-ai-research-7474648183111292.aws.databricksapps.com.

## Observed blocker

The app compute and active deployment `01f1e9071a571b299f85e89ee9b00749` were healthy, but Search displayed unavailable cases and investigations. Runtime logs repeatedly reported `The endpoint has been disabled. Enable it using the API and retry.`

The attached Lakebase endpoint `projects/homicide-research/branches/production/endpoints/primary` had `status.disabled=true`. This explicit disabled state differs from normal idle suspension; a connection cannot enable it. The API reported its prior update time as 2026-11-25 13:29:53 UTC. Who disabled it and why were not established.

## Repair

Restored the expired CLI OAuth login for profile `pc`. No new provider secret was needed. Updated only `spec.disabled` to `false` on the existing Lakebase endpoint at 19:52:08 UTC. Used `databricks postgres update-endpoint` with update mask `spec.disabled` and JSON body `{"spec":{"disabled":false}}`.

The endpoint subsequently reported `ACTIVE`, with its existing compute limits and suspension settings preserved. No app redeployment, database migration, or research-data modification was needed. The deployed source was downloaded to the ignored local directory `local-audit/deployed-01f1e907` for diagnosis; it is newer than this checkout and was not replaced with local source.

## Evidence

- A read-only SQL connection succeeded; the app service principal has SELECT on the case, case-link, publication, investigation, and command tables.
- Search recovered its case selector and enabled submission, and displayed saved Padmini investigations with their search/source counts.
- Cases loaded four cases and five linked investigations.
- Dataset loaded its filters and one matching record without an unavailable warning.
- Database status counts: three investigations awaiting review and seven failed. Recorded failures date from November 16–18 and contain generic historical failure messages; their underlying causes were not established in this repair. They were not replayed or relabeled.
- The configured model endpoint reported `READY`.

This validates recovery of shared storage and saved research access. It does not prove a new search/model/research run completes. Continue the Padmini workflow through the deployed UI for that validation, reusing its saved evidence where possible.

## Case organization repair

At the researcher's request, merged the three duplicate `Padmini Devi Florida` cases into the oldest case, `9815349f-a1aa-4866-9904-111390f97f70`, titled `Padmini Devi (Coopamah) Waldron — DeLand, Florida`. It now contains all four Padmini investigations, including the two failed attempts. The separate Ajike Owens case retains its investigation and now has a concise title.

The operation was rehearsed with a transaction rollback before being committed. Guards required the inspected case revisions, empty reviewed fields, no publications/identifiers requiring reconciliation, and no queued/running commands. A full backup was saved in the ignored file `local-audit/case-merge-backup-fabbb95b-1a2e-4cd3-a2ce-e9bea6a637dd.json` before any changes. A database merge event preserves original case metadata and history; moved history entries retain their original case/revision attribution. No investigation, command, ownership, or evidence snapshot changed. Final database assertions confirmed two cases and all five investigation links.

Future Padmini searches should be launched from the existing case or target that case in Search. This repair reorganized existing records; it did not introduce automatic identity-based merging of future research.
