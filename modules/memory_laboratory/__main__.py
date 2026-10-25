"""python -m modules.memory_laboratory [--env-file .env] [--apply]."""
import argparse
import json

from .setup import Config, DedicatedEmbedder, QdrantSetup


def main():
    parser = argparse.ArgumentParser(description="Non-destructive Memory Laboratory setup")
    parser.add_argument("--env-file", help="Explicit local dotenv file; never printed")
    parser.add_argument("--apply", action="store_true", help="Create missing versioned collections/indexes and verify write/read/delete permissions")
    parser.add_argument("--embedding-only", action="store_true", help="Probe the real dedicated embedding model without contacting Qdrant")
    args = parser.parse_args()
    if args.env_file:
        from pathlib import Path
        if not Path(args.env_file).is_file():
            parser.error("environment file does not exist")
        from dotenv import load_dotenv
        load_dotenv(args.env_file, override=False)
    setup = None
    try:
        config = Config.from_env()
        if args.embedding_only:
            vector = DedicatedEmbedder(config).embed("Niblit dedicated embedding probe")
            report = {"ready": True, "scope": "embedding_only", "model": config.model,
                      "revision": config.revision, "dimension": len(vector)}
        else:
            setup = QdrantSetup(config)
            report = setup.run(apply=args.apply)
    except Exception as exc:
        report = {"ready": False, "issues": [type(exc).__name__]}
    finally:
        if setup:
            setup.close()
    print(json.dumps(report, indent=2))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
