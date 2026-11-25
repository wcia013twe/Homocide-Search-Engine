# Investigation workspace consolidation

Search now only submits research requests. Submission opens the linked case's
Investigations tab with the new investigation selected. An investigation selector
replaces the repeated cards and second detail view.

The investigation presents worker status and last update, any required decision,
provisional findings and gaps, saved search/decision history, and source text.
Full identifiers and timing details remain available in collapsed details.
AI coding finishes within each investigation. Its field labels describe evidence
as Supported, Conflicting, or Missing or unclear; these are not human approvals.
The case Review tab aggregates all investigation findings and remains the only
place for researcher field decisions and Dataset approval. No aggregate AI pass
or new database schema is introduced.

New runs finish even when some fields are unresolved. The `final_coding` node
name is retained so existing checkpoints remain resumable. An owner can select
Complete investigation for an old coding pause; the existing finalize command
now accepts only `search_run_id` and `action: case_review`. It checks checkpoint
ownership and search identity before resuming, preserves original claims and
sources, and makes no new search/model call. This handoff does not approve a case.
The HTTP finalize schema and CLI help reflect this compatibility-only operation.

Queued/running investigations refresh every two seconds. Polling stops when the
selected investigation needs input or finishes; a submitted decision reruns the
page and resumes polling. Refresh investigation reloads changes from another
session. Existing command ownership and revision checks remain in force.

## Source baseline

The checkout contained an older scaffold without the deployed case workflow.
The application modules, SQL migrations, and deployed tests were recovered from
the saved deployment source before applying the UI changes. Prior local versions
of replaced files were preserved in the ignored directory
`local-audit/investigation-consolidation-before`.

The affected baseline files were compared with active deployment
`01f1e91dcebb17d5a990f4442aff70fe` and matched. The separate patch at
`hosting/investigation-workspace-deployed.patch` isolates this feature from the
baseline recovery. No database migration was executed, no research was submitted,
and this change has not been deployed.

## Validation

Run the focused UI checks from WSL:

```sh
PYTHONPATH=tests .venv/bin/python -m unittest test_investigation_workspace test_review_controls test_investigation_progress test_research_ui test_collaboration_ui.CollaborationUITests.test_case_review_selects_scoped_claims test_collaboration_ui.CollaborationUITests.test_closed_filter_uses_current_approval_and_keeps_cases_openable test_collaboration_ui.CollaborationUITests.test_new_pages_explain_missing_services -v
```

The new tests cover submission selecting the exact investigation, selection
stability, decision draft preservation, command submission, legacy coding handoff,
owner-only controls, and saved activity after failure. Existing checks
cover case review, navigation, submission validation, and duplicate command controls.
All 21 focused checks passed. The decision-draft check was rerun after scoping
drafts to each search round and passed, including clearing the previous round's
reason. The isolated patch passes `git apply --check` against the saved baseline.

Desktop (1440px) and mobile (390px) synthetic views were rendered in headless
Chromium and inspected. Neither had horizontal page overflow. The design detector
reported no findings, and application modules compile.

After the coding handoff change and the integration task's test-baseline cleanup,
the full suite completed successfully: 191 tests, 26 skipped. The graph/session
and evidence-status checks passed (16 tests), as did the decision controls,
investigation workspace, grouping, and coding validation checks (25 tests).
The legacy-checkpoint test saves an actual old interrupt in SQLite and reopens
it with the new graph; wrong-owner, stale-search, and extra-field payloads fail
without changing the checkpoint. Completion preserves claims and sources without
calling search or triage. Database integration tests require a disposable
Postgres DSN and were not exercised against production. Deployment is handled
separately by the integration task.
