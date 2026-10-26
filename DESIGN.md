---
name: Homicide Research
description: Simple white workspace for evidence-led research.
colors:
  primary: "#16756B"
  canvas: "#FFFFFF"
  surface: "#F5F7F8"
  text: "#202C35"
  muted-text: "#586671"
  placeholder: "#65717A"
  divider: "#E3E8EB"
  selection: "#D2EBE5"
  selection-text: "#143F39"
typography:
  display:
    fontFamily: "sans-serif"
    fontSize: "2rem"
    fontWeight: 650
    letterSpacing: "-0.025em"
  headline:
    fontSize: "1.35rem"
    fontWeight: 620
  title:
    fontSize: "1.1rem"
    fontWeight: 600
  body:
    fontFamily: "sans-serif"
    lineHeight: 1.55
  label:
    lineHeight: 1.55
  metric:
    fontSize: "1.65rem"
  display-small:
    fontSize: "1.65rem"
spacing:
  content-top: "2.1rem"
  content-bottom: "3rem"
  sidebar-top: "1.5rem"
  tabs-gap: "1.4rem"
  compact-inset: "1rem"
components:
  workspace:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.text}"
  sidebar:
    backgroundColor: "{colors.surface}"
  button-primary:
    backgroundColor: "{colors.primary}"
  caption:
    textColor: "{colors.muted-text}"
---

# Design System: Homicide Research

## Overview

**Creative North Star: "Simple white research workspace"**

A simple, polished white research workspace. Legible records, clear controls, and visible source evidence guide the interface. Compact native Streamlit widgets keep the experience familiar; muted teal identifies actions and selection.

This captures the implemented presentation layer in `.streamlit/config.toml` and `research_app/theme.py`, with composition from `app.py`, `research_app/search.py`, and `research_app/datasets.py`. It is a visual contract, not a claim that discovery, extraction, hosted durable storage, or AI analysis is connected.

**Key Characteristics:**
- White content and a cool pale sidebar
- Charcoal text with muted teal actions
- Compact tables and side-by-side evidence review
- Native Streamlit controls and visible keyboard focus

## Colors

The palette combines muted teal with cool neutrals. The frontmatter is authoritative for project-owned values.

**Primary:** Muted teal marks primary actions, selection, the caret, and explicit keyboard focus. Pale teal and dark teal form the text-selection pair.

**Neutral:** White is the content canvas; cool pale gray supports the sidebar and secondary native surfaces. Charcoal carries main text. Muted slate distinguishes captions, while a separate placeholder gray keeps hints readable. The subtle divider separates sidebar and content.

Feedback colors remain native Streamlit success, information, warning, and error treatments. Always accompany state with plain-language text; no custom status palette is established.

## Typography

Use Streamlit's configured sans-serif family without a separately loaded display face. Display is the page heading, headline the section heading, and title the smaller subsection heading. Paragraphs and field labels use the documented line-height. Metrics and dataframes use tabular numerals for comparison.

Body size, widget fonts, heading line-heights, and font fallback resolution remain framework defaults. Do not infer an additional type scale from them. The compact display size applies at the small-screen breakpoint in the sidecar.

## Layout

Use a wide page with a content maximum of 1480px. The documented top and bottom insets leave room around dense work; the sidebar has its own smaller top inset. Main navigation stays in the pale sidebar, with page title and short context at the top of content.

Dataset work uses seven native tabs: Overview, Incidents, Sources, Variables, Runs, Evaluation, and Settings. Search uses Discovery and Research. Tabs retain native overflow and selection behavior, with zero horizontal tab padding and the documented gap.

Filters commonly use a 2:1:1 column ratio. Tables stretch to their container and hide redundant row indexes. The incident review pattern places Coding & review and Supporting evidence in equal columns with Streamlit's large gap; the table and record selector precede this region. Keep source identity and evidence text next to editable classifications.

At viewport widths of 640px or less, content top and side insets use the compact inset, the page heading uses display-small, and the tab gap uses the compact inset. Streamlit owns sidebar collapse, column stacking, and table overflow; do not claim an additional custom breakpoint or mobile interaction. Verify these native behaviors after framework upgrades.

## Elevation & Depth

The application adds no shadows or animated elevation. White space, pale surfaces, dividers, and native bordered containers establish grouping. Framework menus and popovers retain their native treatment; their shadow values are not project tokens.

## Shapes

Use native Streamlit buttons, forms, expanders, selectors, and bordered containers. The sidebar edge is a one-pixel solid divider. No custom radius scale is defined; native widget rounding, padding, and control heights remain framework-owned.

## Components

**Buttons:** Use the native primary variant for consequential local actions such as Collect sources and Save review. Use ordinary buttons for secondary actions and native link/download buttons for source access and exports. Preserve native hover, active, and disabled behavior. Disable unavailable actions and explain what is missing nearby.

**Inputs:** Keep visible labels and descriptive placeholders. Use text areas for reasons and longer definitions, selectors for bounded states, and multiselects for supporting sources. Group edits in native forms with explicit submit actions. Error and success feedback is textual and adjacent to the workflow.

**Keyboard focus:** Buttons, links, inputs, and text areas receive a solid primary-color outline of 2px with a 3px offset on focus-visible. Native composite widgets retain their framework focus behavior. Never suppress it when extending the UI.

**Navigation:** A native radio group supplies the five sidebar destinations. Its label is visually collapsed while its accessible name remains Workspace navigation. Preserve native selected and keyboard states. Use native tabs within a page.

**Tables and source containers:** Tables favor compact, comparable rows. Search results use bordered containers with a selection checkbox, publisher/date caption, excerpt, and expandable evidence. Reserve expanders for secondary detail such as review history, source previews, creation forms, and snapshots.

**Evidence review:** Keep coding fields and supporting evidence paired. Show uncertainty explicitly as Reported, Not Reported, or Unclear; keep incident review state distinct. Save feedback must reflect the actual result. Source previews expose title, publisher/date, source text, source identifier, processing state, and a source link when available.

Sidecar component snippets are isolated previews of these patterns, not replacements for native Streamlit widgets. Only project-owned tokens and overrides are normative; native dimensions and hover styling are intentionally not frozen here. No shipping raster assets are used.

## Do's and Don'ts

- Do retain white content, restrained teal accents, and readable neutral text.
- Do keep field labels, evidence status, source references, and save feedback visible.
- Do preserve native keyboard behavior, focus indicators, and responsive controls.
- Do label fictional records and explain unavailable integrations beside their controls.
- Don't introduce decorative gradients, illustrations, or elaborate visual treatments into this simple workspace.
- Don't communicate verification or uncertainty through color alone.
- Don't imply that an unavailable service has run or that sample data is real.
- Don't invent custom widget geometry when the native Streamlit control already serves the task.
