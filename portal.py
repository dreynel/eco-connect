import json
import os
import secrets
import socket
import sqlite3
import time
from argparse import ArgumentParser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import uvicorn
import hashlib
from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
DB_PATH = ROOT / "portal.db"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080
TRUST_PROXY_HEADERS = os.environ.get("ECOCON_TRUST_PROXY_HEADERS", "").lower() in {"1", "true", "yes", "on"}

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    hashed = hashlib.scrypt(
        password.encode('utf-8'),
        salt=salt,
        n=16384,
        r=8,
        p=1
    )
    return f"{salt.hex()}:{hashed.hex()}"

def verify_password(password: str, hashed_str: str) -> bool:
    try:
        salt_hex, hashed_hex = hashed_str.split(':')
        salt = bytes.fromhex(salt_hex)
        hashed = bytes.fromhex(hashed_hex)
        
        new_hashed = hashlib.scrypt(
            password.encode('utf-8'),
            salt=salt,
            n=16384,
            r=8,
            p=1
        )
        return new_hashed == hashed
    except Exception:
        return False

RATES: dict[str, dict[str, int]] = {
    "plastic_bottle": {"small": 5, "medium": 7, "large": 10},
    "metal_can": {"small": 7, "medium": 10, "large": 15},
}

def load_rates() -> None:
    global RATES
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute("SELECT material, size, minutes FROM rates")
            rows = cursor.fetchall()
            if rows:
                new_rates = {}
                for material, size, minutes in rows:
                    if material not in new_rates:
                        new_rates[material] = {}
                    new_rates[material][size] = minutes
                RATES = new_rates
    except Exception:
        pass

MATERIAL_LABELS = {"plastic_bottle": "Plastic Bottle", "metal_can": "Metal Can"}
SIZE_LABELS = {"small": "Small", "medium": "Medium", "large": "Large"}

CAPTIVE_CHECK_PATHS = {
    "/generate_204", "/gen_204", "/hotspot-detect.html",
    "/library/test/success.html", "/ncsi.txt", "/connecttest.txt",
    "/success.txt", "/canonical.html", "/redirect", "/fwlink"
}

insert_state = {
    "client_ip": None,
    "expires_at": 0
}

def clear_insert_lock(client_ip: str) -> None:
    if insert_state["client_ip"] == client_ip:
        insert_state["client_ip"] = None
        insert_state["expires_at"] = 0

