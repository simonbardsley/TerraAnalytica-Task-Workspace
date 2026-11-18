# TA Task Workspace — Help and Use Cases

## Purpose

Task Workspace keeps the *working context* for distinct pieces of a QGIS project.
It is useful when a project contains several analyses, deliverables, review stages
or people and the required panels, tools and layers differ between them.

## Quick start

1. Save the QGIS project. Task definitions are stored beside it.
2. Choose **New task**, enter a clear name, and save the task details.
3. On **Workspace**, create or select a profile and tick the state you intend to
   capture: panels and docks, toolbars, and/or participating TerraAnalytica Labs.
4. Choose **Capture selected state**.
5. Select another task from the toolbar or Overview tab. Choose **Restore** when
   you want to restore its captured workspace.

## Compact toolbar

- **Task list** activates a task and its best matching workspace profile.
- **Previous / Next** moves through tasks in project order.
- **Restore** restores the selected task's workspace.
- **Capture** updates its selected workspace profile using the explicit choices.
- **+ Task** creates a new piece of work.
- **Bind layer** assigns the active layer to a semantic input/output role.
- **Roles** checks whether the current task's layer roles can be resolved.
- **Task Workspace** opens the detailed manager.
- **Verify** checks local Git history and the tamper-evident audit chain.

## Manager tabs

### Overview

Edit the task name, type, status, description, notes, semantic inputs and outputs.
Use one task per meaningful outcome or stage rather than one task per mouse click.

### Workspace

A task can have multiple named profiles, such as laptop, office monitor or review
layout. Capture is explicit. Feature selections, edit sessions and temporary
scratch content are not captured.

### Tools

Assigned tools are deliberate task preferences. Recent and learned suggestions
come from successful ToolSearch use when local learning is enabled. Only stable
tool identifiers are recorded—never tool parameters, paths, layer names or output.

### Context

Context reports the task type, semantic inputs/outputs and the resolution of layer
roles. Roles describe meaning (for example `input_imagery` or `review_output`)
rather than relying only on a layer's current display name.

### Workflow

Dependencies describe which tasks precede the current task. Workflow references
can point to executable methods stored elsewhere. Task Workspace does not execute
Processing workflows itself.

### History

When Git is installed, changes are committed to a local repository beside the
project and the audit chain can be verified. No remote is configured and Git hooks
are disabled. If Git is missing, the plugin clearly reports reduced functionality.

### Settings

- **Share task context** controls broadcasting minimal context to participating TA plugins.
- **Usage learning** controls project-local tool counters and suggestions.
- **Auto-save edits** saves manager field changes after a short delay.
- **Recovery** allows rollback when workspace restoration fails.
- **Clear learning** deletes usage counters without altering task definitions.

## Good practice

- Save and back up the QGIS project before relying on captured workspaces.
- Use concise task names and record decisions in notes.
- Capture a profile again after intentionally changing the workspace.
- Verify history periodically when auditability matters.
- Keep executable scientific methods in QGIS Processing, Model Designer, TA Passage
  or AI Central; use Task Workspace to organise their surrounding context.

## Beta limitations

This release is experimental. Editable semantic-binding controls, the full
allowlisted Context Envelope, cloud synchronization and formal QGIS host test
evidence across every supported operating system remain future work. Cloud and
hybrid processing modes are feature-gated and this build makes no network calls.

## Data safety and support

Task files are human-readable and stored beside the project. Do not put secrets in
task names or notes. If a problem occurs, preserve the project and its `ta_tasks`
directory, record the QGIS/plugin versions, and report reproducible steps through
the issue tracker once the public repository is available.
