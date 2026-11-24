"""Open a PostgreSQL connection using the project's local settings."""

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv


def connect() -> psycopg.Connection:
    """Return a connection the caller is responsible for closing."""
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    return psycopg.connect(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"],
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        connect_timeout=5,
    )


if __name__ == "__main__":
    try:
        with connect() as connection:
            if connection.execute("SELECT 1").fetchone() != (1,):
                raise SystemExit("PostgreSQL baglanti testi beklenen sonucu vermedi.")
    except KeyError as error:
        raise SystemExit(f"Eksik baglanti ayari: {error.args[0]}") from None
    except (psycopg.Error, ValueError):
        raise SystemExit("PostgreSQL baglanti testi basarisiz.") from None
    print("PostgreSQL baglantisi basarili (SELECT 1).")
