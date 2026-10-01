"""Offline administration: password hashes and emergency OAuth revocation."""
import argparse
import getpass
import os

from argon2 import PasswordHasher
from oauth_store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["hash-password", "revoke-all"])
    parser.add_argument("--database", default=os.environ.get("MCP_OAUTH_DATABASE", "data/oauth.sqlite3"))
    args = parser.parse_args()
    if args.command == "hash-password":
        password = getpass.getpass("OAuth password (at least 16 characters): ")
        if len(password) < 16 or password != getpass.getpass("Repeat password: "):
            parser.error("Passwords must match and contain at least 16 characters")
        print(PasswordHasher().hash(password))
    else:
        store = Store(args.database)
        with store.transaction():
            store.execute("UPDATE tokens SET revoked=1")
            store.execute("UPDATE codes SET used=1")
            store.execute("DELETE FROM pending")
        store.close()
        print("All OAuth grants revoked. The separately configured legacy bearer token is unchanged.")


if __name__ == "__main__":
    main()
