# Beta release checks

## Current candidate

Version 0.8.2 targets QGIS 3.44.4–4.2.x and remains experimental.
See RELEASE_VALIDATION.md for recorded automated and runtime results.
Record date, operating system, QGIS/Python/Qt versions, archive SHA-256 and
pass/fail evidence for each check. An unchecked item has no recorded result.

## Automated checks

- [ ] Run `PYTHONPATH=. python3 -m unittest discover -s ta_tasks/tests -v`.
- [ ] Build with `python3 scripts/build_plugin.py`.
- [ ] Run `python3 scripts/validate_package.py dist/ta_tasks-0.8.2.zip`.
- [ ] Review source and archive for secrets and private project data.

## QGIS clean-profile checks

Use a new disposable QGIS profile and a temporary project with synthetic layers.
Install the exact release ZIP through Plugin Manager. Repeat platform-sensitive
checks on Windows and Linux before claiming those platforms are validated.

- [ ] Enable, disable and re-enable the plugin. Check menu, toolbar and dock cleanup.
- [ ] Open the dock before saving a project. Save as QGZ, then confirm the save
      prompt disappears and task controls become available immediately.
- [ ] Repeat with QGS and a path containing spaces and non-ASCII characters.
- [ ] Edit name, description, type, status, notes, inputs and outputs. Reopen the
      project and verify persistence and isolation between two projects.
- [ ] Create, rename, select and delete profiles. Capture panels and toolbars
      separately. Change the layout and verify restore honours capture choices.
- [ ] Switch tasks and verify the intended profile is restored. Verify active
      edits, feature selections and temporary scratch content remain protected.
- [ ] Test missing layers, missing companions and an unavailable participant.
- [ ] Add workflow references and dependencies. Verify cycle rejection.
- [ ] Disable auto-save, edit a task and verify explicit saving. Enable auto-save,
      edit again and verify the change survives reopening.
- [ ] Disable tool learning and context sharing and verify the settings persist.
      Record a tool ID, clear learning and inspect the project-local files.
- [ ] Verify local history with Git present. Test a session without Git available.
- [ ] On a disposable copy, test corrupt-state recovery and a newer schema.
      Confirm recovery respects its setting and newer schemas remain read-only.
- [ ] Check text, checkboxes, focus, banner and help in light and dark themes.
- [ ] Open offline help and check the compact toolbar instructions.
- [ ] Review QGIS logs for exceptions after capture, restore and project switching.

## Publication

- [ ] Confirm public source, GPL-2.0-only licence, help@nzspatial.com and all links.
- [ ] Tag the exact tested source and publish the matching ZIP and checksum.
- [ ] Upload the experimental version to plugins.qgis.org.
- [ ] Review security scan results and address findings before approval.
- [ ] Install the approved version through QGIS Plugin Manager and repeat the
      first-save and capture/restore checks.

Cloud service functionality remains feature-gated. See SECURITY.md for the
separate cloud-service security and SOC 2 readiness scope.
