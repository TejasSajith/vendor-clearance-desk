"""Start the web UI on this machine:  python -m app [--port 8000]

Binds to 127.0.0.1 only. APP_PASSWORD is optional here (local only); set it to require a sign-in.
Stop with Ctrl+C. If the port is busy:  lsof -ti tcp:8000 | xargs kill   (or pick another with --port).
"""
import argparse, errno, logging, os, socket, sys

HOST = "127.0.0.1"

def port_free(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try: s.bind((HOST, port)); return True
    except OSError as e:
        if e.errno in (errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", -1)): return False
        raise
    finally: s.close()

def password_note(from_shell):
    """Where the access password comes from, for the start-up message. Never prints the value."""
    if not (os.environ.get("APP_PASSWORD") or "").strip(): return "none (local only; set APP_PASSWORD to require one)"
    return "required, APP_PASSWORD from " + ("the shell environment" if from_shell else ".env in the repo root (remove that line for no password)")

def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m app", description="Vendor Clearance Desk web UI (local)")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    a = ap.parse_args(argv)
    if not port_free(a.port):
        print(f"Port {a.port} is already in use (probably an earlier server that was left running).\n"
              f"  Free it:        lsof -ti tcp:{a.port} | xargs kill\n"
              f"  Or use another: python -m app --port {a.port + 1}", file=sys.stderr)
        return 1
    import uvicorn
    from .server import create_app
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from_shell = bool((os.environ.get("APP_PASSWORD") or "").strip())   # before create_app reads .env
    try: app = create_app(require_password=False)
    except RuntimeError as e:
        print(f"Cannot start: {e}", file=sys.stderr); return 1
    url = f"http://{HOST}:{a.port}"
    print(f"\nVendor Clearance Desk running at {url}\n"
          f"  Stop: Ctrl+C here (or: lsof -ti tcp:{a.port} | xargs kill)\n"
          f"  Password: {password_note(from_shell)}\n", flush=True)
    uvicorn.run(app, host=HOST, port=a.port, log_level="info", access_log=True)
    return 0

if __name__ == "__main__": raise SystemExit(main())
