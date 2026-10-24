from __future__ import annotations

import argparse
import ipaddress
import json
import shutil
import sqlite3
import socket
import select
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_DB_PATH = ROOT / "portal.db"
FILTER_TABLE = ("inet", "ecoconnect_filter")
NAT_TABLE = ("ip", "ecoconnect_nat")


def active_clients(db_path: Path) -> list[tuple[str, int]]:
    now = int(time.time())
    clients: list[tuple[str, int]] = []

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE sessions
            SET active_until = 0, is_connected = 0, updated_at = ?
            WHERE is_connected = 1 AND active_until <= ?
            """,
            (now, now),
        )
        rows = conn.execute(
            """
            SELECT client_ip, active_until
            FROM sessions
            WHERE is_connected = 1 AND active_until > ?
            """,
            (now,),
        ).fetchall()

    for client_ip, active_until in rows:
        try:
            ip = ipaddress.ip_address(str(client_ip))
        except ValueError:
            continue

        if ip.version != 4:
            continue

        ttl = max(1, int(active_until) - now)
        clients.append((str(ip), ttl))

    return clients


def run_nft(args: list[str], input_text: str | None = None) -> None:
    subprocess.run(
        ["nft", *args],
        input=input_text,
        text=True,
        check=True,
    )


def table_exists(family: str, table: str) -> bool:
    result = subprocess.run(
        ["nft", "list", "table", family, table],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return result.returncode == 0


def delete_table_if_exists(family: str, table: str) -> None:
    if table_exists(family, table):
        run_nft(["delete", "table", family, table])


def nft_string(value: str) -> str:
    return json.dumps(value)


last_dns_check = 0.0
last_domains: list[str] = []
cached_ips: set[str] = set()


def get_blacklisted_domains(db_path: Path) -> list[str]:
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute("SELECT domain FROM blacklist").fetchall()
        return [row[0] for row in rows]
    except Exception:
        return []


def resolve_domains(domains: list[str]) -> set[str]:
    ips: set[str] = set()
    for domain in domains:
        try:
            infos = socket.getaddrinfo(domain, None, socket.AF_INET, socket.SOCK_STREAM)
            for info in infos:
                ip = info[4][0]
                ips.add(ip)
        except Exception:
            pass
    return ips


def update_blocked_ips_if_needed(db_path: Path, force: bool = False) -> set[str]:
    global last_dns_check, last_domains, cached_ips
    now = time.time()
    domains = get_blacklisted_domains(db_path)
    
    if force or domains != last_domains or (now - last_dns_check > 300.0):
        cached_ips = resolve_domains(domains)
        last_domains = domains
        last_dns_check = now
        
    return cached_ips


def sync_blocked_ips(ips: set[str], dry_run: bool) -> None:
    elements = ", ".join(ips)

    if dry_run:
        print(
            json.dumps(
                {
                    "blocked_ips": list(ips)
                },
                indent=2,
            )
        )
        return

    script = "flush set inet ecoconnect_filter blocked_ips\n"
    if elements:
        script += f"add element inet ecoconnect_filter blocked_ips {{ {elements} }}\n"
    try:
        run_nft(["-f", "-"], script)
    except Exception as e:
        print(f"Error syncing blocked IPs: {e}", file=sys.stderr)


def install_rules(lan_interface: str, upstream_interface: str) -> None:
    delete_table_if_exists(*FILTER_TABLE)
    delete_table_if_exists(*NAT_TABLE)

    rules = f"""
table inet ecoconnect_filter {{
  set allowed_clients {{
    type ipv4_addr
    flags timeout
  }}

  set blocked_ips {{
    type ipv4_addr
  }}

  chain forward {{
    type filter hook forward priority filter; policy drop;
    ip daddr @blocked_ips reject
    iifname {nft_string(lan_interface)} ip saddr @allowed_clients oifname {nft_string(upstream_interface)} accept
    iifname {nft_string(upstream_interface)} ip daddr @allowed_clients oifname {nft_string(lan_interface)} ct state established,related accept
  }}
}}

