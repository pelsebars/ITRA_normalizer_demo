#!/usr/bin/env python3
from itra_normalizer.config import get_settings
from itra_normalizer.db import connect, ingest_fixtures


def main() -> None:
    settings = get_settings()
    connection = connect(settings.db_path)
    count = ingest_fixtures(connection)
    print(f"Ingested {count} site fixtures into {settings.db_path}")


if __name__ == "__main__":
    main()
