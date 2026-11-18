# TA Task Workspace

TA Task Workspace is an experimental QGIS plugin for dividing a saved project
into named pieces of work and restoring the QGIS workspace associated with each
task. It complements executable Processing workflows: Task Workspace remembers
the working context; QGIS Processing, Model Designer, TA Passage or AI Central
remain responsible for running algorithms.

## Core workflow

1. Save the QGIS project.
2. Create a task for a meaningful piece of work.
3. Add its description, status, notes, semantic inputs and outputs.
4. Select exactly which panels, toolbars and participating TA context to capture.
5. Capture one or more named workspace profiles.
6. Switch tasks and restore the best matching profile when needed.

The manager also supports task dependencies, workflow references, semantic layer
roles, assigned/recent/suggested tools, local history and audit verification.

## Storage and privacy

Task data is stored in a `ta_tasks` directory beside the saved QGIS project.
When Git is available, the plugin creates a local repository with hooks disabled;
it configures no remote and never pushes. Without Git, task management continues
but history and audit verification are unavailable for that session.

Tool learning is optional and project-local. It stores only stable task/tool IDs,
aggregate counts and UTC timestamps. It does not store parameters, paths, layer
names, feature attributes, coordinates or outputs. The data can be cleared from
Settings.

## Compatibility and beta status

- QGIS 3.22 through QGIS 4.x are declared by the package.
- Qt imports use the QGIS compatibility layer for Qt 5 and Qt 6.
- This version is an experimental beta and should be tested on copies or backed-up
  projects before production use.
- The plugin is local-first and does not connect to a cloud service.

See `HELP.md` for the complete user guide, `SECURITY.md` for security boundaries,
and `CHANGELOG.md` for release history.

## Licence

Copyright © TerraAnalytica / NZSpatial Limited contributors.

TA Task Workspace is distributed under the GNU General Public License, version 2
(`GPL-2.0-only`). See `LICENSE` for the complete terms.
