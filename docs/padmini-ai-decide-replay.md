# Padmini ai_decide replay — 2026-10-28

Status: prepared and attempted; no successful ai_decide outputs.

## Scope and evidence

Read `local-audit/search_audit.sqlite3` in read-only mode. Loaded 10 results from Exa run
`99873483-702b-4183-906d-c6cf960a56b8` and 10 from Brave run
`3029dc8a-c677-4840-a010-1012a40127ec`, both for `padmini waldron ucf`.
Verified each run's saved raw-response file against its recorded SHA-256.
The experiment did not execute searches, fetch source URLs, modify SQLite, or deploy anything.

## Attempted sequence

1. Exa source-value request: seed, incident objective, all 10 titles/URLs/dates,
   and at most 1,000 characters of each excerpt. One read/reject question per rank.
   REST returned Internal Server Error. No classification was produced.
2. Minimal REST availability probe, unrelated to research data: also Internal Server Error.
3. Minimal SQL availability probe on existing warehouse: FAILED, with:

   `Endpoint ai_decide is not enabled for batch inference in this workspace.`

The loop stops on errors. Brave classification and both resolution stages were not called.
This SQL error establishes that batch inference is not enabled; the REST internal error
does not independently explain REST configuration or regional availability.

## Prepared decision definitions

Source value: read potential matching death/crime evidence, relevant updates, primary
statements, or sources resolving an identity ambiguity that currently blocks research.
Reject means skip this pass, preserving the result. Pure academic/contact/payroll material
is deferred. The seed does not establish homicide; a homicide keyword is not required.

Resolution: after each selected excerpt is added, assess nine explicitly supplied candidate
hypotheses: identity, age, city, road, agency, manner, medical cause, incident date, case number.
These hypotheses are human-authored test inputs, not facts extracted by ai_decide.
For each, request a support probability and accept/needs_resolution choice.

The final-resolution policy for this experiment is one directly read relevant primary
source or two independently originating reliable sources without material contradiction.
This is an experimental policy, not an installed production rule. Saved search excerpts
can support leads but cannot satisfy that final-resolution policy.

## Important saved evidence for later inspection

Exa rank 10: the November 4 ClickOrlando report says Padmini Waldron, 47, and Scott
Waldron, 49, were found at a DeLand home on Cape Cod Road. It connects Padmini to
UCF and attributes information to DeLand Police Department. It describes a cardiac-arrest
report as the reason for the response and explicitly says cause of death was not released.
It says the bodies were found Saturday; publication date must not become incident date.

Brave rank 7: the November 5 ClickOrlando title reports a murder-suicide classification.
Its short excerpt connects Padmini to UCF. This is a later lead from the same publisher,
not a second independent source and not a directly read police statement.

These observations are manual inspection, NOT ai_decide decisions.

## Reproduction and audit

Runner: `dev/decision_replay.py`. Execute from the repository root in an environment with
the Databricks SDK and the existing `pc` authentication profile:

```text
python dev/decision_replay.py             # local inspection only
python dev/decision_replay.py --execute   # model replay, no searches or URL fetching
python dev/decision_replay.py --probe     # minimal REST diagnostic
python dev/decision_replay.py --sql-probe # minimal SQL diagnostic
```

Saved requests, errors, and SQL status are under `local-audit/decision-replays/`:
`20261028T185909Z`, `20261028T185940Z`, and `20261028T190005Z`.
The SQL statement ID is `01f1d301-ca2c-168e-9c53-605447c3a80e`.

Follow-up catalog check confirmed that `system.ai.ai_decide` is registered and its
metadata is readable. A catalog-qualified SQL invocation also failed with the same
batch-inference enablement error (statement `01f1d305-7a67-164b-b4ae-30880ba82104`).
The function exists; execution has not succeeded on the tested warehouse. This is
not evidence that the function is absent or that the caller lacks catalog visibility.
The follow-up record is `local-audit/catalog-decide-probe.json`.

Resolve the execution-path enablement failure before retrying the live experiment.
No model quality, accuracy, probability calibration, latency, or cost conclusion can be drawn
from these failed requests. The runner remains standalone and is not wired into LangGraph.
