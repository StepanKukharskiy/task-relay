---
name: excel-to-powerpoint
description: Update an existing recurring PowerPoint report from a spreadsheet while preserving its template, mapping period-specific values and native charts, and reporting uncertain fields.
---

Update a fixed report from new-period source data. Separate reusable mappings, formatting and validation rules from this month's workbook, deck and execution receipt.

Use the supplied template and mapping when present. Otherwise inspect the workbook and presentation to build a bounded map of source cells to text, table cells, chart series/categories and reporting-period labels. Confirm ambiguous units or definitions before using them. Do not infer a cause from numeric change.

Work on a copy. Preserve slide count, dimensions, masters, layouts, geometry, static content and typography. Update all mapped values, chart categories and series, native chart workbooks/caches and current-period labels. Historical months can remain in a trend.

Preflight numeric types, required fields, currency, reconciliation rules and unique output targets. Missing required data or an ambiguous/missing target blocks export. Report optional unmapped commentary as requiring human input. Preserve originals and refuse an existing output path.

Use this Skill directly in Codex; Relay is optional. For local discovery, place this folder at `.agents/skills/excel-to-powerpoint` in the working project and ask Codex to use `$excel-to-powerpoint` with the selected files. A compatible Agent Skills host can read the same instructions, but execution support depends on its document tools and has not been tested here.

For the supplied reference adapter, read [references/codex-runtime.md](references/codex-runtime.md). Codex's bundled spreadsheet/presentation dependencies are required. Discover the current host paths and resolve them locally; no Relay API or package is involved. If those tools are unavailable, explain the missing dependency rather than implying that installing Relay fixes it.

A mapping contains the sheet, currency and reporting-period cell, numeric targets, period targets, complete chart categories/series and optional commentary. Table indices are zero-based. Stable text-shape names and slide ownership identify targets. Workbook values are read through the host calculation engine; unsupported source formulas must not be presented as verified.

The reference adapter supports explicitly mapped GBP or USD, Arial, six slides at 1280 × 720 pixels, and one series per chart. Its explicit `chart_data_policy: replace-literal-snapshots` rebuilds local embedded chart snapshots using the supplied workbook. The packaging helper repairs missing embeddings after export and refuses any chart formula outside that snapshot contract. These charts remain native and editable; they are snapshots without live links to the monthly workbook. For another template, adapt and retest these assumptions before running the helper.

Independently reopen the exported PPTX. Compare displayed values to source cells with their intended rounding, validate complete chart categories/series and embedded data, and compare template layout/style signatures. Render every slide for fit and overflow. Reopen in an available native application and state which one was used. A structural reopen or preview does not prove PowerPoint application compatibility.

Keep a receipt of inputs, their hashes, mapped targets, checks actually run and unresolved exceptions. State whether the inputs are synthetic or public transaction data. Do not claim customer validation, Relay execution, cross-host compatibility or Skill telemetry without the corresponding evidence. This version allows complete literal snapshot ranges to grow when the mapped trend gains an observed month.

The Skill and reference adapter contain no execution telemetry or publisher reporting endpoint. Normal model/tool use still follows the chosen host and provider.
