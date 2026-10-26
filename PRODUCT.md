# Homicide Research Platform

<!-- impeccable:product-schema 1 -->

## Platform
web

## Stack
Delegated by user: use Streamlit if capable, otherwise React. This UI-first scaffold uses Streamlit on Databricks Apps; ordinary Python modules keep the data contract portable.

## Users
Social science researchers discovering, coding, verifying, and analyzing homicide incidents using news, public records, and uploaded research materials.

## Product Purpose
Support discovery → evidence collection → verification → structured datasets → analysis in one persistent research workspace.

## Operating Context
Search contains Discovery and Research modes. Datasets contains Overview, Incidents, Sources, Variables, Runs, Evaluation, and Settings. Library holds shared source material. Projects groups datasets and supports analysis. Usage shows work, coverage, and costs.

## Capabilities and Constraints
This pass implements the UI and its data contract first. Live web discovery, document parsing, model extraction, and natural-language analysis are future adapters. Preview fixtures must be visibly fictional. Research corrections and approvals must retain evidence and audit history. Databricks workspace authentication supplies deployed identity. Persistent hosted storage beyond app lifecycle is an explicit next integration, with snapshot export/import in the scaffold.

## Brand Commitments
User explicitly requested a polished simple white interface with visual clarity and functional design; avoid an elaborate visual design process. Light research workspace, compact tables, muted teal actions, side-by-side evidence review.

## Evidence on Hand
The user's researcher-experience brief and prior ingestion architecture discussion are the source requirements. No actual homicide dataset or source corpus has been supplied for this build. All example incidents and source excerpts are synthetic.

## Product Principles
- Evidence first: every substantive claim traces to source material.
- Spreadsheet familiarity and direct manipulation.
- Researcher control over correction and verification.
- Preserve work and expose persistence limitations honestly.
- Progressive complexity; basic discovery and review stay approachable.

## Open Decisions
Live search provider, extraction service, durable hosted state, collaboration roles, and analytical query execution remain unconnected in this scaffold.
