"""Read-only authenticated Qdrant availability inspection; never changes collections."""
import argparse
import json
import sys
from pathlib import Path


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--env-file", type=Path, required=True)
    args = p.parse_args(argv)
    from dotenv import dotenv_values
    from qdrant_client import QdrantClient
    if not args.env_file.is_file():
        print(json.dumps({"state": "environment_file_unavailable", "ready": False}))
        return 2
    settings = dotenv_values(args.env_file)
    url = settings.get("QDRANT_URL")
    key = settings.get("QDRANT_API_KEY")
    if not url:
        print(json.dumps({"state": "missing_qdrant_url", "ready": False}))
        return 2
    try:
        client = QdrantClient(url=url, api_key=key or None, timeout=5)
        names = [c.name for c in client.get_collections().collections]
        print(json.dumps({"state": "authenticated_read_success", "ready": True,
                          "collections": names, "writes_attempted": 0}, indent=2))
        client.close()
        return 0
    except Exception as exc:
        print(json.dumps({"state": "read_failed", "ready": False,
                          "error_type": type(exc).__name__, "writes_attempted": 0}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
