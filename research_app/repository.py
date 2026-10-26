"""Small, transactional persistence adapter for the UI prototype."""
from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path
import sqlite3
from typing import Any

from research_app.data import seed_workspace, validate_workspace


class ConflictError(RuntimeError):
    """Another session changed this user's workspace; reload before retrying."""


class Repository:
    def __init__(self, path: str | Path, user_id: str):
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("A non-empty user_id is required")
        self.path = Path(path).expanduser()
        self.user_id = user_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS workspaces (
                user_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK (revision >= 0)
            )""")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.execute("PRAGMA busy_timeout = 15000")
        return connection

    def load(self) -> tuple[dict[str, Any], int]:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT OR IGNORE INTO workspaces (user_id, payload, revision) VALUES (?, ?, 0)",
                (self.user_id, json.dumps(seed_workspace(), allow_nan=False)),
            )
            row = connection.execute(
                "SELECT payload, revision FROM workspaces WHERE user_id = ?", (self.user_id,)
            ).fetchone()
        return json.loads(row[0]), row[1]

    def save(self, workspace: dict[str, Any], expected_revision: int) -> int:
        validate_workspace(workspace)
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("expected_revision must be a non-negative integer")
        payload = json.dumps(workspace, allow_nan=False)
        with closing(self._connect()) as connection, connection:
            changed = connection.execute(
                "UPDATE workspaces SET payload = ?, revision = revision + 1 "
                "WHERE user_id = ? AND revision = ?",
                (payload, self.user_id, expected_revision),
            ).rowcount
            if changed != 1:
                raise ConflictError("Workspace changed in another session. Reload to review the latest changes.")
        return expected_revision + 1

    def reset(self, expected_revision: int) -> int:
        """Restore fictional demonstration data without rewinding the revision."""
        return self.save(seed_workspace(), expected_revision)
