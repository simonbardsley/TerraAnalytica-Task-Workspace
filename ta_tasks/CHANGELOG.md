# Changelog

## 0.8.3 — QGIS upload metadata correction

- Removed the slash from the author field to satisfy QGIS repository validation.
- Added author-field checks to package validation and regression tests.

## 0.8.2 — experimental release candidate

- Updated the homepage to the published Task Workspace product page.
- Standardised Plugin Manager, toolbar and message naming to TA Task Workspace.
- Scoped advertised compatibility to QGIS 3.44.4–4.2.x pending broader testing.
- Smoke-tested the packaged plugin with QGIS 3.44.4 (Qt 5) and 4.2.3 (Qt 6).
- Added archive validation, checksum generation and a QGIS release checklist.
- Updated security documentation for the current local-first beta.

## 0.8.1 — beta release preparation

- Adopted the same GNU GPL version 2 licence as TerraAnalytica Work Log.
- Added bundled README, full offline help and release changelog.
- Replaced the small message-box guide with a resizable, scrollable help window.
- Expanded Plugin Manager metadata with beta scope, privacy behaviour and Git fallback.

## 0.8.0

- Connected successful ToolSearch use to the active task through a minimal capability boundary.
- Stored only validated stable tool identifiers, aggregate counts and timestamps.
- Added assigned, recent and learned tool sections with explicit management controls.

## 0.7.2

- Added the shared TerraAnalytica help-button treatment and initial usage guide.

## 0.7.0

- Completed editable task fields, workspace profiles, explicit capture policy,
  workflow links and project-local privacy, learning, auto-save and recovery settings.
