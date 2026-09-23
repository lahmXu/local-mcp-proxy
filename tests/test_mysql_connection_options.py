import unittest
from unittest.mock import patch

import adapters
from adapters import build_mysql_connection_settings, execute_mysql_tool
from models import MCPConfig, MySQLConfig, ProtocolType, ToolConfig
from web_app import _validate_config


def mysql_config(**advanced_options):
    return MySQLConfig(
        host="db.example.com",
        port=3306,
        user="reader",
        password="secret",
        database="analytics",
        advanced_options={
            "autocommit": True,
            "connection_timeout": 5,
            "pool_size": 3,
            "pool_reset_session": True,
            **advanced_options,
        },
    )


class MySQLConfigTest(unittest.TestCase):
    def test_old_config_gets_safe_advanced_defaults(self):
        cfg = MySQLConfig.from_dict({
            "host": "localhost",
            "port": 3306,
            "user": "root",
            "password": "",
            "database": "demo",
        })

        self.assertTrue(cfg.advanced_options["autocommit"])
        self.assertTrue(cfg.advanced_options["pool_reset_session"])
        self.assertEqual(3, cfg.advanced_options["pool_size"])
        self.assertEqual(5, cfg.advanced_options["connection_timeout"])

    def test_unknown_connector_options_are_preserved(self):
        cfg = MySQLConfig.from_dict({
            "advanced_options": {
                "charset": "utf8mb4",
                "time_zone": "+08:00",
            },
        })

        self.assertEqual("utf8mb4", cfg.advanced_options["charset"])
        self.assertEqual("+08:00", cfg.advanced_options["time_zone"])

    def test_advanced_options_must_be_an_object(self):
        with self.assertRaisesRegex(ValueError, "JSON 对象"):
            MySQLConfig.from_dict({"advanced_options": []})


class MySQLConnectionSettingsTest(unittest.TestCase):
    def test_splits_pool_options_from_connector_options(self):
        cfg = mysql_config(charset="utf8mb4", pool_size=7)

        connection_options, pool_options = build_mysql_connection_settings(cfg)

        self.assertEqual(7, pool_options["pool_size"])
        self.assertTrue(pool_options["pool_reset_session"])
        self.assertEqual("utf8mb4", connection_options["charset"])
        self.assertTrue(connection_options["autocommit"])
        self.assertNotIn("pool_size", connection_options)
        self.assertEqual("db.example.com", connection_options["host"])

    def test_validation_accepts_unknown_options_and_rejects_managed_fields(self):
        cfg = MCPConfig(
            id="cfg-1",
            name="mysql",
            protocol=ProtocolType.MYSQL,
            protocol_config=mysql_config(ssl_disabled=True),
        )
        self.assertIsNone(_validate_config(cfg))

        cfg.protocol_config.advanced_options["host"] = "other.example.com"
        self.assertIn("host", _validate_config(cfg))

    def test_pool_is_recreated_when_advanced_options_change(self):
        adapters._mysql_pools.clear()
        cfg = MCPConfig(
            id="cfg-1",
            name="mysql",
            protocol=ProtocolType.MYSQL,
            protocol_config=mysql_config(),
        )
        first_pool = object()
        second_pool = object()

        with patch(
            "adapters.mysql.connector.pooling.MySQLConnectionPool",
            side_effect=[first_pool, second_pool],
        ) as pool_factory:
            self.assertIs(first_pool, adapters._get_mysql_pool(cfg))
            self.assertIs(first_pool, adapters._get_mysql_pool(cfg))
            cfg.protocol_config.advanced_options["autocommit"] = False
            self.assertIs(second_pool, adapters._get_mysql_pool(cfg))

        self.assertEqual(2, pool_factory.call_count)


class FakeCursor:
    description = [("value", 3)]

    def __init__(self):
        self.closed = False

    def execute(self, _sql):
        return None

    def fetchall(self):
        return []

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self):
        self.cursor_instance = FakeCursor()
        self.in_transaction = True
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def rollback(self):
        self.rolled_back = True
        self.in_transaction = False

    def close(self):
        self.closed = True


class FakePool:
    def __init__(self, connection):
        self.connection = connection

    def get_connection(self):
        return self.connection


class MySQLExecutionCleanupTest(unittest.TestCase):
    def test_closes_cursor_and_rolls_back_before_returning_connection(self):
        connection = FakeConnection()
        cfg = MCPConfig(
            id="cfg-1",
            name="mysql",
            protocol=ProtocolType.MYSQL,
            protocol_config=mysql_config(autocommit=False),
        )

        with patch("adapters._get_mysql_pool", return_value=FakePool(connection)):
            result = execute_mysql_tool(
                cfg,
                ToolConfig(name="query", sql="SELECT 1", format="json"),
                {},
            )

        self.assertEqual("[]", result)
        self.assertTrue(connection.cursor_instance.closed)
        self.assertTrue(connection.rolled_back)
        self.assertTrue(connection.closed)


if __name__ == "__main__":
    unittest.main()
