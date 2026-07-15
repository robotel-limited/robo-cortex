"""Commands: roco export, import, merge"""

import json
import sys

from robo_cortex.core.transfer import export_memories, import_memories, merge_jsonl
from robo_cortex.core.memory import _MEMORY_COLUMNS
from robo_cortex.cli._common import _get_cmd_name, _store, _store_conn, _global_store, cli_command


@cli_command("export")
def run_export(args) -> int:
    """Export memories to JSONL format (portable, mergeable)."""
    if args.scope == "global":
        with _global_store() as conn:
            memories = export_memories(conn, args.scope)
    else:
        with _store(args.repo) as (repo_root, conn):
            memories = export_memories(conn, args.scope)

    output_file = args.output if args.output else sys.stdout
    if isinstance(output_file, str):
        with open(output_file, "w") as f:
            for mem in memories:
                json.dump(mem, f, default=str)
                f.write("\n")
        print(f"✅ Exported {len(memories)} {args.scope}-scoped memories to {args.output}")
    else:
        for mem in memories:
            json.dump(mem, output_file, default=str)
            output_file.write("\n")
        print(f"✅ Exported {len(memories)} {args.scope}-scoped memories", file=sys.stderr)

    return 0


@cli_command("import")
def run_import(args) -> int:
    """Import memories from JSONL file."""
    def repo_conn_cm():
        return _store_conn(args.repo)

    result = import_memories(repo_conn_cm, _global_store, args.input)

    for duplicate in result.duplicates:
        print(f"  ℹ️  {duplicate}")
    for warning in result.warnings:
        print(f"  ⚠️  {warning}")

    print(f"\n✅ Import complete:")
    print(f"   ✓ Imported: {result.imported} memories")
    if result.skipped > 0:
        print(f"   ⊘ Skipped: {result.skipped}")

    return 0


@cli_command("merge")
def run_merge(args) -> int:
    """Merge two JSONL knowledge bases, de-duplicating by ID+scope."""
    memories, result = merge_jsonl(args.file1, args.file2)

    # Write merged output
    with open(args.output, "w") as f:
        for mem in memories.values():
            json.dump(mem, f, default=str)
            f.write("\n")

    for conflict in result.conflicts:
        print(
            f"  🔄 Conflict at ID {conflict['id']} ({conflict['scope']}): "
            f"{conflict['reason']}"
        )

    for warning in result.warnings:
        print(f"  ⚠️  {warning}")

    print(f"\n✅ Merge complete:")
    print(f"   From {args.file1}: {result.file1_count} memories")
    print(f"   From {args.file2}: {result.file2_count} new memories")
    if result.conflict_count > 0:
        print(f"   Conflicts resolved: {result.conflict_count}")
    print(f"   Total merged: {result.total} unique memories")
    print(f"   Output: {args.output}")

    return 0


def register(subparsers):
    # export
    p_export = subparsers.add_parser("export", help="Export memories to JSONL")
    p_export.add_argument(
        "--repo",
        default=None,
        help="Path inside the target repository (required if exporting repo scope and not in a git tree)",
    )
    p_export.add_argument(
        "--scope",
        choices=["global", "repo"],
        default="global",
        help="Memory scope to export (default: global)",
    )
    p_export.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output file (default: stdout)",
    )
    p_export.set_defaults(func=run_export)

    # import
    p_import = subparsers.add_parser("import", help="Import memories from JSONL")
    p_import.add_argument(
        "--repo",
        default=None,
        help="Path inside the target repository (required if importing repo scope and not in a git tree)",
    )
    p_import.add_argument(
        "input",
        help="Input JSONL file to import from",
    )
    p_import.set_defaults(func=run_import)

    # merge
    p_merge = subparsers.add_parser("merge", help="Merge two JSONL knowledge bases")
    p_merge.add_argument(
        "file1",
        help="First JSONL file",
    )
    p_merge.add_argument(
        "file2",
        help="Second JSONL file",
    )
    p_merge.add_argument(
        "--output",
        "-o",
        required=True,
        help="Output merged JSONL file",
    )
    p_merge.set_defaults(func=run_merge)