def notify_firewall() -> None:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(b"sync", ("127.0.0.1", 5555))
    except Exception:
        pass


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rates (
                material TEXT NOT NULL,
                size TEXT NOT NULL,
                minutes INTEGER NOT NULL,
                PRIMARY KEY (material, size)
            )
            """
        )
        cursor = conn.execute("SELECT COUNT(*) FROM rates")
        if cursor.fetchone()[0] == 0:
            defaults = [
                ("plastic_bottle", "small", 5),
                ("plastic_bottle", "medium", 7),
                ("plastic_bottle", "large", 10),
                ("metal_can", "small", 7),
                ("metal_can", "medium", 10),
                ("metal_can", "large", 15),
            ]
            conn.executemany("INSERT INTO rates (material, size, minutes) VALUES (?, ?, ?)", defaults)

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                client_ip TEXT PRIMARY KEY,
                active_until INTEGER NOT NULL,
                paused_seconds INTEGER NOT NULL DEFAULT 0,
                is_connected INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS topups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_ip TEXT NOT NULL,
                material TEXT NOT NULL,
                size TEXT NOT NULL,
                minutes_added INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                session_token TEXT
            )
            """
        )
        
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS blacklist (
                domain TEXT PRIMARY KEY,
                created_at INTEGER NOT NULL
            )
            """
        )
        
        # Insert default admin if none exists, or migrate legacy bcrypt hashes
        cursor = conn.execute("SELECT id, username, password_hash FROM admins")
        rows = cursor.fetchall()
        if len(rows) == 0:
            default_user = os.environ.get("ECOCON_ADMIN_USERNAME", "admin")
            default_pass = os.environ.get("ECOCON_ADMIN_PASSWORD", "admin")
            hashed = hash_password(default_pass)
            conn.execute(
                "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
                (default_user, hashed)
            )
        else:
            for admin_id, username, pwd_hash in rows:
                if pwd_hash.startswith(("$2a$", "$2b$", "$2y$")):
                    default_pass = os.environ.get("ECOCON_ADMIN_PASSWORD", "admin")
                    new_hash = hash_password(default_pass)
                    conn.execute(
                        "UPDATE admins SET password_hash = ? WHERE id = ?",
                        (new_hash, admin_id)
                    )

        migrate_sessions(conn)
    load_rates()


def migrate_sessions(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    if "paused_seconds" not in columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN paused_seconds INTEGER NOT NULL DEFAULT 0")
    if "is_connected" not in columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN is_connected INTEGER NOT NULL DEFAULT 0")

    now = int(time.time())
    rows = conn.execute(
        """
        SELECT client_ip, active_until
        FROM sessions
        WHERE active_until > ? AND paused_seconds = 0 AND is_connected = 0
        """,
        (now,),
    ).fetchall()
    for client_ip, active_until in rows:
        conn.execute(
            """
            UPDATE sessions
            SET paused_seconds = ?, active_until = 0, updated_at = ?
            WHERE client_ip = ?
            """,
            (max(0, int(active_until) - now), now, client_ip),
        )


def calculate_remaining(active_until: int, paused_seconds: int, is_connected: bool) -> int:
    if is_connected:
        return max(0, active_until - int(time.time())) + paused_seconds
    return max(0, paused_seconds)


def fetch_session_row(conn: sqlite3.Connection, client_ip: str) -> tuple[int, int, bool]:
    row = conn.execute(
        """
        SELECT active_until, paused_seconds, is_connected
        FROM sessions
        WHERE client_ip = ?
        """,
        (client_ip,),
    ).fetchone()
    if not row:
        return 0, 0, False
    return int(row[0]), int(row[1]), bool(row[2])


def normalize_expired_session(conn: sqlite3.Connection, client_ip: str) -> None:
    now = int(time.time())
    cursor = conn.execute(
        """
        UPDATE sessions
        SET active_until = 0, is_connected = 0, updated_at = ?
        WHERE client_ip = ? AND is_connected = 1 AND active_until <= ?
        """,
        (now, client_ip, now),
    )
    if cursor.rowcount > 0:
        notify_firewall()


def get_session(client_ip: str) -> dict[str, Any]:
    now = int(time.time())
    with sqlite3.connect(DB_PATH) as conn:
        normalize_expired_session(conn, client_ip)
        active_until, paused_seconds, is_connected = fetch_session_row(conn, client_ip)
        
    is_locked = insert_state["client_ip"] is not None and insert_state["expires_at"] > now
    locked_by_me = is_locked and insert_state["client_ip"] == client_ip
    locked_by_other = is_locked and not locked_by_me

    return {
        "active_until": active_until,
        "paused_seconds": paused_seconds,
        "is_connected": is_connected,
        "remaining_seconds": calculate_remaining(active_until, paused_seconds, is_connected),
        "server_time": now,
        "insert_locked_by_me": locked_by_me,
        "insert_locked_by_other": locked_by_other,
    }


def add_topup(client_ip: str, material: str, size: str) -> dict[str, Any]:
    if material not in RATES or size not in RATES[material]:
        raise ValueError("Unknown material or size")

    now = int(time.time())
    minutes = RATES[material][size]
    seconds = minutes * 60

    with sqlite3.connect(DB_PATH) as conn:
        normalize_expired_session(conn, client_ip)
        active_until, paused_seconds, is_connected = fetch_session_row(conn, client_ip)

        if is_connected:
            total_remaining = max(0, active_until - now) + paused_seconds + seconds
            connection_seconds = min(total_remaining, 3600)
            paused_seconds = total_remaining - connection_seconds
            active_until = now + connection_seconds
        else:
            paused_seconds += seconds
            active_until = 0

        conn.execute(
            """
            INSERT INTO sessions (client_ip, active_until, paused_seconds, is_connected, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(client_ip) DO UPDATE SET
                active_until = excluded.active_until,
                paused_seconds = excluded.paused_seconds,
                is_connected = excluded.is_connected,
                updated_at = excluded.updated_at
            """,
            (client_ip, active_until, paused_seconds, int(is_connected), now),
        )
        conn.execute(
            """
            INSERT INTO topups (client_ip, material, size, minutes_added, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (client_ip, material, size, minutes, now),
        )

    notify_firewall()
    
    # We keep the lock after topup so they can keep adding. 
    # It releases when they connect, pause, or cancel.
    status_data = get_session(client_ip)
    status_data.update({
        "material": material,
        "material_label": MATERIAL_LABELS[material],
        "size": size,
        "size_label": SIZE_LABELS[size],
        "minutes_added": minutes,
    })
    return status_data


def connect_session(client_ip: str) -> dict[str, Any]:
    now = int(time.time())
    with sqlite3.connect(DB_PATH) as conn:
        normalize_expired_session(conn, client_ip)
        active_until, paused_seconds, is_connected = fetch_session_row(conn, client_ip)
        remaining_seconds = calculate_remaining(active_until, paused_seconds, is_connected)

        if remaining_seconds <= 0:
            raise ValueError("Add time before connecting.")

        connection_seconds = min(remaining_seconds, 3600)
        extra_seconds = remaining_seconds - connection_seconds
        active_until = now + connection_seconds
        conn.execute(
            """
            INSERT INTO sessions (client_ip, active_until, paused_seconds, is_connected, updated_at)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(client_ip) DO UPDATE SET
                active_until = excluded.active_until,
                paused_seconds = excluded.paused_seconds,
                is_connected = 1,
                updated_at = excluded.updated_at
            """,
            (client_ip, active_until, extra_seconds, now),
        )

    clear_insert_lock(client_ip)
    notify_firewall()
    return get_session(client_ip)


def pause_session(client_ip: str) -> dict[str, Any]:
    now = int(time.time())
    with sqlite3.connect(DB_PATH) as conn:
        normalize_expired_session(conn, client_ip)
        active_until, paused_seconds, is_connected = fetch_session_row(conn, client_ip)
        remaining_seconds = calculate_remaining(active_until, paused_seconds, is_connected)
        conn.execute(
            """
            INSERT INTO sessions (client_ip, active_until, paused_seconds, is_connected, updated_at)
            VALUES (?, 0, ?, 0, ?)
            ON CONFLICT(client_ip) DO UPDATE SET
                active_until = 0,
                paused_seconds = excluded.paused_seconds,
                is_connected = 0,
                updated_at = excluded.updated_at
            """,
            (client_ip, remaining_seconds, now),
        )

    clear_insert_lock(client_ip)
    notify_firewall()
    return get_session(client_ip)


def verify_admin_session(admin_session: Optional[str] = Cookie(None)) -> bool:
    if not admin_session:
        return False
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT id FROM admins WHERE session_token = ?", (admin_session,)).fetchone()
        return row is not None


def get_client_ip(request: Request) -> str:
    if TRUST_PROXY_HEADERS and "x-forwarded-for" in request.headers:
        return request.headers["x-forwarded-for"].split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

class LoginRequest(BaseModel):
    username: str
    password: str

class TopupRequest(BaseModel):
    material: str
    size: str

class UpdateRatesRequest(BaseModel):
    rates: dict[str, dict[str, int]]

@app.middleware("http")
async def captive_portal_middleware(request: Request, call_next):
    path = request.url.path
    if path in CAPTIVE_CHECK_PATHS:
        client_ip = get_client_ip(request)
        session = get_session(client_ip)
        if not session["is_connected"] or session["remaining_seconds"] <= 0:
            return RedirectResponse(url="http://192.168.8.1:8080/")
        
        if path in {"/generate_204", "/gen_204"}:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        if path == "/ncsi.txt":
            return PlainTextResponse("Microsoft NCSI")
        if path == "/connecttest.txt":
            return PlainTextResponse("Microsoft Connect Test")
        if path in {"/success.txt", "/canonical.html"}:
            return PlainTextResponse("success\n")
        
        return HTMLResponse("<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>")
    
    response = await call_next(request)
    return response

@app.get("/")
@app.get("/index.html")
async def read_index():
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

@app.get("/admin")
@app.get("/admin.html")
async def read_admin():
    return FileResponse(STATIC_DIR / "admin.html", media_type="text/html")

@app.get("/api/status")
async def api_status(request: Request):
    return get_session(get_client_ip(request))

@app.get("/api/rates")
async def api_rates():
    rates_data = {
        material: {
            "label": MATERIAL_LABELS[material],
            "sizes": {
                size: {"label": SIZE_LABELS[size], "minutes": minutes}
                for size, minutes in sizes.items()
            },
        }
        for material, sizes in RATES.items()
    }
    return {"rates": rates_data}

@app.post("/api/insert/start")
async def api_insert_start(request: Request):
    client_ip = get_client_ip(request)
    now = time.time()
    
    if insert_state["client_ip"] is not None and insert_state["client_ip"] != client_ip and insert_state["expires_at"] > now:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Machine is currently in use by another user.")
        
    insert_state["client_ip"] = client_ip
    insert_state["expires_at"] = now + 120 # 2 minutes lock
    
    return get_session(client_ip)

@app.post("/api/insert/cancel")
async def api_insert_cancel(request: Request):
    clear_insert_lock(get_client_ip(request))
    return get_session(get_client_ip(request))

@app.post("/api/connect")
async def api_connect(request: Request):
    try:
        return connect_session(get_client_ip(request))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@app.post("/api/pause")
async def api_pause(request: Request):
    return pause_session(get_client_ip(request))

@app.post("/api/reset")
async def api_reset(request: Request):
    client_ip = get_client_ip(request)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO sessions (client_ip, active_until, paused_seconds, is_connected, updated_at)
            VALUES (?, 0, 0, 0, ?)
            ON CONFLICT(client_ip) DO UPDATE SET
                active_until = 0,
                paused_seconds = 0,
                is_connected = 0,
                updated_at = excluded.updated_at
            """,
            (client_ip, int(time.time()))
        )
    notify_firewall()
    return get_session(client_ip)

@app.post("/api/topup")
async def api_topup(request: Request, data: TopupRequest):
    try:
        return add_topup(get_client_ip(request), data.material, data.size)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@app.get("/api/admin/session")
async def api_admin_session(is_auth: bool = Depends(verify_admin_session)):
    return {"authenticated": is_auth}

@app.post("/api/admin/login")
async def api_admin_login(data: LoginRequest, response: Response):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT id, password_hash FROM admins WHERE username = ?", (data.username,)).fetchone()
        if not row or not verify_password(data.password, row[1]):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin credentials.")
        
        token = secrets.token_urlsafe(32)
        conn.execute("UPDATE admins SET session_token = ? WHERE id = ?", (token, row[0]))
        
        response.set_cookie(key="admin_session", value=token, httponly=True, samesite="lax")
        return {"authenticated": True}

@app.post("/api/admin/logout")
async def api_admin_logout(response: Response, admin_session: Optional[str] = Cookie(None)):
    if admin_session:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("UPDATE admins SET session_token = NULL WHERE session_token = ?", (admin_session,))
    response.delete_cookie("admin_session")
    return {"authenticated": False}

@app.post("/api/admin/rates")
async def api_admin_rates(data: UpdateRatesRequest, is_auth: bool = Depends(verify_admin_session)):
    if not is_auth:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin login required.")
    
    # Validation
    for material, sizes in data.rates.items():
        if material not in MATERIAL_LABELS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid material: {material}")
        for size, minutes in sizes.items():
            if size not in SIZE_LABELS:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid size: {size}")
            if not isinstance(minutes, int) or minutes < 0:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Time allotment must be non-negative integer.")

    # Save to db
    with sqlite3.connect(DB_PATH) as conn:
        for material, sizes in data.rates.items():
            for size, minutes in sizes.items():
                conn.execute(
                    """
                    INSERT INTO rates (material, size, minutes)
                    VALUES (?, ?, ?)
                    ON CONFLICT(material, size) DO UPDATE SET minutes = excluded.minutes
                    """,
                    (material, size, minutes)
                )
    
    # Reload in-memory rates
    load_rates()
    return {"rates": RATES}

class BlacklistRequest(BaseModel):
    domain: str

@app.get("/api/admin/blacklist")
async def api_admin_blacklist(is_auth: bool = Depends(verify_admin_session)):
    if not is_auth:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin login required.")
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT domain, created_at FROM blacklist ORDER BY created_at DESC").fetchall()
    return {"blacklist": [{"domain": row[0], "created_at": row[1]} for row in rows]}

@app.post("/api/admin/blacklist")
async def api_admin_add_blacklist(data: BlacklistRequest, is_auth: bool = Depends(verify_admin_session)):
    if not is_auth:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin login required.")
    domain = data.domain.strip().lower()
    if not domain:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Domain name cannot be empty.")
    if " " in domain or "." not in domain:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid domain name format.")
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("INSERT INTO blacklist (domain, created_at) VALUES (?, ?)", (domain, int(time.time())))
        notify_firewall()
        return {"success": True, "domain": domain}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Domain already exists in blacklist.")

@app.delete("/api/admin/blacklist/{domain}")
async def api_admin_delete_blacklist(domain: str, is_auth: bool = Depends(verify_admin_session)):
    if not is_auth:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin login required.")
    domain = domain.strip().lower()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM blacklist WHERE domain = ?", (domain,))
    notify_firewall()
    return {"success": True}

@app.post("/api/admin/reset_dashboard")
async def api_admin_reset_dashboard(is_auth: bool = Depends(verify_admin_session)):
    if not is_auth:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin login required.")
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM topups")
        conn.execute("DELETE FROM sessions")
    
    notify_firewall()
    return {"success": True}

@app.get("/api/admin/dashboard")
async def api_admin_dashboard(is_auth: bool = Depends(verify_admin_session)):
    if not is_auth:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin login required.")
    
    now = int(time.time())
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            UPDATE sessions
            SET active_until = 0, is_connected = 0, updated_at = ?
            WHERE is_connected = 1 AND active_until <= ?
            """,
            (now, now),
        )
        if conn.execute("SELECT changes()").fetchone()[0] > 0:
            notify_firewall()
            
        totals = conn.execute("SELECT COUNT(*), COALESCE(SUM(minutes_added), 0) FROM topups").fetchone()
        active_clients = conn.execute("SELECT COUNT(*) FROM sessions WHERE is_connected = 1 AND active_until > ?", (now,)).fetchone()[0]
        saved_clients = conn.execute("SELECT COUNT(*) FROM sessions WHERE is_connected = 0 AND paused_seconds > 0").fetchone()[0]
        breakdown_rows = conn.execute("SELECT material, size, COUNT(*), COALESCE(SUM(minutes_added), 0) FROM topups GROUP BY material, size").fetchall()
        recent_rows = conn.execute("SELECT client_ip, material, size, minutes_added, created_at FROM topups ORDER BY created_at DESC LIMIT 30").fetchall()
        session_rows = conn.execute("SELECT client_ip, active_until, paused_seconds, is_connected, updated_at FROM sessions WHERE is_connected = 1 OR paused_seconds > 0 ORDER BY updated_at DESC LIMIT 30").fetchall()

    return {
        "server_time": now,
        "summary": {
            "item_count": int(totals[0]),
            "total_minutes": int(totals[1]),
            "active_clients": int(active_clients),
            "saved_clients": int(saved_clients),
        },
        "breakdown": [
            {
                "material": material,
                "material_label": MATERIAL_LABELS.get(material, material),
                "size": size,
                "size_label": SIZE_LABELS.get(size, size),
                "count": int(count),
                "minutes": int(minutes),
            }
            for material, size, count, minutes in breakdown_rows
        ],
        "recent_topups": [
            {
                "client_ip": client_ip,
                "material": material,
                "material_label": MATERIAL_LABELS.get(material, material),
                "size": size,
                "size_label": SIZE_LABELS.get(size, size),
                "minutes_added": int(minutes_added),
                "created_at": int(created_at),
            }
            for client_ip, material, size, minutes_added, created_at in recent_rows
        ],
        "sessions": [
            {
                "client_ip": client_ip,
                "is_connected": bool(is_connected),
                "remaining_seconds": calculate_remaining(int(active_until), int(paused_seconds), bool(is_connected)),
                "updated_at": int(updated_at),
            }
            for client_ip, active_until, paused_seconds, is_connected, updated_at in session_rows
        ],
    }

def parse_args():
    parser = ArgumentParser(description="Run the EcoConnect portal server.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", default=DEFAULT_PORT, type=int)
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite database path")
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()
    DB_PATH = Path(args.db).expanduser().resolve()
    uvicorn.run(app, host=args.host, port=args.port)
