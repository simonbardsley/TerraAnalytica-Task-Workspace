"""Dockable Task Manager UI (M6 foundation and first-run experience)."""
from __future__ import annotations

from qgis.PyQt.QtCore import QEvent, QTimer, Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
    QDockWidget,
)

from .ta_style import stylesheet
from .task_help import TaskWorkspaceHelpDialog
from .compat import MessageLevel
from .twm.display import classify_display
from .twm.schemas import KNOWN_TASK_TYPES, TaskStatus
from .twm.service import CaptureOptions


def _qt_enum(group: str, name: str):
    """Resolve scoped Qt6 and unscoped Qt5 enum members."""
    scoped = getattr(Qt, group, None)
    return getattr(scoped, name) if scoped is not None else getattr(Qt, name)


LEFT_DOCK = _qt_enum("DockWidgetArea", "LeftDockWidgetArea")
RIGHT_DOCK = _qt_enum("DockWidgetArea", "RightDockWidgetArea")
SINGLE_SELECTION = QAbstractItemView.SelectionMode.SingleSelection
USER_ROLE = _qt_enum("ItemDataRole", "UserRole")
ITEM_IS_USER_CHECKABLE = _qt_enum("ItemFlag", "ItemIsUserCheckable")
CHECKED = _qt_enum("CheckState", "Checked")
UNCHECKED = _qt_enum("CheckState", "Unchecked")
EVENT_TYPE = getattr(QEvent, "Type", QEvent)
PALETTE_EVENTS = tuple(
    event for event in (
        getattr(EVENT_TYPE, "PaletteChange", None),
        getattr(EVENT_TYPE, "ApplicationPaletteChange", None),
    ) if event is not None
)


