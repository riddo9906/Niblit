"""Operator-only CLI. This is not registered as an assistant tool."""
import argparse
import json
import os
from pathlib import Path

from dotenv import dotenv_values

from .gateway import MemoryGateway
from .setup import Config


def main():
    parser = argparse.ArgumentParser(description="Governed Memory Laboratory operator")
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--namespace", default="desktop")
    parser.add_argument("--principal", default="desktop_operator")
    commands = parser.add_subparsers(dest="command", required=True)
    grant = commands.add_parser("grant")
    grant.add_argument("actions", nargs="+", choices=["read", "ingest", "delete", "consolidate"])
    grant.add_argument("--confirm", action="store_true", required=True)
    ingest = commands.add_parser("ingest")
    ingest.add_argument("path", help="Relative file within NIBLIT_WORKSPACE_ROOT")
    recall = commands.add_parser("retrieve")
    recall.add_argument("query")
    migrate = commands.add_parser("migrate")
    migrate.add_argument("source")
    migrate.add_argument("--format", choices=["knowledge-json", "laboratory-jsonl"], required=True)
    migrate.add_argument("--apply", action="store_true")
    migrate.add_argument("--backup-dir")
    rollback = commands.add_parser("rollback")
    rollback.add_argument("manifest")
    commands.add_parser("consolidate")
    args = parser.parse_args()
    values = dotenv_values(args.env_file)
    config = Config.from_values(values)
    if args.command == "grant":
        # Explicit operator confirmation updates the EXISTING permission store.
        # It does not grant tools run/code execution/model-write authority.
        from modules.core_tool_runtime import _permission_manager
        manager = _permission_manager()
        for action in args.actions:
            manager.perms[f"memory.{action}.{args.namespace}"] = True
        manager.save()
        print(json.dumps({"granted": args.actions, "namespace": args.namespace}))
        return 0
    g = MemoryGateway(config, args.ledger)
    try:
        scope = {"namespace": args.namespace, "principal": args.principal}
        if args.command == "ingest":
            result = g.ingest_file(args.path, **scope)
        elif args.command == "retrieve":
            result = g.retrieve(args.query, **scope)
        elif args.command == "consolidate":
            from .consolidation import Consolidator
            result = Consolidator(g, **scope).tick()
        elif args.command == "migrate":
            from .migration import plan, apply
            result = plan(args.source, format=args.format, **scope)
            if args.apply:
                if not args.backup_dir:
                    parser.error("--backup-dir is required for apply")
                result = apply(g, result, args.backup_dir)
            else:
                # Counts and hashes only: do not dump private facts to logs.
                result = {k: v for k, v in result.items() if k != "entries"} | {"records": len(result["entries"])}
        else:
            from .migration import rollback
            manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
            if (manifest["namespace"], manifest["principal"]) != (args.namespace, args.principal):
                parser.error("manifest scope does not match operator scope")
            result = rollback(g, manifest)
        print(json.dumps(result, indent=2))
    finally:
        g.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
