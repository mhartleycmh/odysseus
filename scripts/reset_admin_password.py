"""Reset a local Odysseus user's password without printing it."""

from __future__ import annotations

import getpass
import json
import os
import tempfile
from pathlib import Path

import bcrypt


BASE_DIR = Path(__file__).resolve().parents[1]
AUTH_FILE = Path(os.environ.get("ODYSSEUS_DATA_DIR", BASE_DIR / "data")) / "auth.json"
MIN_LENGTH = 8


def main() -> None:
    if not AUTH_FILE.exists():
        raise SystemExit(f"Authentication file not found: {AUTH_FILE}")

    data = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    users = data.get("users")
    if not isinstance(users, dict) or not users:
        raise SystemExit("No users found in the authentication file.")

    username = input("Username [admin]: ").strip().lower() or "admin"
    if username not in users:
        raise SystemExit(f"User not found: {username}")

    password = getpass.getpass("New password: ")
    confirmation = getpass.getpass("Confirm new password: ")
    if len(password) < MIN_LENGTH:
        raise SystemExit(f"Password must be at least {MIN_LENGTH} characters.")
    if password != confirmation:
        raise SystemExit("Passwords do not match.")

    users[username]["password_hash"] = bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")

    fd, temporary_name = tempfile.mkstemp(
        prefix="auth-", suffix=".json", dir=str(AUTH_FILE.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as temporary:
            json.dump(data, temporary, indent=2)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, AUTH_FILE)
    finally:
        temporary_path = Path(temporary_name)
        if temporary_path.exists():
            temporary_path.unlink()

    print(f"Password updated for {username}. Restart Odysseus before signing in.")


if __name__ == "__main__":
    main()
