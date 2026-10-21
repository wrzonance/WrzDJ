"""Create a DJ user from the command line."""

import argparse

from app.db.session import SessionLocal
from app.services.auth import create_user, get_user_by_username


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a DJ user")
    parser.add_argument("--username", required=True, help="Username for the DJ")
    parser.add_argument("--password", required=True, help="Password for the DJ")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        existing = get_user_by_username(db, args.username)
        if existing:
            print(f"User '{args.username}' already exists.")
            return 1

        user = create_user(db, args.username, args.password)
        print(f"Created user '{user.username}' with ID {user.id}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
