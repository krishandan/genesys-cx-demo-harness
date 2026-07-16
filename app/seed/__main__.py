"""CLI: python -m app.seed --tenant northwind"""

import argparse
import json
import sys

from app.db import SessionLocal
from app.logging import configure_logging
from app.seed.generator import PackNotFoundError, seed_tenant


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.seed", description="Seed a tenant pack.")
    parser.add_argument(
        "--tenant",
        required=True,
        help="Tenant slug; must match a directory under app/seed/packs/.",
    )
    args = parser.parse_args(argv)

    configure_logging()

    try:
        with SessionLocal() as db:
            result = seed_tenant(db, args.tenant)
    except PackNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result.as_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