table ip ecoconnect_nat {{
  set allowed_clients {{
    type ipv4_addr
    flags timeout
  }}

  chain prerouting {{
    type nat hook prerouting priority dstnat; policy accept;
    iifname {nft_string(lan_interface)} ip saddr != @allowed_clients tcp dport 80 redirect to :8080
  }}

  chain postrouting {{
    type nat hook postrouting priority srcnat; policy accept;
    oifname {nft_string(upstream_interface)} masquerade
  }}
}}
"""
    run_nft(["-f", "-"], rules)


def set_ip_forwarding(enabled: bool) -> None:
    path = Path("/proc/sys/net/ipv4/ip_forward")
    if path.exists():
        path.write_text("1\n" if enabled else "0\n", encoding="utf-8")


def purge_conntrack(client_ip: str, conntrack_path: str | None) -> None:
    if not conntrack_path:
        return

    for direction in ("-s", "-d"):
        subprocess.run(
            [conntrack_path, "-D", direction, client_ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )


def sync_allowed_clients(clients: list[tuple[str, int]], dry_run: bool) -> None:
    elements = ", ".join(f"{client_ip} timeout {ttl}s" for client_ip, ttl in clients)

    if dry_run:
        print(
            json.dumps(
                {
                    "allowed_clients": [
                        {"client_ip": client_ip, "ttl_seconds": ttl}
                        for client_ip, ttl in clients
                    ]
                },
                indent=2,
            )
        )
        return

    script = "flush set inet ecoconnect_filter allowed_clients\n"
    script += "flush set ip ecoconnect_nat allowed_clients\n"
    if elements:
        script += f"add element inet ecoconnect_filter allowed_clients {{ {elements} }}\n"
        script += f"add element ip ecoconnect_nat allowed_clients {{ {elements} }}\n"
    run_nft(["-f", "-"], script)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Keep Orange Pi forwarding open only for active EcoConnect clients."
    )
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to portal.db")
    parser.add_argument(
        "--lan-interface",
        default="eth0",
        help="Interface connected to the Wi-Fi AP/router LAN side",
    )
    parser.add_argument(
        "--upstream-interface",
        default="wlan0",
        help="USB Wi-Fi interface connected to the main ISP",
    )
    parser.add_argument("--poll-seconds", default=1.0, type=float)
    parser.add_argument(
        "--flush-conntrack",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Drop existing connection-tracking entries when a client is paused or expires",
    )
    parser.add_argument("--once", action="store_true", help="Sync once and exit")
    parser.add_argument("--dry-run", action="store_true", help="Print allowed clients only")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db).expanduser().resolve()

    if not db_path.exists():
        print(f"Database not found: {db_path}", file=sys.stderr)
        return 1

    if not args.dry_run and not shutil.which("nft"):
        print("nft command not found. Install nftables first.", file=sys.stderr)
        return 1

    if not args.dry_run:
        set_ip_forwarding(True)
        install_rules(args.lan_interface, args.upstream_interface)

    previous_allowed: set[str] = set()
    conntrack_path = shutil.which("conntrack") if args.flush_conntrack else None

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 5555))
    sock.setblocking(False)

    while True:
        clients = active_clients(db_path)
        current_allowed = {client_ip for client_ip, _ttl in clients}
        sync_allowed_clients(clients, args.dry_run)
        for removed_client in previous_allowed - current_allowed:
            purge_conntrack(removed_client, conntrack_path)
        previous_allowed = current_allowed

        blocked_ips = update_blocked_ips_if_needed(db_path)
        sync_blocked_ips(blocked_ips, args.dry_run)
        
        if args.once:
            return 0
            
        ready, _, _ = select.select([sock], [], [], 10.0)
        if ready:
            while True:
                try:
                    sock.recv(1024)
                except BlockingIOError:
                    break


if __name__ == "__main__":
    raise SystemExit(main())
