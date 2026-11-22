# TerraAnalytica Task Workspace

Task Workspace is an experimental QGIS plugin for organising a saved project into
named tasks and restoring the QGIS workspace associated with each task.

It remembers working context—task details, semantic layer roles, assigned tools,
dependencies and explicit workspace profiles—while QGIS Processing, Model
Designer, TA Passage or AI Central remain responsible for executing algorithms.

## Quick start

1. Save the QGIS project.
2. Install and enable **TA Task Workspace**.
3. Create a task and enter its purpose, status, notes, inputs and outputs.
4. On **Workspace**, select exactly which panels, toolbars and participating
   TerraAnalytica context to capture.
5. Capture the profile, then switch tasks and restore it when required.

See the bundled [user guide](ta_tasks/HELP.md), [security notes](ta_tasks/SECURITY.md)
and [changelog](ta_tasks/CHANGELOG.md) for details.

## Privacy and storage

Task files are stored in a `ta_tasks` directory beside the saved QGIS project.
When Git is available, Task Workspace creates a local repository with hooks
disabled. It configures no remote and never pushes.

Optional ToolSearch learning stores only stable task/tool identifiers, aggregate
counts and timestamps. It does not store tool parameters, paths, layer names,
coordinates, attributes or outputs. This beta makes no cloud connection.

## Install a beta ZIP

In QGIS, open **Plugins → Manage and Install Plugins → Install from ZIP**, select
the release archive and enable **TA Task Workspace**. Experimental plugins must
be enabled in Plugin Manager settings for repository-distributed beta versions.

## Development

The installable QGIS package is in `ta_tasks/`. Its dependency-free model tests
can be run outside QGIS:

```sh
PYTHONPATH=. python3 -m unittest discover -s ta_tasks/tests -v
python3 scripts/build_plugin.py
python3 scripts/validate_package.py dist/ta_tasks-0.8.3.zip
```

This beta targets QGIS 3.44.4–4.2.x. Runtime smoke tests passed on macOS with
QGIS 3.44.4 (Qt 5) and 4.2.3 (Qt 6). QGIS-hosted UI and restore tests still require
supported QGIS installations. Record their results using the bundled
[release checklist](ta_tasks/RELEASE_CHECKLIST.md).

Run `scripts/qgis_smoke.py dist/ta_tasks-0.8.3.zip` with the Python interpreter
and library environment supplied by your QGIS installation. The smoke test
extracts the ZIP into a temporary directory and exercises real QGIS/Qt APIs in
a disposable Qt host. See [validation results](ta_tasks/RELEASE_VALIDATION.md)
for its scope and remaining interactive checks.

## Licence

Copyright © TerraAnalytica / NZSpatial Limited contributors.

Distributed under the GNU General Public License, version 2 (`GPL-2.0-only`).
See [LICENSE](LICENSE).
