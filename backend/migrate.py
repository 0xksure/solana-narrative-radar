"""Run database migrations."""
import os
from yoyo import read_migrations, get_backend

DATABASE_URL = os.environ.get("DATABASE_URL", "")


def run_migrations():
    if not DATABASE_URL:
        print("No DATABASE_URL set, skipping migrations")
        return
    backend = get_backend(DATABASE_URL)
    migrations = read_migrations(os.path.join(os.path.dirname(__file__), "migrations"))
    with backend.lock():
        backend.apply_migrations(backend.to_apply(migrations))
    print("Migrations applied successfully")


def rollback_last():
    if not DATABASE_URL:
        return
    backend = get_backend(DATABASE_URL)
    migrations = read_migrations(os.path.join(os.path.dirname(__file__), "migrations"))
    with backend.lock():
        backend.rollback_one(backend.to_rollback(migrations))
    print("Rolled back last migration")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "rollback":
        rollback_last()
    else:
        run_migrations()