class TaskManagerDock(QDockWidget):
    """Useful management surface even before a QGIS project has been saved."""

    def __init__(self, plugin, parent=None):
        super().__init__("TA Task Workspace", parent)
        self.plugin = plugin
        self._loading = False
        self._help_dialog = None
        self.setObjectName("TATaskManagerDock")
        self.setAllowedAreas(LEFT_DOCK | RIGHT_DOCK)
        self.setWindowIcon(plugin._plugin_icon())

        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)

        header = QFrame()
        header.setObjectName("taTasksHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 10, 12, 10)
        header_layout.setSpacing(8)
        title_box = QWidget()
        title_box.setObjectName("taTasksTitleBox")
        title_layout = QVBoxLayout(title_box)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(1)
        self.brand = QLabel("TERRAANALYTICA")
        self.brand.setObjectName("taTasksWordmark")
        self.heading = QLabel("Task Workspace")
        self.heading.setObjectName("taTasksTitle")
        self.subtitle = QLabel("Organise work. Restore your workspace.")
        self.subtitle.setObjectName("taTasksSubtitle")
        title_layout.addWidget(self.brand)
        title_layout.addWidget(self.heading)
        title_layout.addWidget(self.subtitle)
        header_layout.addWidget(title_box, 1)
        self.help_button = QToolButton()
        self.help_button.setObjectName("taTasksHelpButton")
        self.help_button.setText("?")
        self.help_button.setToolTip("How to use Task Workspace")
        self.help_button.setFixedSize(28, 28)
        self.help_button.clicked.connect(self._show_help)
        header_layout.addWidget(self.help_button)
        self.explainer = QLabel(
            "Create a task for each piece of project work, then capture its QGIS panels, "
            "toolbars and layer roles. Switching tasks restores that working context."
        )
        self.explainer.setObjectName("taTasksExplainer")
        self.explainer.setWordWrap(True)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(header)
        layout.addWidget(self.explainer)
        layout.addWidget(self.status)

        self.save_button = QPushButton("Save QGIS project to begin")
        self.save_button.setToolTip("Task definitions are stored beside the saved QGIS project")
        self.save_button.clicked.connect(self.plugin._save_project_as)
        layout.addWidget(self.save_button)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self._build_overview()
        self._build_workspace()
        self._build_tools()
        self._build_context()
        self._build_workflow()
        self._build_history()
        self._build_settings()
        self.setWidget(root)
        self.root = root
        root.setObjectName("taTasksRoot")
        self._apply_theme()
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setSingleShot(True)
        self.autosave_timer.setInterval(700)
        self.autosave_timer.timeout.connect(lambda: self._save_task(silent=True))
        self.refresh()

    def _apply_theme(self):
        self.root.setStyleSheet(stylesheet())

    def _show_help(self):
        if self._help_dialog is None:
            self._help_dialog = TaskWorkspaceHelpDialog(self)
        self._help_dialog.show()
        self._help_dialog.raise_()
        self._help_dialog.activateWindow()

    def changeEvent(self, event):  # noqa: N802 - Qt API
        super().changeEvent(event)
        if PALETTE_EVENTS and event.type() in PALETTE_EVENTS and hasattr(self, "root"):
            self._apply_theme()

    def _page(self):
        page = QWidget()
        page.setLayout(QVBoxLayout())
        return page

    def _build_overview(self):
        page = self._page()
        self.task_list = QListWidget()
        self.task_list.setSelectionMode(SINGLE_SELECTION)
        self.task_list.currentItemChanged.connect(self._task_selected)
        page.layout().addWidget(self.task_list, 1)
        row = QHBoxLayout()
        for text, slot in (
            ("New task", self.plugin._new_task),
            ("Restore", self.plugin._restore),
            ("Capture", self.plugin._capture),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            row.addWidget(button)
        page.layout().addLayout(row)
        form = QFormLayout()
        self.task_name = QLineEdit()
        self.task_type = QComboBox()
        self.task_type.setEditable(True)
        self.task_type.addItems(sorted(KNOWN_TASK_TYPES))
        self.task_status = QComboBox()
        for status in TaskStatus:
            self.task_status.addItem(status.value.replace("_", " ").title(), status.value)
        self.task_description = QTextEdit()
        self.task_description.setMaximumHeight(72)
        self.task_notes = QTextEdit()
        self.task_notes.setMaximumHeight(72)
        self.task_inputs = QLineEdit()
        self.task_inputs.setPlaceholderText("Comma-separated semantic roles")
        self.task_outputs = QLineEdit()
        self.task_outputs.setPlaceholderText("Comma-separated semantic roles")
        for label, widget in (("Name", self.task_name), ("Type", self.task_type),
                              ("Status", self.task_status), ("Description", self.task_description),
                              ("Notes", self.task_notes), ("Inputs", self.task_inputs),
                              ("Outputs", self.task_outputs)):
            form.addRow(label, widget)
        page.layout().addLayout(form)
        save = QPushButton("Save task details")
        save.clicked.connect(self._save_task)
        page.layout().addWidget(save)
        for widget in (self.task_name, self.task_inputs, self.task_outputs):
            widget.textEdited.connect(self._schedule_autosave)
        self.task_type.currentTextChanged.connect(self._schedule_autosave)
        self.task_status.currentIndexChanged.connect(self._schedule_autosave)
        self.task_description.textChanged.connect(self._schedule_autosave)
        self.task_notes.textChanged.connect(self._schedule_autosave)
        self.tabs.addTab(page, "Overview")

    def _build_workspace(self):
        page = self._page()
        text = QLabel("Capture and restore QGIS panels, toolbars and participating TerraAnalytica Labs. "
                      "Transient selections and unsaved edit sessions are excluded by default.")
        text.setWordWrap(True)
        page.layout().addWidget(text)
        profile_row = QHBoxLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.currentIndexChanged.connect(self._profile_changed)
        profile_row.addWidget(self.profile_combo, 1)
        for label, slot in (("New", self._new_profile), ("Rename", self._rename_profile),
                            ("Delete", self._delete_profile)):
            button = QPushButton(label)
            button.clicked.connect(slot)
            profile_row.addWidget(button)
        page.layout().addLayout(profile_row)
        self.capture_panels = QCheckBox("Panels and dock layout")
        self.capture_toolbars = QCheckBox("Toolbars")
        self.capture_participants = QCheckBox("Participating TerraAnalytica Labs")
        for check in (self.capture_panels, self.capture_toolbars, self.capture_participants):
            page.layout().addWidget(check)
        safe = QLabel("Feature selections, edit sessions and temporary scratch content are excluded.")
        safe.setWordWrap(True)
        page.layout().addWidget(safe)
        row = QHBoxLayout()
        for label, slot in (("Capture selected state", self._capture_profile),
                            ("Restore selected profile", self._restore_profile)):
            button = QPushButton(label)
            button.clicked.connect(slot)
            row.addWidget(button)
        page.layout().addLayout(row)
        page.layout().addStretch(1)
        self.tabs.addTab(page, "Workspace")

    def _build_tools(self):
        page = self._page()
        intro = QLabel(
            "ToolSearch records only stable tool IDs for the current task. No parameters, paths, "
            "layer names or outputs are captured."
        )
        intro.setWordWrap(True)
        page.layout().addWidget(intro)
        self.assigned_tools = QListWidget()
        self.recent_tools = QListWidget()
        self.suggested_tools = QListWidget()
        for label, widget in (("Assigned to this task", self.assigned_tools),
                              ("Recently used", self.recent_tools),
                              ("Learned suggestions", self.suggested_tools)):
            page.layout().addWidget(QLabel(label))
            widget.setSelectionMode(SINGLE_SELECTION)
            widget.setMaximumHeight(110)
            page.layout().addWidget(widget)
        self.tool_id = QLineEdit()
        self.tool_id.setPlaceholderText("Stable tool ID, for example processing:native:buffer")
        page.layout().addWidget(self.tool_id)
        buttons = QHBoxLayout()
        for label, slot in (("Assign tool ID", self._assign_tool),
                            ("Assign selected", self._assign_selected_tool),
                            ("Remove assigned", self._remove_assigned_tool),
                            ("Clear learning", self._clear_usage)):
            button = QPushButton(label)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        page.layout().addLayout(buttons)
        self.tabs.addTab(page, "Tools")

    def _assign_tool(self):
        self._set_assigned_tool(self.tool_id.text().strip(), True)

    def _assign_selected_tool(self):
        item = self.recent_tools.currentItem() or self.suggested_tools.currentItem()
        if item is not None:
            self._set_assigned_tool(item.text(), True)

    def _remove_assigned_tool(self):
        item = self.assigned_tools.currentItem()
        if item is not None:
            self._set_assigned_tool(item.text(), False)

    def _set_assigned_tool(self, tool_id, assigned):
        service = self.plugin.service
        if service is None or service.registry.current is None or not tool_id:
            return
        task = service.registry.current
        tools = list(task.preferred_tools)
        if assigned and tool_id not in tools:
            tools.append(tool_id)
        elif not assigned and tool_id in tools:
            tools.remove(tool_id)
        else:
            return
        try:
            service.registry.update_task(task.id, preferred_tools=tools)
            self.plugin._flush()
            self.tool_id.clear()
            self.refresh_tools()
        except (ValueError, RuntimeError) as exc:
            self.plugin._msg(str(exc), MessageLevel.Warning)

    def refresh_tools(self):
        for widget in (self.assigned_tools, self.recent_tools, self.suggested_tools):
            widget.clear()
        service = self.plugin.service
        if service is None or service.registry.current is None:
            return
        task = service.registry.current
        tools = service.build_context(task).get("tools", {})
        self.assigned_tools.addItems(tools.get("assigned", task.preferred_tools))
        self.recent_tools.addItems(tools.get("recent", []))
        self.suggested_tools.addItems(tools.get("suggested", []))

    def _build_context(self):
        page = self._page()
        self.context_text = QTextBrowser()
        page.layout().addWidget(self.context_text)
        check = QPushButton("Check layer roles")
        check.clicked.connect(self.plugin._check_roles)
        page.layout().addWidget(check)
        self.tabs.addTab(page, "Context")

    def _build_workflow(self):
        page = self._page()
        text = QLabel("Task dependencies describe project stages. Executable algorithms remain in "
                      "AI Central Flow or QGIS Processing.")
        text.setWordWrap(True)
        page.layout().addWidget(text)
        page.layout().addWidget(QLabel("PREDECESSOR TASKS"))
        self.predecessor_list = QListWidget()
        page.layout().addWidget(self.predecessor_list, 1)
        self.workflow_refs = QLineEdit()
        self.workflow_refs.setPlaceholderText("External workflow IDs, comma-separated")
        page.layout().addWidget(QLabel("LINKED PROCESSING WORKFLOWS"))
        page.layout().addWidget(self.workflow_refs)
        save = QPushButton("Save workflow links")
        save.clicked.connect(self._save_workflow)
        page.layout().addWidget(save)
        self.tabs.addTab(page, "Workflow")

    def _build_history(self):
        page = self._page()
        self.history_text = QTextBrowser()
        page.layout().addWidget(self.history_text)
        verify = QPushButton("Verify history integrity")
        verify.clicked.connect(self.plugin._verify)
        page.layout().addWidget(verify)
        self.tabs.addTab(page, "History")

    def _build_settings(self):
        page = self._page()
        self.setting_share_context = QCheckBox("Share structured task context with registered TA plugins")
        self.setting_learning = QCheckBox("Learn from local per-task tool usage")
        self.setting_autosave = QCheckBox("Auto-save task editor changes")
        self.setting_recovery = QCheckBox("Automatically roll back an unusable restored layout")
        for widget in (self.setting_share_context, self.setting_learning,
                       self.setting_autosave, self.setting_recovery):
            page.layout().addWidget(widget)
        privacy = QLabel("All settings and usage counters remain project-local. Cloud processing is disabled.")
        privacy.setWordWrap(True)
        page.layout().addWidget(privacy)
        clear = QPushButton("Clear local tool-usage learning")
        clear.clicked.connect(self._clear_usage)
        page.layout().addWidget(clear)
        save = QPushButton("Save settings")
        save.clicked.connect(self._save_settings)
        page.layout().addWidget(save)
        page.layout().addStretch(1)
        self.tabs.addTab(page, "Settings")

    def _task_selected(self, current: QListWidgetItem | None, _previous=None):
        if current is None or self.plugin.service is None:
            return
        task_id = current.data(USER_ROLE)
        if task_id != self.plugin.service.registry.project.current_task_id:
            self.plugin._select_task_id(task_id)

    @staticmethod
    def _values(text):
        return [part.strip() for part in text.replace("\n", ",").split(",") if part.strip()]

    def _schedule_autosave(self, *_):
        if self._loading or self.plugin.service is None:
            return
        if self.plugin.service.registry.project.settings.auto_save_edits:
            self.autosave_timer.start()

    def _save_task(self, _checked=False, silent=False):
        service = self.plugin.service
        if self._loading or service is None or service.registry.current is None:
            return
        task = service.registry.current
        try:
            service.registry.update_task(
                task.id,
                name=self.task_name.text().strip(),
                type=self.task_type.currentText().strip() or "general",
                status=self.task_status.currentData(),
                description=self.task_description.toPlainText().strip(),
                notes=self.task_notes.toPlainText().strip(),
            )
            service.registry.replace_roles(
                task.id, self._values(self.task_inputs.text()), self._values(self.task_outputs.text())
            )
            self.plugin._flush()
            if not silent:
                self.plugin._msg("Task details saved.", MessageLevel.Success)
                self.refresh()
        except (ValueError, RuntimeError) as exc:
            self.plugin._msg(str(exc), MessageLevel.Warning)

    def _selected_profile_id(self):
        return self.profile_combo.currentData()

    def _profile_changed(self, *_):
        if self._loading or self.plugin.service is None:
            return
        profile_id = self._selected_profile_id()
        profile = next((p for p in self.plugin.service.registry.project.profiles
                        if p.id == profile_id), None)
        if profile is None:
            return
        defaults = self.plugin.service.registry.project.settings
        self.capture_panels.setChecked(profile.capture_options.get("panels_and_docks", defaults.capture_panels))
        self.capture_toolbars.setChecked(profile.capture_options.get("toolbars", defaults.capture_toolbars))
        self.capture_participants.setChecked(
            profile.capture_options.get("participants", defaults.capture_participants)
        )

    def capture_options(self):
        return CaptureOptions(
            panels_and_docks=self.capture_panels.isChecked(),
            toolbars=self.capture_toolbars.isChecked(),
            participants=self.capture_participants.isChecked(),
        )

    def _capture_profile(self):
        service = self.plugin.service
        if service is None or service.registry.current is None:
            return
        try:
            profile = service.capture_current_workspace(self._selected_profile_id(), self.capture_options())
            self.plugin._flush()
            self.plugin._msg(f"Captured workspace profile '{profile.name}'.", MessageLevel.Success)
            self.refresh()
        except (ValueError, RuntimeError) as exc:
            self.plugin._msg(str(exc), MessageLevel.Warning)

    def _restore_profile(self):
        service = self.plugin.service
        if service is None or service.registry.current is None:
            return
        report = service.restore_task(service.registry.current.id, self._selected_profile_id())
        self.plugin._flush()
        if report.warnings:
            self.plugin._msg("; ".join(report.warnings), MessageLevel.Warning)
        else:
            self.plugin._msg("Workspace profile restored.", MessageLevel.Success)
        self.refresh()

    def _new_profile(self):
        service = self.plugin.service
        if service is None or service.registry.current is None:
            return
        from qgis.PyQt.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New workspace profile", "Profile name:")
        if ok and name.strip():
            profile = service.registry.new_profile(
                service.registry.current.id, classify_display(service.shell.backend.screens()), name.strip()
            )
            service.registry.save_profile(profile)
            self.plugin._flush()
            self.refresh()
            self.profile_combo.setCurrentIndex(self.profile_combo.findData(profile.id))

    def _rename_profile(self):
        profile_id = self._selected_profile_id()
        if not profile_id or self.plugin.service is None:
            return
        from qgis.PyQt.QtWidgets import QInputDialog
        current = self.profile_combo.currentText()
        name, ok = QInputDialog.getText(self, "Rename workspace profile", "Profile name:", text=current)
        if ok and name.strip():
            self.plugin.service.registry.rename_profile(profile_id, name)
            self.plugin._flush()
            self.refresh()

    def _delete_profile(self):
        profile_id = self._selected_profile_id()
        if not profile_id or self.plugin.service is None:
            return
        self.plugin.service.registry.delete_profile(profile_id)
        self.plugin._flush()
        self.refresh()

    def _save_workflow(self):
        service = self.plugin.service
        if service is None or service.registry.current is None:
            return
        task = service.registry.current
        predecessors = []
        for row in range(self.predecessor_list.count()):
            item = self.predecessor_list.item(row)
            if item.checkState() == CHECKED:
                predecessors.append(item.data(USER_ROLE))
        try:
            service.registry.replace_links(task.id, predecessors)
            service.registry.replace_associations(task.id, "workflow", self._values(self.workflow_refs.text()))
            self.plugin._flush()
            self.plugin._msg("Task dependencies and workflow references saved.", MessageLevel.Success)
            self.refresh()
        except (ValueError, RuntimeError) as exc:
            self.plugin._msg(str(exc), MessageLevel.Warning)

    def _save_settings(self):
        service = self.plugin.service
        if service is None:
            return
        settings = service.registry.update_settings(
            share_task_context=self.setting_share_context.isChecked(),
            usage_learning=self.setting_learning.isChecked(),
            auto_save_edits=self.setting_autosave.isChecked(),
            recovery_enabled=self.setting_recovery.isChecked(),
            capture_panels=self.capture_panels.isChecked(),
            capture_toolbars=self.capture_toolbars.isChecked(),
            capture_participants=self.capture_participants.isChecked(),
        )
        if service.usage is not None:
            service.usage.enabled = settings.usage_learning
        self.plugin._flush()
        self.plugin._msg("Task Workspace settings saved.", MessageLevel.Success)

    def _clear_usage(self):
        service = self.plugin.service
        if service is not None and service.usage is not None:
            service.usage.clear()
            self.plugin._msg("Local tool-usage learning cleared.", MessageLevel.Success)
            self.refresh()

    def refresh(self):
        self._loading = True
        service = self.plugin.service
        ready = service is not None
        self.save_button.setVisible(not ready)
        self.tabs.setEnabled(ready)
        self.task_list.blockSignals(True)
        self.task_list.clear()
        if not ready:
            self.status.setText("Save this QGIS project first. TA Tasks stores its definitions and "
                                "audit history in a local folder beside the project file.")
            self.refresh_tools()
            self.context_text.setText("Task context appears after a saved project has a current task.")
            self.history_text.setText("History begins when the saved project creates its TA Tasks store.")
            self.task_list.blockSignals(False)
            self._loading = False
            return

        registry = service.registry
        current_id = registry.project.current_task_id
        for task in registry.tasks:
            item = QListWidgetItem(task.name)
            item.setData(USER_ROLE, task.id)
            item.setToolTip(task.description or task.type)
            self.task_list.addItem(item)
            if task.id == current_id:
                self.task_list.setCurrentItem(item)
        self.task_list.blockSignals(False)
        task = registry.current
        self.status.setText(f"Project: {registry.project.name}  •  {len(registry.tasks)} task(s)")
        if task is None:
            self.refresh_tools()
            self.context_text.setText("No current task.")
        else:
            self.task_name.setText(task.name)
            self.task_type.setCurrentText(task.type)
            self.task_status.setCurrentIndex(max(0, self.task_status.findData(task.status.value)))
            self.task_description.setPlainText(task.description)
            self.task_notes.setPlainText(task.notes)
            self.task_inputs.setText(", ".join(role.role for role in task.inputs))
            self.task_outputs.setText(", ".join(role.role for role in task.outputs))
            self.profile_combo.clear()
            profiles = registry.project.profiles_for(task.id)
            for profile in profiles:
                label = profile.name + (f" — {profile.captured_at}" if profile.captured_at else " — not captured")
                self.profile_combo.addItem(label, profile.id)
            settings = registry.project.settings
            selected = profiles[0] if profiles else None
            options = selected.capture_options if selected else {}
            self.capture_panels.setChecked(options.get("panels_and_docks", settings.capture_panels))
            self.capture_toolbars.setChecked(options.get("toolbars", settings.capture_toolbars))
            self.capture_participants.setChecked(options.get("participants", settings.capture_participants))
            self.predecessor_list.clear()
            for candidate in registry.tasks:
                if candidate.id == task.id:
                    continue
                item = QListWidgetItem(candidate.name)
                item.setData(USER_ROLE, candidate.id)
                item.setFlags(item.flags() | ITEM_IS_USER_CHECKABLE)
                item.setCheckState(CHECKED if candidate.id in task.predecessors else UNCHECKED)
                self.predecessor_list.addItem(item)
            self.workflow_refs.setText(", ".join(task.associations.get("workflow", [])))
            context = service.build_context(task)
            self.refresh_tools()
            roles = context.get("roles", {})
            self.context_text.setText(
                f"Type: {task.type}\nInputs: {', '.join(context.get('inputs', [])) or 'None'}\n"
                f"Outputs: {', '.join(context.get('outputs', [])) or 'None'}\n"
                f"Layer roles: {', '.join(f'{k}: {v}' for k, v in roles.items()) or 'Not resolved'}"
            )
        settings = registry.project.settings
        self.setting_share_context.setChecked(settings.share_task_context)
        self.setting_learning.setChecked(settings.usage_learning)
        self.setting_autosave.setChecked(settings.auto_save_edits)
        self.setting_recovery.setChecked(settings.recovery_enabled)
        if self.plugin.store is None:
            self.history_text.setText("Git-backed history is unavailable for this project session.")
        else:
            rows = self.plugin.store.history(limit=20)
            self.history_text.setText("\n".join(f"{r.date}  {r.subject}" for r in rows) or "No history yet.")
        self._loading = False
