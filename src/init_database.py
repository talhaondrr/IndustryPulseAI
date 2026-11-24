"""Apply the PostgreSQL schema in a single transaction."""

from pathlib import Path

import psycopg

if __package__:
    from .database import connect
else:
    from database import connect


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "sql" / "01_create_schema.sql"


def init_database() -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with connect() as connection:
        # Serialize simultaneous runs until the transaction ends.
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtext('industrypulseai:public:schema'))"
        )
        connection.execute(schema)


if __name__ == "__main__":
    try:
        init_database()
    except psycopg.Error as error:
        raise SystemExit(
            f"Şema uygulanamadı. PostgreSQL hata kodu: {error.sqlstate or 'yok'}."
        ) from None
    except (KeyError, ValueError, OSError):
        raise SystemExit("Bağlantı ayarları veya SQL dosyası okunamadı.") from None
    print("PostgreSQL şeması başarıyla uygulandı.")
