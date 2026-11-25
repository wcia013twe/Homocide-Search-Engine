# Padmini research workflow: one run through the UI

Follow one research journey. Each completed search supplies evidence for checking discovery, triage, saved audit records, follow-up planning, and progress together. Reuse saved evidence instead of repeating live searches for individual checks.

## Operate the run

1. Open http://localhost:8501 and select **Search → Padmini research run**. Choose Exa for the initial provider. The seed is `padmini waldron ucf`; it is a query, not a claim about the incident. Other search fields do not apply to this mode.
2. Click **Start Padmini run**. The existing checkpointed graph searches, saves evidence, assesses every source, proposes follow-ups, and pauses for review.
3. Read the source excerpts and assessments. Open promising sources and check whether they belong to the person/incident being researched. Keep identity matches and classification provisional where evidence is unclear.
4. Review the proposed follow-up, research gap, reason, and supporting source ranks. Enter a reason for continuing and click **Run selected follow-up**. Each selected step makes one search and, for nonempty results, one triage call.
5. Continue only when an unresolved research gap warrants it. Use **Finish research pass** with a reason, or stop at the existing three-search limit. The run keeps its original provider even if the top selector changes.
6. Use **Download research run** to retain queries, excerpts, assessments, proposals, decisions, audit IDs, and the stopping reason together.

The orchestrator must use these UI controls for the research run. It reads one completed step and chooses the next action from that evidence. It does not create a parallel CLI run, silently retry searches, or spend another provider call merely to inspect progress.

## Check together during that same pass

- [ ] Discovery: sources help identify the person, incident, or useful context; unrelated name matches are recognized.
- [ ] Evidence: every source receives a relevance assessment with an observable reason. Compare the strongest excerpt with its original source.
- [ ] Direction: follow-ups address specific missing or conflicting details and cite the source ranks that motivated them. Publication dates are not assumed to be incident dates.
- [ ] Audit: the progress table contains each completed query once, with source count, assessed count, and run ID. `Verified` means the existing audit reader checked saved response/triage hashes, result counts, and triage references; it does not verify the factual claims in a source.
- [ ] Continuity: navigating away/back preserves progress without repeating paid calls. Chosen follow-ups and stopping reasons persist with the checkpoint.
- [ ] Outcome: the exported run explains what was found, the gaps that drove proposals, and why this pass stopped. Record the next research action rather than adding unrelated edge-case tests.

The progress view checks every saved search in one local read pass. Viewing progress makes no provider/model calls.

## Scope and current blockers

- The panel uses the real local SQLite checkpoint/audit backend, isolated by browser-session identity. Keep this browser session open: a new local identity does not automatically reopen the old run. Research checkpoints are separate from workspace snapshots. The downloaded run is an evidence export, not a checkpoint restore file.
- Hosted orchestration still needs the existing shared session backend connected to this UI. This change does not deploy anything or claim cloud durability.
- This run covers discovery and source triage from search excerpts. Full-page retrieval and structured incident profile filling are not enabled in this UI.
- Live execution is blocked by the expired Databricks `pc` login. In WSL, run `/home/wcia013twe/.local/bin/databricks auth login --profile pc`, finish login, stop the current server, and restart `.venv/bin/python local-audit/start-testing.py`. The ignored local launcher loads provider keys into memory. Model endpoint access still needs a live run.
- Research-run audit files are local; a cloud SQL warehouse is not required to begin this workflow. Local success does not verify Delta/UC integration.

## Focused verification

One deterministic UI journey replaces external search/model responses while exercising real graph nodes, SQLite checkpoints/audit records, and review artifacts:

```sh
.venv/bin/python -m unittest discover -s tests -p test_research_workflow_ui.py -v
```

The journey starts discovery through the UI, reads progress, navigates away/back, chooses a proposed follow-up, finishes, and checks that two search/model calls produced two verified audit entries and saved continuation/stop decisions. Fixtures are synthetic and are not evidence about Padmini.

After a code change, run that journey first and then the existing regression suite once:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

For the live run record: date/commit, provider/model, each run ID, useful sources, unresolved gap, chosen follow-up and reason, final outcome, and blockers. Mark live execution **BLOCKED** until login is restored; mark it **COMPLETE** only after operating the workflow through the UI and inspecting its exported evidence.
