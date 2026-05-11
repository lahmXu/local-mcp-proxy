import os


class MySQLConfig:
    """MySQL 连接配置"""

    def __init__(self):
        self.host = os.getenv("MYSQL_HOST", "localhost")
        self.port = int(os.getenv("MYSQL_PORT", "3306"))
        self.user = os.getenv("MYSQL_USER", "root")
        self.password = os.getenv("MYSQL_PASSWORD", "")
        self.database = os.getenv("MYSQL_DATABASE", "")

    def to_dict(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "database": self.database,
        }

    def validate(self) -> list[str]:
        """验证配置，返回缺失项列表"""
        missing = []
        if not self.host:
            missing.append("MYSQL_HOST")
        if not self.user:
            missing.append("MYSQL_USER")
        if not self.database:
            missing.append("MYSQL_DATABASE")
        return missing


# 全局配置实例
config = MySQLConfig()
