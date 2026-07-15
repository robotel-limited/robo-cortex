"""Transfer operations: export, import, merge of knowledge bases."""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from robo_cortex.core.errors import ValidationError
from robo_cortex.core.memory import _MEMORY_COLUMNS, validate_memory_fields


@dataclass
class ImportResult:
    imported: int = 0
    skipped: int = 0
    warnings: list = field(default_factory=list)
    duplicates: list = field(default_factory=list)


@dataclass
class MergeResult:
    file1_count: int = 0
    file2_count: int = 0
    conflict_count: int = 0
    total: int = 0
    conflicts: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def export_memories(conn, scope: str) -> list[dict]:
    """Export memories from store, return as list of dicts (no output)."""
    query = "SELECT {} FROM memory WHERE scope = ?".format(
        ", ".join(_MEMORY_COLUMNS)
    )
    cursor = conn.execute(query, (scope,))
    rows = cursor.fetchall()
    memories = [dict(zip(_MEMORY_COLUMNS, row)) for row in rows]
    return memories


def _confidence_rank(conf: str) -> int:
    """Rank confidence levels for conflict resolution."""
    ranks = {"high": 3, "medium": 2, "low": 1}
    return ranks.get(conf, 0)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def import_memories(repo_conn_cm, global_conn_cm, input_path: str) -> ImportResult:
    """
    Import memories from JSONL file.

    Args:
        repo_conn_cm: zero-arg callable returning a context manager that
            yields a connection to the repo-scope store.
        global_conn_cm: zero-arg callable returning a context manager that
            yields a connection to the global-scope store.
        input_path: path to JSONL file

    Two separate factories rather than one `conn_selector(scope)` callable:
    there is no scope-keyed branching inside this function that could route
    a "repo" request to the wrong connection type -- each factory is
    pre-bound by the caller to the correct store, so the connection-vs-tuple
    mismatch that used to crash `roco import --repo` (a `_store()` 2-tuple
    unpacked where a bare connection was expected) cannot recur here: there
    is no code path left that could pick the wrong one.

    Validates every line through the same `validate_memory_fields` that
    `record_memory` uses -- import is not a backdoor around record's rules
    (in particular: scope='global' without assumptions is rejected here
    too, not silently inserted).
    """
    result = ImportResult()
    global_memories = []
    repo_memories = []

    with open(input_path, "r") as f:
        for line_num, line in enumerate(f, 1):
            if not line.strip():
                continue

            try:
                mem = json.loads(line)
            except json.JSONDecodeError:
                result.warnings.append(f"Line {line_num}: Invalid JSON")
                result.skipped += 1
                continue

            if not all(k in mem for k in ["type", "scope", "statement", "confidence"]):
                result.warnings.append(
                    f"Line {line_num}: Missing required fields (type, scope, statement, confidence)"
                )
                result.skipped += 1
                continue

            try:
                validate_memory_fields(
                    mem.get("type"), mem.get("scope"), mem.get("statement"),
                    mem.get("confidence"), mem.get("why_it_matters"), mem.get("assumptions"),
                )
            except ValidationError as error:
                result.warnings.append(f"Line {line_num}: {error}")
                result.skipped += 1
                continue

            mem = dict(mem)
            mem.setdefault("status", "provisional")
            mem.setdefault("created_by", "imported")
            mem["created_at"] = mem.get("created_at") or _now_iso()
            mem["last_verified_at"] = mem.get("last_verified_at") or mem["created_at"]

            if mem["scope"] == "global":
                global_memories.append((line_num, mem))
            else:
                repo_memories.append((line_num, mem))

    def _insert_memories(conn, mems):
        for line_num, mem in mems:
            cursor = conn.execute(
                "SELECT id FROM memory WHERE id = ? AND scope = ?",
                (mem.get("id"), mem.get("scope"))
            )
            if cursor.fetchone():
                result.duplicates.append(
                    f"Memory ID {mem.get('id')} ({mem.get('scope')}) already exists, skipping"
                )
                result.skipped += 1
                continue

            conn.execute(
                """INSERT INTO memory
                   (id, type, scope, statement, why_it_matters, assumptions,
                    status, status_reason, confidence, created_at, last_verified_at, created_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    mem.get("id"),
                    mem.get("type"),
                    mem.get("scope"),
                    mem.get("statement"),
                    mem.get("why_it_matters"),
                    mem.get("assumptions"),
                    mem.get("status"),
                    mem.get("status_reason"),
                    mem.get("confidence"),
                    mem.get("created_at"),
                    mem.get("last_verified_at"),
                    mem.get("created_by"),
                )
            )
            result.imported += 1

    if global_memories:
        with global_conn_cm() as conn:
            _insert_memories(conn, global_memories)
            conn.commit()

    if repo_memories:
        with repo_conn_cm() as conn:
            _insert_memories(conn, repo_memories)
            conn.commit()

    return result


def merge_jsonl(file1: str, file2: str) -> tuple[dict, MergeResult]:
    """
    Merge two JSONL knowledge bases, de-duplicating by ID+scope.

    Returns:
        (merged_memories_dict, MergeResult with statistics)
    """
    result = MergeResult()
    memories = {}  # key: (id, scope), value: memory dict

    # Read file 1
    with open(file1, "r") as f:
        for line_num, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                mem = json.loads(line)
                if not all(k in mem for k in ["id", "scope"]):
                    result.warnings.append(f"{file1}:{line_num}: Missing id/scope")
                    continue
                key = (mem["id"], mem["scope"])
                memories[key] = mem
                result.file1_count += 1
            except json.JSONDecodeError:
                result.warnings.append(f"{file1}:{line_num}: Invalid JSON")

    # Read file 2, resolve conflicts
    with open(file2, "r") as f:
        for line_num, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                mem = json.loads(line)
                if not all(k in mem for k in ["id", "scope"]):
                    result.warnings.append(f"{file2}:{line_num}: Missing id/scope")
                    continue
                key = (mem["id"], mem["scope"])

                if key in memories:
                    # Conflict: pick winner by confidence, then by created_at.
                    # Message format matches EXPORT_IMPORT.md's documented
                    # examples ("picked high over medium" / "confidence tie,
                    # picked new") -- always phrased from the winner's side.
                    existing = memories[key]
                    new_conf = mem.get("confidence", "low")
                    existing_conf = existing.get("confidence", "low")
                    new_rank = _confidence_rank(new_conf)
                    existing_rank = _confidence_rank(existing_conf)

                    conflict_info = {"id": mem["id"], "scope": mem["scope"]}

                    if new_rank > existing_rank:
                        memories[key] = mem
                        conflict_info["winner"] = "new"
                        conflict_info["reason"] = f"picked {new_conf} over {existing_conf}"
                    elif new_rank == existing_rank:
                        existing_ts = existing.get("created_at", "")
                        new_ts = mem.get("created_at", "")
                        if new_ts > existing_ts:
                            memories[key] = mem
                            conflict_info["winner"] = "new"
                            conflict_info["reason"] = "confidence tie, picked new"
                        else:
                            conflict_info["winner"] = "existing"
                            conflict_info["reason"] = "confidence tie, picked existing"
                    else:
                        conflict_info["winner"] = "existing"
                        conflict_info["reason"] = f"picked {existing_conf} over {new_conf}"

                    result.conflict_count += 1
                    result.conflicts.append(conflict_info)
                else:
                    memories[key] = mem
                    result.file2_count += 1

            except json.JSONDecodeError:
                result.warnings.append(f"{file2}:{line_num}: Invalid JSON")

    result.total = len(memories)

    return memories, result
