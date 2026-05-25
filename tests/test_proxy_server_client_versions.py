import asyncio
import tempfile
import unittest
from pathlib import Path

from models import ConfigStorage, MCPConfig, ProtocolType, ToolConfig
from proxy_server import MCPClientVersionTracker, MCPProxyManager, ToolListVersionMiddleware


class FakeSession:
    def __init__(self):
        self.notification_count = 0

    async def send_tool_list_changed(self):
        self.notification_count += 1


class FakeFastMCPContext:
    request_context = object()

    def __init__(self, session_id, session):
        self.session_id = session_id
        self.session = session


class FakeMiddlewareContext:
    def __init__(self, method, session_id, session):
        self.method = method
        self.fastmcp_context = FakeFastMCPContext(session_id, session)


async def return_tools(_context):
    return "tools"


async def bump_version_while_listing(_context):
    _context.bump_config_version()
    return "tools"


async def return_called(_context):
    return "called"


class MCPClientVersionTrackerTest(unittest.TestCase):
    def test_marks_client_synced_only_after_tools_list(self):
        async def run():
            tracker = MCPClientVersionTracker(version_factory=iter([100, 200]).__next__)
            session = FakeSession()

            tracker.mark_tools_listed("session-1", session)
            self.assertEqual(100, tracker.client_versions["session-1"])

            tracker.bump_config_version()
            self.assertEqual(200, tracker.current_version)

            notified = await tracker.notify_if_outdated("session-1", session)

            self.assertTrue(notified)
            self.assertEqual(1, session.notification_count)
            self.assertEqual(100, tracker.client_versions["session-1"])

            tracker.mark_tools_listed("session-1", session)

            self.assertEqual(200, tracker.client_versions["session-1"])

        asyncio.run(run())

    def test_does_not_notify_current_client(self):
        async def run():
            tracker = MCPClientVersionTracker(version_factory=iter([100]).__next__)
            session = FakeSession()

            tracker.mark_tools_listed("session-1", session)
            notified = await tracker.notify_if_outdated("session-1", session)

            self.assertFalse(notified)
            self.assertEqual(0, session.notification_count)

        asyncio.run(run())

    def test_unknown_client_is_recorded_as_unsynced(self):
        async def run():
            tracker = MCPClientVersionTracker(version_factory=iter([100]).__next__)
            session = FakeSession()

            notified = await tracker.notify_if_outdated("session-1", session)

            self.assertTrue(notified)
            self.assertEqual(0, tracker.client_versions["session-1"])
            self.assertEqual(1, session.notification_count)

        asyncio.run(run())


class ToolListVersionMiddlewareTest(unittest.TestCase):
    def test_tools_list_marks_session_as_current(self):
        async def run():
            tracker = MCPClientVersionTracker(version_factory=iter([100]).__next__)
            middleware = ToolListVersionMiddleware(tracker)
            session = FakeSession()
            context = FakeMiddlewareContext("tools/list", "session-1", session)

            result = await middleware.on_list_tools(context, return_tools)

            self.assertEqual("tools", result)
            self.assertEqual(100, tracker.client_versions["session-1"])

        asyncio.run(run())

    def test_tools_list_marks_version_from_request_start(self):
        async def run():
            tracker = MCPClientVersionTracker(version_factory=iter([100, 200]).__next__)
            middleware = ToolListVersionMiddleware(tracker)
            session = FakeSession()
            context = FakeMiddlewareContext("tools/list", "session-1", session)
            context.bump_config_version = tracker.bump_config_version

            result = await middleware.on_list_tools(context, bump_version_while_listing)

            self.assertEqual("tools", result)
            self.assertEqual(100, tracker.client_versions["session-1"])
            self.assertEqual(200, tracker.current_version)

        asyncio.run(run())

    def test_non_tools_list_request_notifies_outdated_session(self):
        async def run():
            tracker = MCPClientVersionTracker(version_factory=iter([100, 200]).__next__)
            middleware = ToolListVersionMiddleware(tracker)
            session = FakeSession()
            tracker.mark_tools_listed("session-1", session)
            tracker.bump_config_version()
            context = FakeMiddlewareContext("tools/call", "session-1", session)

            result = await middleware.on_request(context, return_called)

            self.assertEqual("called", result)
            self.assertEqual(1, session.notification_count)
            self.assertEqual(100, tracker.client_versions["session-1"])

        asyncio.run(run())


class ConfigStorageMetadataTest(unittest.TestCase):
    def test_runtime_metadata_is_saved_and_cleared_without_becoming_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = ConfigStorage(config_dir=Path(temp_dir))
            storage.add(MCPConfig(
                id="cfg-1",
                name="demo",
                protocol=ProtocolType.HTTP,
                tools=[ToolConfig(name="tool")],
            ))

            storage.set_runtime_metadata("mcp_client_versions", {"session-1": 100})
            storage = ConfigStorage(config_dir=Path(temp_dir))
            self.assertEqual(["cfg-1"], [cfg.id for cfg in storage.list_all()])
            self.assertEqual(
                {"session-1": 100},
                storage.get_runtime_metadata("mcp_client_versions"),
            )

            storage.clear_runtime_metadata("mcp_client_versions")
            storage = ConfigStorage(config_dir=Path(temp_dir))
            self.assertIsNone(storage.get_runtime_metadata("mcp_client_versions"))
            self.assertEqual(["cfg-1"], [cfg.id for cfg in storage.list_all()])

    def test_proxy_manager_clears_client_versions_on_startup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = ConfigStorage(config_dir=Path(temp_dir))
            storage.add(MCPConfig(
                id="cfg-1",
                name="demo",
                protocol=ProtocolType.HTTP,
                tools=[ToolConfig(name="tool")],
            ))
            storage.set_runtime_metadata("mcp_client_versions", {"session-1": 100})

            MCPProxyManager(ConfigStorage(config_dir=Path(temp_dir)))
            storage = ConfigStorage(config_dir=Path(temp_dir))

            metadata = storage.get_runtime_metadata("mcp_client_versions")
            self.assertIsInstance(metadata["current_version"], int)
            self.assertEqual({}, metadata["client_versions"])

    def test_tracker_persists_client_versions_to_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = ConfigStorage(config_dir=Path(temp_dir))
            tracker = MCPClientVersionTracker(
                version_factory=iter([100]).__next__,
                persist_callback=lambda metadata: storage.set_runtime_metadata(
                    "mcp_client_versions",
                    metadata,
                ),
            )

            tracker.mark_tools_listed("session-1", FakeSession(), 100)
            storage = ConfigStorage(config_dir=Path(temp_dir))

            self.assertEqual(
                {
                    "current_version": 100,
                    "client_versions": {"session-1": 100},
                },
                storage.get_runtime_metadata("mcp_client_versions"),
            )


if __name__ == "__main__":
    unittest.main()
