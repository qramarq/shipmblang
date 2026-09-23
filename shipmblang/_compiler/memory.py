"""Shared, local SQLite memory for ShipMB prose and reviewed meanings.

The store is deliberately independent from the compiler pipeline.  Constructing
``MemoryStore`` is the first operation that creates a database; importing this
module never writes to disk.
"""
from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Any
from uuid import uuid4


SCHEMA_VERSION = 2
CACHE_LIMIT = 5_000
MAX_DOCUMENT_CHARS = 1_000_000


def default_memory_path() -> Path:
    override = os.environ.get("SHIPMB_MEMORY_DB")
    if override:
        return Path(override).expanduser().resolve()
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base).resolve() / "ShipMB" / "memory.sqlite3"
    return Path.home() / ".local" / "share" / "ShipMB" / "memory.sqlite3"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _object(value: str) -> Any:
    return json.loads(value)


def _normalized(source: str) -> str:
    return " ".join(source.casefold().split())


def _sha(value: str | bytes) -> str:
    data = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


def _profile_pair(context: Mapping[str, Any], versions: Mapping[str, Any] | None = None) -> tuple[str, str] | None:
    """Validate optional profile metadata without invalidating legacy rows."""
    context_profile = context.get("profile")
    context_version = context.get("profile_version")
    version_profile = versions.get("profile") if versions is not None else None
    explicit_version = versions.get("profile_version") if versions is not None else None
    if context_profile is None and context_version is None and version_profile is None and explicit_version is None:
        return None
    if not isinstance(context_profile, str) or not context_profile.strip():
        raise ValueError("context profile must be a nonempty string")
    if versions is None:
        if context_version is not None and (not isinstance(context_version, str) or not context_version.strip()):
            raise ValueError("context profile_version must be a nonempty string")
        # Cross-version related lookup and memory revision are partitioned by
        # the explicit context profile even when the version lives in the
        # versions mapping used by confirmed lookup.
        return context_profile, context_version or "versioned-by-lookup"
    if any(value is not None for value in (context_version, version_profile, explicit_version)):
        values = (context_version, version_profile, explicit_version)
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError("explicit profile metadata must include nonempty profile_version and profile in both mappings")
        if context_profile != version_profile or context_version != explicit_version:
            raise ValueError("context and versions must name the same profile and profile_version")
        return context_profile, context_version
    # Compatibility for the direct compiler's schema-v2 integration: the
    # context names the profile and the grammar/catalog pair versions it.
    grammar = versions.get("grammar")
    catalog = versions.get("catalog")
    if not isinstance(grammar, str) or not grammar.strip() or not isinstance(catalog, str) or not catalog.strip():
        raise ValueError("profile context requires explicit profile_version or versioned grammar and catalog")
    return context_profile, f"grammar={grammar};catalog={catalog}"


