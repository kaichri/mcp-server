"""Container-local readiness check: both HTTP listeners and their shared database."""
from http.client import HTTPConnection, HTTPException


def healthy():
    try:
        for port, path, expected in [(8000, "/healthz", 200), (8001, "/mcp", 401)]:
            connection = HTTPConnection("127.0.0.1", port, timeout=2)
            try:
                connection.request("GET", path)
                response = connection.getresponse()
                if response.status != expected:
                    return False
                if port == 8001 and not response.getheader("WWW-Authenticate", "").startswith("Bearer "):
                    return False
                response.read(1024)
            finally:
                connection.close()
    except (OSError, HTTPException):
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(0 if healthy() else 1)
