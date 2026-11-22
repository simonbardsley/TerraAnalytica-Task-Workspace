# Beta validation

Recorded 22 November 2026 on macOS.

## 0.8.4 security and Qt6 correction

The 0.8.3 repository scan reported three Bandit findings and four Qt6 enum
warnings. Secrets detection passed. Version 0.8.4 removes ambiguous `shell`
keyword arguments from layout data serialisation, preserves the saved schema,
and replaces four legacy enum fallbacks with scoped enums.

Bandit 1.8.6 under Python 3.13 reports zero issues and no analysis errors after
two line-specific review annotations for the required subprocess import and
local Git execution. Detect-secrets 1.5.0 reports zero findings in shipped files.
Tests, including synthetic secret fixtures, are excluded from the release ZIP
and its secrets scan. Security scanners now run in repository CI.

The QGIS repository must rescan the new version before its status is known.

## 0.8.2 runtime baseline

## Automated coverage

- Model, privacy and UI contract tests.
- Package validation compares archive files byte-for-byte with release source,
  checks required documentation, version and experimental status, rejects extra
  files, unsafe paths, symlinks, hidden files and unexpected file types, and
  generates a SHA-256 sidecar.
- Regression tests cover a valid ZIP, macOS metadata, source mismatch and private
  key file rejection. Package checks do not replace a full secrets scan.

## QGIS runtime smoke coverage

The packaged plugin passed scripts/qgis_smoke.py with both installed runtimes.

| Runtime | Result |
| --- | --- |
| QGIS 3.44.4 Solothurn, Python 3.13, Qt 5 | Passed |
| QGIS 4.2.3 Belém do Pará, Python 3.12, Qt 6 | Passed |

The test extracts the release ZIP to a temporary plugin folder. It uses real
QGIS/Qt APIs with a disposable QMainWindow and a minimal interface adapter.
It checks plugin startup, untitled-project state, first-save prompt dismissal
for QGS and QGZ, Unicode and space-containing paths, task persistence, capture
and restore, project reopening and menu removal on unload.

The offscreen platform reported unsupported window-size hints. The initial
runs also reported a PROJ database mismatch from the local Conda environment.
The smoke test does not exercise coordinate transformations.

## Remaining release checks

Interactive Plugin Manager installation, actual QGIS window layouts, visual
light/dark checks, edit-session protection, missing companions, no-Git operation,
corrupt-state recovery and Windows/Linux testing remain on RELEASE_CHECKLIST.md.
These checks have no recorded result for this candidate.

The QGIS repository submission and its automated security scan are pending.