class MemoryStore:
    """Process-safe SQLite facade; each operation uses its own connection."""

    def __init__(self, path: str | os.PathLike[str] | None = None, *, cache_limit: int = CACHE_LIMIT):
        self.path = Path(path).expanduser().resolve() if path is not None else default_memory_path()
        if cache_limit < 1:
            raise ValueError("cache_limit must be positive")
        self.cache_limit = cache_limit
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _migrate(self) -> None:
        with self._connection() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError(f"Memory schema {version} is newer than supported schema {SCHEMA_VERSION}")
            if version == 0:
                connection.executescript(
                    """
                    BEGIN IMMEDIATE;
                    CREATE TABLE IF NOT EXISTS projects (
                        name TEXT PRIMARY KEY,
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS submissions (
                        id TEXT PRIMARY KEY,
                        source TEXT NOT NULL,
                        source_hash TEXT NOT NULL,
                        normalized_source TEXT NOT NULL,
                        project TEXT NOT NULL REFERENCES projects(name),
                        pipeline TEXT NOT NULL,
                        result_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS submissions_lookup
                        ON submissions(project, source_hash, created_at);
                    CREATE TABLE IF NOT EXISTS interpretations (
                        id TEXT PRIMARY KEY,
                        submission_id TEXT REFERENCES submissions(id),
                        project TEXT NOT NULL REFERENCES projects(name),
                        source_hash TEXT NOT NULL,
                        normalized_source TEXT NOT NULL,
                        meaning_json TEXT NOT NULL,
                        context_json TEXT NOT NULL,
                        versions_json TEXT NOT NULL,
                        scope TEXT NOT NULL DEFAULT 'project'
                            CHECK(scope IN ('project','global')),
                        status TEXT NOT NULL DEFAULT 'candidate'
                            CHECK(status IN ('candidate','confirmed','superseded')),
                        reviewer TEXT,
                        reviewed_at TEXT,
                        superseded_by TEXT REFERENCES interpretations(id),
                        revision INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS interpretations_lookup
                        ON interpretations(normalized_source, status, project, scope);
                    CREATE TABLE IF NOT EXISTS clarification_history (
                        id TEXT PRIMARY KEY,
                        submission_id TEXT NOT NULL REFERENCES submissions(id),
                        question TEXT NOT NULL,
                        answer TEXT NOT NULL,
                        interpretation_id TEXT REFERENCES interpretations(id),
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS documents (
                        id TEXT PRIMARY KEY,
                        project TEXT NOT NULL REFERENCES projects(name),
                        path TEXT NOT NULL,
                        content TEXT NOT NULL,
                        content_hash TEXT NOT NULL,
                        status TEXT NOT NULL,
                        reviewed_at TEXT,
                        owner TEXT,
                        indexed_at TEXT NOT NULL,
                        UNIQUE(project, path)
                    );
                    CREATE TABLE IF NOT EXISTS parse_cache (
                        key TEXT PRIMARY KEY,
                        revision TEXT NOT NULL,
                        value_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        accessed_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS parse_cache_lru ON parse_cache(accessed_at);
                    CREATE TABLE IF NOT EXISTS audit_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        action TEXT NOT NULL,
                        object_type TEXT NOT NULL,
                        object_id TEXT NOT NULL,
                        details_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    PRAGMA user_version=2;
                    COMMIT;
                    """
                )
            elif version == 1:
                connection.execute("BEGIN IMMEDIATE")
                # Another initializer may have completed this migration while
                # this connection waited for the write lock.
                locked_version = connection.execute("PRAGMA user_version").fetchone()[0]
                if locked_version == 1:
                    connection.execute("ALTER TABLE documents ADD COLUMN content TEXT NOT NULL DEFAULT ''")
                    connection.execute("PRAGMA user_version=2")
                connection.commit()
            for attempt in range(6):
                try:
                    connection.execute("PRAGMA journal_mode=WAL")
                    break
                except sqlite3.OperationalError as error:
                    if "locked" not in str(error).lower() or attempt == 5:
                        raise
                    time.sleep(0.05 * (attempt + 1))

    @staticmethod
    def revision(context: Mapping[str, Any]) -> str:
        """Return a deterministic cache/context revision."""
        return _sha(_json({"schema": SCHEMA_VERSION, "context": context}))

    @staticmethod
    def profile_scope(
        profile: str,
        profile_version: str,
        *,
        context: Mapping[str, Any] | None = None,
        versions: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return matching, explicit profile metadata for memory operations."""
        if not isinstance(profile, str) or not profile.strip():
            raise ValueError("profile must be a nonempty string")
        if not isinstance(profile_version, str) or not profile_version.strip():
            raise ValueError("profile_version must be a nonempty string")
        scoped_context = dict(context or {})
        scoped_versions = dict(versions or {})
        for mapping in (scoped_context, scoped_versions):
            existing_profile = mapping.get("profile", profile)
            existing_version = mapping.get("profile_version", profile_version)
            if existing_profile != profile or existing_version != profile_version:
                raise ValueError("existing profile metadata conflicts with the requested profile scope")
            mapping["profile"] = profile
            mapping["profile_version"] = profile_version
        return scoped_context, scoped_versions

    @staticmethod
    def profile_cache_key(
        source: str,
        context: Mapping[str, Any],
        versions: Mapping[str, Any],
        *,
        options: Mapping[str, Any] | None = None,
        memory_revision: str | None = None,
    ) -> str:
        """Build a cache key that requires a complete profile partition."""
        if _profile_pair(context, versions) is None:
            raise ValueError("profile-aware cache keys require profile metadata")
        return _sha(_json({
            "schema": SCHEMA_VERSION,
            "source_hash": _sha(source),
            "context": context,
            "versions": versions,
            "options": options or {},
            "memory_revision": memory_revision,
        }))

    def _project(self, connection: sqlite3.Connection, project: str) -> str:
        project = project.strip()
        if not project:
            raise ValueError("project must not be empty")
        connection.execute(
            "INSERT OR IGNORE INTO projects(name,created_at) VALUES (?,?)",
            (project, _now()),
        )
        return project

    def _audit(self, connection: sqlite3.Connection, action: str, kind: str, object_id: str, details: Any) -> None:
        connection.execute(
            "INSERT INTO audit_log(action,object_type,object_id,details_json,created_at) VALUES (?,?,?,?,?)",
            (action, kind, object_id, _json(details), _now()),
        )

    def record_submission(self, source: str, project: str, pipeline: str, result: Any) -> str:
        """Persist every submitted prose and outcome, including failures."""
        if not isinstance(source, str):
            raise TypeError("source must be a string")
        if not pipeline.strip():
            raise ValueError("pipeline must not be empty")
        submission_id = uuid4().hex
        with self._connection() as connection:
            project = self._project(connection, project)
            connection.execute(
                """INSERT INTO submissions
                   (id,source,source_hash,normalized_source,project,pipeline,result_json,created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (submission_id, source, _sha(source), _normalized(source), project, pipeline, _json(result), _now()),
            )
            self._audit(connection, "record", "submission", submission_id, {"project": project, "pipeline": pipeline})
        return submission_id

    def add_candidate(
        self,
        submission_id: str,
        meaning: Any,
        context: Mapping[str, Any],
        versions: Mapping[str, Any],
        *,
        project: str | None = None,
        scope: str = "project",
    ) -> str:
        _profile_pair(context, versions)
        if scope not in {"project", "global"}:
            raise ValueError("scope must be project or global")
        interpretation_id = uuid4().hex
        with self._connection() as connection:
            submission = connection.execute(
                "SELECT project,source_hash,normalized_source FROM submissions WHERE id=?", (submission_id,)
            ).fetchone()
            if submission is None:
                raise KeyError(f"Unknown submission {submission_id}")
            selected_project = project or submission["project"]
            self._project(connection, selected_project)
            connection.execute(
                """INSERT INTO interpretations
                   (id,submission_id,project,source_hash,normalized_source,meaning_json,context_json,
                    versions_json,scope,status,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,'candidate',?)""",
                (
                    interpretation_id, submission_id, selected_project, submission["source_hash"],
                    submission["normalized_source"], _json(meaning), _json(context), _json(versions), scope, _now(),
                ),
            )
            self._audit(connection, "add", "interpretation", interpretation_id, {"status": "candidate"})
        return interpretation_id

    def confirm(
        self,
        interpretation_id: str,
        reviewer: str,
        *,
        expected_revision: int | None = None,
        replace_existing: bool = False,
    ) -> int:
        reviewer = reviewer.strip()
        if not reviewer:
            raise ValueError("reviewer must not be empty")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status,revision,project,source_hash,context_json FROM interpretations WHERE id=?", (interpretation_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown interpretation {interpretation_id}")
            if row["status"] == "superseded":
                raise ValueError("A superseded interpretation cannot be confirmed")
            if expected_revision is not None and row["revision"] != expected_revision:
                raise RuntimeError("Interpretation changed during review")
            revision = row["revision"] + 1
            superseded: list[str] = []
            if replace_existing:
                existing = connection.execute(
                    """SELECT id,revision FROM interpretations
                       WHERE id<>? AND project=? AND source_hash=? AND context_json=? AND status='confirmed'""",
                    (interpretation_id, row["project"], row["source_hash"], row["context_json"]),
                ).fetchall()
                for previous in existing:
                    connection.execute(
                        """UPDATE interpretations SET status='superseded',superseded_by=?,reviewer=?,reviewed_at=?,revision=?
                           WHERE id=?""",
                        (interpretation_id, reviewer, _now(), previous["revision"] + 1, previous["id"]),
                    )
                    superseded.append(previous["id"])
            connection.execute(
                "UPDATE interpretations SET status='confirmed',reviewer=?,reviewed_at=?,revision=? WHERE id=?",
                (reviewer, _now(), revision, interpretation_id),
            )
            self._audit(
                connection,
                "confirm",
                "interpretation",
                interpretation_id,
                {"reviewer": reviewer, "replace_existing": replace_existing, "superseded": superseded},
            )
        return revision

    def supersede(self, interpretation_id: str, *, successor_id: str | None = None, reviewer: str = "system") -> int:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT revision FROM interpretations WHERE id=?", (interpretation_id,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown interpretation {interpretation_id}")
            if successor_id is not None and connection.execute(
                "SELECT 1 FROM interpretations WHERE id=?", (successor_id,)
            ).fetchone() is None:
                raise KeyError(f"Unknown successor {successor_id}")
            revision = row["revision"] + 1
            connection.execute(
                "UPDATE interpretations SET status='superseded',superseded_by=?,reviewer=?,reviewed_at=?,revision=? WHERE id=?",
                (successor_id, reviewer, _now(), revision, interpretation_id),
            )
            self._audit(connection, "supersede", "interpretation", interpretation_id, {"successor_id": successor_id})
        return revision

    def lookup_confirmed(
        self, source: str, context: Mapping[str, Any], versions: Mapping[str, Any], *, project: str | None = None
    ) -> list[dict[str, Any]]:
        """Return byte-exact, context/version-compatible meanings."""
        _profile_pair(context, versions)
        parameters: list[Any] = [_sha(source), _json(context), _json(versions)]
        project_clause = "scope='global'"
        if project is not None:
            project_clause = "(scope='global' OR project=?)"
            parameters.append(project)
        with self._connection() as connection:
            rows = connection.execute(
                f"""SELECT * FROM interpretations
                    WHERE source_hash=? AND context_json=? AND versions_json=?
                      AND status='confirmed' AND {project_clause}
                    ORDER BY created_at,id""",
                parameters,
            ).fetchall()
        return [self._interpretation(row) for row in rows]

    def lookup_candidates(
        self, source: str, context: Mapping[str, Any], versions: Mapping[str, Any], *, project: str | None = None
    ) -> list[dict[str, Any]]:
        """Return normalized matches for clarification only, never compilation."""
        _profile_pair(context, versions)
        parameters: list[Any] = [_normalized(source), _json(context), _json(versions)]
        project_clause = "scope='global'"
        if project is not None:
            project_clause = "(scope='global' OR project=?)"
            parameters.append(project)
        with self._connection() as connection:
            rows = connection.execute(
                f"""SELECT * FROM interpretations
                    WHERE normalized_source=? AND context_json=? AND versions_json=?
                      AND status IN ('candidate','confirmed') AND {project_clause}
                    ORDER BY CASE status WHEN 'confirmed' THEN 0 ELSE 1 END,created_at,id""",
                parameters,
            ).fetchall()
        return [self._interpretation(row) for row in rows]

    def lookup_related(
        self, source: str, context: Mapping[str, Any], *, project: str | None = None
    ) -> list[dict[str, Any]]:
        """Return byte-exact candidate/confirmed meanings across versions.

        Callers use this only to explain stale meanings or ask clarification;
        compilation reuse remains restricted to ``lookup_confirmed``.
        """
        _profile_pair(context)
        parameters: list[Any] = [_sha(source), _json(context)]
        project_clause = "scope='global'"
        if project is not None:
            project_clause = "(scope='global' OR project=?)"
            parameters.append(project)
        with self._connection() as connection:
            rows = connection.execute(
                f"""SELECT * FROM interpretations
                    WHERE source_hash=? AND context_json=?
                      AND status IN ('candidate','confirmed') AND {project_clause}
                    ORDER BY CASE status WHEN 'confirmed' THEN 0 ELSE 1 END,created_at,id""",
                parameters,
            ).fetchall()
        return [self._interpretation(row) for row in rows]

    def memory_revision(self, project: str, context: Mapping[str, Any]) -> str:
        """Hash compatible confirmed IDs/revisions for cache invalidation."""
        _profile_pair(context)
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT id,revision,versions_json FROM interpretations
                   WHERE status='confirmed' AND context_json=? AND (scope='global' OR project=?)
                   ORDER BY id""",
                (_json(context), project),
            ).fetchall()
        return _sha(_json({
            "schema": SCHEMA_VERSION,
            "project": project,
            "context": context,
            "confirmed": [(row["id"], row["revision"], row["versions_json"]) for row in rows],
        }))

    def record_clarification(
        self, submission_id: str, question: str, answer: str, *, interpretation_id: str | None = None
    ) -> str:
        clarification_id = uuid4().hex
        with self._connection() as connection:
            if connection.execute("SELECT 1 FROM submissions WHERE id=?", (submission_id,)).fetchone() is None:
                raise KeyError(f"Unknown submission {submission_id}")
            connection.execute(
                "INSERT INTO clarification_history VALUES (?,?,?,?,?,?)",
                (clarification_id, submission_id, question, answer, interpretation_id, _now()),
            )
            self._audit(connection, "answer", "clarification", clarification_id, {"submission_id": submission_id})
        return clarification_id

    def clarification_history(self, submission_id: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM clarification_history WHERE submission_id=? ORDER BY created_at,id", (submission_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def index_document(
        self, project: str, path: str, content: str, *, status: str, reviewed_at: str | None = None, owner: str | None = None
    ) -> str:
        if not isinstance(content, str):
            raise TypeError("document content must be a string")
        if len(content) > MAX_DOCUMENT_CHARS:
            raise ValueError(f"document content exceeds {MAX_DOCUMENT_CHARS} characters")
        document_id = _sha(f"{project}\0{path}")
        with self._connection() as connection:
            project = self._project(connection, project)
            connection.execute(
                """INSERT INTO documents(id,project,path,content,content_hash,status,reviewed_at,owner,indexed_at)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(project,path) DO UPDATE SET content=excluded.content,content_hash=excluded.content_hash,
                       status=excluded.status,reviewed_at=excluded.reviewed_at,owner=excluded.owner,indexed_at=excluded.indexed_at""",
                (document_id, project, path, content, _sha(content), status, reviewed_at, owner, _now()),
            )
        return document_id

    def get_cache(self, key: str, *, revision: str | None = None) -> Any | None:
        with self._connection() as connection:
            row = connection.execute("SELECT revision,value_json FROM parse_cache WHERE key=?", (key,)).fetchone()
            if row is None or (revision is not None and row["revision"] != revision):
                return None
            connection.execute("UPDATE parse_cache SET accessed_at=? WHERE key=?", (_now(), key))
        return _object(row["value_json"])

    def put_cache(self, key: str, value: Any, *, revision: str = "1") -> None:
        now = _now()
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO parse_cache(key,revision,value_json,created_at,accessed_at) VALUES (?,?,?,?,?)
                   ON CONFLICT(key) DO UPDATE SET revision=excluded.revision,value_json=excluded.value_json,
                       created_at=excluded.created_at,accessed_at=excluded.accessed_at""",
                (key, revision, _json(value), now, now),
            )
            connection.execute(
                """DELETE FROM parse_cache WHERE key IN
                   (SELECT key FROM parse_cache ORDER BY accessed_at DESC,key DESC LIMIT -1 OFFSET ?)""",
                (self.cache_limit,),
            )

    def clear_cache(self) -> int:
        with self._connection() as connection:
            count = connection.execute("SELECT count(*) FROM parse_cache").fetchone()[0]
            connection.execute("DELETE FROM parse_cache")
        return count

    def search(self, query: str, *, project: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        terms = query.casefold().split()
        if not terms or limit < 1:
            raise ValueError("query and positive limit are required")
        submission_clauses = ["normalized_source LIKE ?" for _ in terms]
        submission_parameters: list[Any] = [f"%{term}%" for term in terms]
        document_clauses = ["lower(content) LIKE ?" for _ in terms]
        document_parameters: list[Any] = [f"%{term}%" for term in terms]
        if project is not None:
            submission_clauses.append("project=?")
            submission_parameters.append(project)
            document_clauses.append("project=?")
            document_parameters.append(project)
        with self._connection() as connection:
            submissions = connection.execute(
                f"SELECT id,project,pipeline,source,result_json,created_at FROM submissions WHERE {' AND '.join(submission_clauses)} ORDER BY created_at DESC,id LIMIT ?",
                [*submission_parameters, limit],
            ).fetchall()
            documents = connection.execute(
                f"SELECT id,project,path,content,status,indexed_at FROM documents WHERE {' AND '.join(document_clauses)} ORDER BY indexed_at DESC,id LIMIT ?",
                [*document_parameters, limit],
            ).fetchall()
        results = [
            {**dict(row), "kind": "submission", "result": _object(row["result_json"])} for row in submissions
        ]
        results.extend({**dict(row), "kind": "document"} for row in documents)
        results.sort(key=lambda row: (row.get("created_at") or row.get("indexed_at") or "", row["id"]), reverse=True)
        return results[:limit]

    def inspect(self, kind: str, object_id: str) -> dict[str, Any] | None:
        tables = {"submission": "submissions", "interpretation": "interpretations", "document": "documents"}
        if kind not in tables:
            raise ValueError("kind must be submission, interpretation, or document")
        with self._connection() as connection:
            row = connection.execute(f"SELECT * FROM {tables[kind]} WHERE id=?", (object_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        for key in tuple(result):
            if key.endswith("_json"):
                result[key[:-5]] = _object(result.pop(key))
        return result

    def export_data(self, destination: str | os.PathLike[str]) -> Path:
        destination = Path(destination)
        with self._connection() as connection:
            payload = {
                "format": "shipmb-memory",
                "schema_version": SCHEMA_VERSION,
                "projects": [dict(row) for row in connection.execute("SELECT * FROM projects ORDER BY name")],
                "submissions": [dict(row) for row in connection.execute("SELECT * FROM submissions ORDER BY created_at,id")],
                "interpretations": [dict(row) for row in connection.execute("SELECT * FROM interpretations ORDER BY created_at,id")],
                "clarification_history": [dict(row) for row in connection.execute("SELECT * FROM clarification_history ORDER BY created_at,id")],
                "documents": [dict(row) for row in connection.execute("SELECT * FROM documents ORDER BY project,path")],
            }
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return destination

    def import_data(self, source: str | os.PathLike[str]) -> dict[str, int]:
        payload = json.loads(Path(source).read_text(encoding="utf-8"))
        if payload.get("format") != "shipmb-memory" or payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("Unsupported memory export")
        counts = {"submissions": 0, "interpretations": 0, "clarification_history": 0, "documents": 0}
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for row in payload.get("projects", []):
                connection.execute("INSERT OR IGNORE INTO projects(name,created_at) VALUES (?,?)", (row["name"], row["created_at"]))
            for table in counts:
                for row in payload.get(table, []):
                    row = dict(row)
                    if table == "interpretations":
                        # Imported interpretations always require local review.
                        row.update(status="candidate", reviewer=None, reviewed_at=None, superseded_by=None)
                    columns = list(row)
                    placeholders = ",".join("?" for _ in columns)
                    cursor = connection.execute(
                        f"INSERT OR IGNORE INTO {table}({','.join(columns)}) VALUES ({placeholders})",
                        [row[column] for column in columns],
                    )
                    counts[table] += cursor.rowcount
            self._audit(connection, "import", "memory", str(source), counts)
        return counts

    def backup(self, destination: str | os.PathLike[str]) -> Path:
        destination = Path(destination).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".tmp")
        if temporary.exists():
            temporary.unlink()
        source = self._connect()
        target = sqlite3.connect(temporary)
        try:
            source.backup(target)
            target.execute("DELETE FROM parse_cache")
            target.commit()
        finally:
            target.close()
            source.close()
        os.replace(temporary, destination)
        return destination

    @staticmethod
    def _interpretation(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        for key in ("meaning_json", "context_json", "versions_json"):
            result[key[:-5]] = _object(result.pop(key))
        return result
