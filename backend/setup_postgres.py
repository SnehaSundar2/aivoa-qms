"""Create the PostgreSQL role and database this project expects.

Run:  python setup_postgres.py

Prompts for your PostgreSQL superuser password, then creates:
    role      qms      (password: qms)
    database  qms_complaints  (owner: qms)

matching the default DATABASE_URL in app/core/config.py. Safe to re-run - it
skips anything that already exists.

This exists as a script rather than a README one-liner because CREATE DATABASE
cannot run inside a transaction, and because quoting a multi-statement SQL
one-liner through PowerShell is genuinely painful.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

ROLE = "qms"
ROLE_PASSWORD = "qms"
DATABASE = "qms_complaints"


def read_password(user: str) -> str:
    """Get the superuser password without hanging in a non-interactive shell.

    `getpass` reads the Windows console directly, so it blocks forever when
    stdin is a pipe. Preference order:
      1. PGPASSWORD, the standard libpq variable,
      2. a line on stdin when stdin is not a terminal (CI, piped input),
      3. an interactive prompt.
    """
    from_env = os.environ.get("PGPASSWORD")
    if from_env:
        print("Using the password from PGPASSWORD.")
        return from_env

    if not sys.stdin.isatty():
        line = sys.stdin.readline()
        if not line:
            print(
                "No password available: stdin is not a terminal and PGPASSWORD "
                "is not set.",
                file=sys.stderr,
            )
            sys.exit(1)
        return line.rstrip("\n")

    # The terminal shows nothing at all while you type - no asterisks, no
    # moving cursor. Say so, because otherwise it reads as a frozen prompt.
    print(f"\nPassword for PostgreSQL user '{user}'.")
    print("Your typing is hidden - no characters will appear. Type it and press Enter.")
    print("(Or press Ctrl+C and set $env:PGPASSWORD=\"...\" instead.)")
    return getpass.getpass("Password: ")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", default="5432")
    parser.add_argument(
        "--superuser",
        default="postgres",
        help="PostgreSQL superuser to connect as (default: postgres)",
    )
    args = parser.parse_args()

    try:
        import psycopg
    except ImportError:
        print("psycopg is not installed. Run: pip install -r requirements.txt")
        return 1

    password = read_password(args.superuser)

    dsn = (
        f"host={args.host} port={args.port} user={args.superuser} "
        f"password={password} dbname=postgres connect_timeout=10"
    )

    try:
        conn = psycopg.connect(dsn)
    except Exception as exc:  # noqa: BLE001
        print(f"\nCould not connect to PostgreSQL at {args.host}:{args.port}")
        print(f"  {type(exc).__name__}: {str(exc).strip()}")
        print("\nCheck that the server is running and the password is correct.")
        print("If your superuser is not 'postgres', pass --superuser <name>.")
        return 1

    # CREATE DATABASE cannot run inside a transaction block.
    conn.autocommit = True

    with conn:
        server_version = conn.execute("SELECT version()").fetchone()[0]
        print(f"\nConnected: {server_version.split(',')[0]}")

        # --- role ---
        exists = conn.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s", (ROLE,)
        ).fetchone()
        if exists:
            print(f"  role '{ROLE}' already exists - left unchanged")
        else:
            # Identifiers cannot be parameterised, but ROLE is a module
            # constant, not user input, so there is nothing to inject here.
            conn.execute(
                f"CREATE ROLE {ROLE} LOGIN PASSWORD %s", (ROLE_PASSWORD,)
            )
            print(f"  created role '{ROLE}'")

        # --- database ---
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (DATABASE,)
        ).fetchone()
        if exists:
            print(f"  database '{DATABASE}' already exists - left unchanged")
        else:
            conn.execute(f"CREATE DATABASE {DATABASE} OWNER {ROLE}")
            print(f"  created database '{DATABASE}' owned by '{ROLE}'")

    # --- prove the application's own credentials work ---
    app_dsn = (
        f"host={args.host} port={args.port} user={ROLE} password={ROLE_PASSWORD} "
        f"dbname={DATABASE} connect_timeout=10"
    )
    try:
        with psycopg.connect(app_dsn) as check:
            who = check.execute("SELECT current_user, current_database()").fetchone()
        print(f"\nVerified: connected as '{who[0]}' to '{who[1]}'.")
    except Exception as exc:  # noqa: BLE001
        print(f"\nRole and database exist, but connecting as '{ROLE}' failed:")
        print(f"  {type(exc).__name__}: {str(exc).strip()}")
        print(
            "\nThis is usually pg_hba.conf requiring a different auth method for "
            "local connections. Check the 'host all all 127.0.0.1/32' line."
        )
        return 1

    print("\nNext:")
    print("  python seed.py --reset")
    print("  python -m uvicorn app.main:app --reload")
    print("  curl http://localhost:8000/health      -> expect \"database\":\"postgresql\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
