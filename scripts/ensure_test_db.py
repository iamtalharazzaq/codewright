"""Create the throwaway test database named in TEST_DATABASE_URL if it doesn't exist yet (used by `make check`)."""

import os
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql

url = os.environ["TEST_DATABASE_URL"]
parts = urlsplit(url)
name = parts.path.lstrip("/")
admin_url = urlunsplit(parts._replace(path="/postgres"))

with psycopg.connect(admin_url, autocommit=True) as conn:
    if conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone() is None:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        print(f"Created test database {name}")
