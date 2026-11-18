import tempfile
import unittest
from pathlib import Path

from ta_tasks.twm.migration import migrate
from ta_tasks.twm.registry import RegistryError, TaskRegistry
from ta_tasks.twm.schemas import DisplayClass, Project, ProjectSettings, WorkspaceProfile


class TaskManagerModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.registry = TaskRegistry.for_path(Path(self.temp.name) / "project.json", "Test")
        self.first = self.registry.create_task("Prepare")
        self.second = self.registry.create_task("Analyse")

    def tearDown(self):
        self.temp.cleanup()

    def test_v1_projects_migrate_with_safe_settings(self):
        raw = self.registry.project.to_dict()
        raw["schema_version"] = 1
        raw["project"].pop("settings", None)
        migrated = migrate(raw)
        self.assertEqual(migrated["schema_version"], 2)
        loaded = Project.from_dict(migrated)
        self.assertTrue(loaded.settings.recovery_enabled)
        self.assertTrue(loaded.settings.usage_learning)

    def test_task_editor_fields_roles_and_workflow_references_persist(self):
        self.registry.update_task(self.second.id, name="Vegetation", type="remote_sensing_analysis",
                                  status="active", description="Analyse imagery", notes="Review QA")
        self.registry.replace_roles(self.second.id, ["multispectral_imagery"], ["analysis_output"])
        self.registry.replace_links(self.second.id, [self.first.id])
        self.registry.replace_associations(self.second.id, "workflow", ["ai-central:ndvi-v1"])
        task = self.registry.get(self.second.id)
        self.assertEqual(task.name, "Vegetation")
        self.assertEqual([x.role for x in task.inputs], ["multispectral_imagery"])
        self.assertEqual(task.predecessors, [self.first.id])
        self.assertEqual(task.associations["workflow"], ["ai-central:ndvi-v1"])

    def test_cycle_safe_dependency_replacement(self):
        self.registry.replace_links(self.second.id, [self.first.id])
        with self.assertRaises(RegistryError):
            self.registry.replace_links(self.first.id, [self.second.id])
        self.assertEqual(self.registry.get(self.second.id).predecessors, [self.first.id])

    def test_profile_management_and_capture_options_round_trip(self):
        profile = WorkspaceProfile("desktop", self.first.id, "Desktop", DisplayClass.SINGLE_STANDARD,
                                   capture_options={"panels_and_docks": True, "toolbars": False})
        self.registry.save_profile(profile)
        self.registry.rename_profile("desktop", "Office")
        loaded = Project.from_dict(self.registry.project.to_dict())
        self.assertEqual(loaded.profiles[0].name, "Office")
        self.assertFalse(loaded.profiles[0].capture_options["toolbars"])
        self.registry.delete_profile("desktop")
        self.assertEqual(self.registry.project.profiles, [])

    def test_settings_are_validated_and_persisted(self):
        settings = self.registry.update_settings(usage_learning=False, auto_save_edits=False,
                                                 share_task_context=False, recovery_enabled=True)
        self.assertFalse(settings.usage_learning)
        loaded = Project.from_dict(self.registry.project.to_dict())
        self.assertFalse(loaded.settings.share_task_context)
        with self.assertRaises(RegistryError):
            self.registry.update_settings(usage_learning="no")


if __name__ == "__main__":
    unittest.main()
