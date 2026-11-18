import json
import tempfile
import unittest
from pathlib import Path

from ta_tasks.twm.events import EventBus, Events
from ta_tasks.twm.usage import ToolUsageStore, UsageError, validate_tool_id
from ta_tasks.twm.security import scrub_secrets


class ToolUsageStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "usage.json"

    def tearDown(self):
        self.temp.cleanup()

    def test_aggregate_ranking_and_reload(self):
        store = ToolUsageStore(self.path)
        store.record("vegetation", "native:buffer", "2026-10-01T00:00:00+00:00")
        store.record("vegetation", "gdal:clip", "2026-10-02T00:00:00+00:00")
        store.record("vegetation", "native:buffer", "2026-10-03T00:00:00+00:00")
        rows = ToolUsageStore(self.path).ranked("vegetation")
        self.assertEqual([(r.tool_id, r.count) for r in rows],
                         [("native:buffer", 2), ("gdal:clip", 1)])

    def test_disabled_collection_writes_nothing(self):
        store = ToolUsageStore(self.path, enabled=False)
        self.assertFalse(store.record("vegetation", "native:buffer"))
        self.assertFalse(self.path.exists())

    def test_clear_one_task_preserves_other_task(self):
        store = ToolUsageStore(self.path)
        store.record("one", "native:buffer")
        store.record("two", "native:clip")
        store.clear("one")
        self.assertEqual(store.ranked("one"), [])
        self.assertEqual(store.ranked("two")[0].tool_id, "native:clip")

    def test_bus_records_only_minimal_identifiers(self):
        bus = EventBus()
        store = ToolUsageStore(self.path)
        unsubscribe = store.attach(bus)
        bus.publish(Events.TOOL_USED, task_id="mapping", tool_id="qgis:layout",
                    parameters={"password": "must-not-be-recorded"})
        unsubscribe()
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertNotIn("password", json.dumps(raw))
        self.assertEqual(raw["tasks"]["mapping"]["qgis:layout"]["count"], 1)

    def test_rejects_free_text_and_path_like_identifiers(self):
        store = ToolUsageStore(self.path)
        with self.assertRaises(UsageError):
            store.record("task", "tool id with user text")
        with self.assertRaises(UsageError):
            store.record("../../escape", "tool")

    def test_public_tool_identifier_validation(self):
        self.assertEqual(validate_tool_id("processing:native:buffer"),
                         "processing:native:buffer")
        with self.assertRaises(UsageError):
            validate_tool_id("layer /Users/person/private.gpkg")

    def test_audit_payload_text_is_redacted(self):
        value = scrub_secrets({"message": "failed https://alice:hunter2@example.test x token=abc123"})
        self.assertNotIn("hunter2", value["message"])
        self.assertNotIn("abc123", value["message"])


if __name__ == "__main__":
    unittest.main()
