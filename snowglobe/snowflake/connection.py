import snowflake.connector
from snowflake.connector import DictCursor
from cryptography.hazmat.primitives import serialization
from typing import Optional
from pathlib import Path

class SnowflakeReadOnly:
    """
    Read-only Snowflake connector.

    Enforces:
    - No DDL/GRANT statements
    - Context manager usage
    """

    def __init__(
        self,
        account: str,
        user: str,
        role: Optional[str] = None,
        password: Optional[str] = None,
        private_key_path: Optional[str] = None,
        private_key_pwd: Optional[str] = None,
        warehouse: Optional[str] = None
    ):
        self.account = account
        self.warehouse = warehouse
        self.user = user
        self.role = role
        self.password = password
        self.private_key_path = private_key_path
        self.private_key_pwd = private_key_pwd
        self.conn: Optional[snowflake.connector.SnowflakeConnection] = None

    def __enter__(self):
        conn_args = {
            "user": self.user,
            "account": self.account,
            "role": self.role,
            "warehouse": self.warehouse,
            "autocommit": True,
        }
        if self.private_key_path:
            private_key_file = Path(self.private_key_path).expanduser()
            with private_key_file.open("rb") as f:
                p_key = serialization.load_pem_private_key(
                    f.read(),
                    password=self.private_key_pwd.encode() if self.private_key_pwd else None,
                )
            pkb = p_key.private_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            conn_args["private_key"] = pkb
        else:
            conn_args["password"] = self.password

        self.conn = snowflake.connector.connect(**conn_args)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.conn:
            self.conn.close()

    def query(self, sql: str):
        """
        Execute a read-only query. Raises an exception if it detects DDL.
        """
        ddl_keywords = ["CREATE", "ALTER", "DROP", "GRANT", "REVOKE", "TRUNCATE"]
        if any(sql.strip().upper().startswith(k) for k in ddl_keywords):
            raise ValueError("SnowflakeReadOnly: DDL/DCL statements are not allowed")
        with self.conn.cursor(DictCursor) as cur:
            cur.execute(sql)
            return cur.fetchall()
