from flask import Flask, request, jsonify, session, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import requests
import os
import json
import sqlite3
import secrets
import smtplib
import threading
import time
import glob
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import hashlib
from datetime import datetime, timedelta, timezone
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")

APP_ID     = os.environ.get("ADZUNA_APP_ID",  "")
APP_KEY    = os.environ.get("ADZUNA_APP_KEY", "")
ADMIN_USER = os.environ.get("ADMIN_USER", "").strip()

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", os.environ.get("SMTP_USER", ""))
APP_URL   = os.environ.get("APP_URL", "http://localhost:8080")

_dir       = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.environ.get("DATA_DIR", os.path.join(_dir, "data"))
DB_PATH    = os.path.join(DATA_DIR, "jobfinder.db")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
BACKUP_KEEP = int(os.environ.get("BACKUP_KEEP", "7"))   # Aufbewahrungsdauer in Tagen
BACKUP_HOUR = int(os.environ.get("BACKUP_HOUR", "2"))   # UTC-Stunde für tägliches Backup
WATCH_INTERVAL_MINUTES = int(os.environ.get("WATCH_INTERVAL_MINUTES", "60"))  # Prüfintervall
WATCH_SCRAPE_DELAY     = int(os.environ.get("WATCH_SCRAPE_DELAY", "5"))       # Sekunden zwischen zwei Scrapes
WATCH_MAX_PAGES        = int(os.environ.get("WATCH_MAX_PAGES",    "10"))      # Max. Seiten pro Karriereseite


# ── Automatisches Backup ──────────────────────────────────────────

def _build_backup_payload():
    """Erstellt das Backup-Payload-Dict mit allen Nutzerdaten inkl. Watch-Daten."""
    with get_db() as db:
        users = [dict(r) for r in db.execute(
            "SELECT id, username, password_hash, email, is_admin, is_locked, created_at FROM users"
        ).fetchall()]
        user_data = [dict(r) for r in db.execute(
            "SELECT user_id, saved, ignored, jira_config FROM user_data"
        ).fetchall()]
        watches = [dict(r) for r in db.execute(
            "SELECT id, user_id, name, career_url, keywords, active, check_interval_hours, "
            "last_checked_at, last_check_status, created_at FROM company_watches"
        ).fetchall()]
        watch_jobs = [dict(r) for r in db.execute(
            "SELECT id, company_id, title, url, found_at, last_seen_at, is_new FROM watch_jobs"
        ).fetchall()]
    return {
        "version": "1.1",
        "app": "JobPipeline",
        "created": datetime.now(timezone.utc).isoformat(),
        "users": users,
        "user_data": user_data,
        "company_watches": watches,
        "watch_jobs": watch_jobs,
    }


def _make_backup():
    """Erstellt eine JSON-Sicherung aller Nutzerdaten und gibt den Dateipfad zurück."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    payload = _build_backup_payload()
    ts   = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M")
    path = os.path.join(BACKUP_DIR, f"backup_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    # Alte Backups bereinigen
    files = sorted(glob.glob(os.path.join(BACKUP_DIR, "backup_*.json")))
    for old in files[:-BACKUP_KEEP]:
        os.remove(old)
    return path


def _schedule_backup():
    """Startet einen Hintergrund-Thread, der täglich um BACKUP_HOUR UTC eine Sicherung erstellt."""
    def _loop():
        while True:
            now    = datetime.now(timezone.utc)
            target = now.replace(hour=BACKUP_HOUR, minute=0, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            time.sleep((target - now).total_seconds())
            try:
                path = _make_backup()
                print(f"[Backup] Automatisches Backup erstellt: {path}", flush=True)
            except Exception as e:
                print(f"[Backup] Fehler: {e}", flush=True)
    threading.Thread(target=_loop, daemon=True, name="daily-backup").start()


# ── Karriere-Monitor: Scraping & Scheduler ────────────────────────

def _get_global_kw(uid):
    """Gibt die globalen Suchbegriffe eines Nutzers zurück."""
    with get_db() as db:
        row = db.execute("SELECT watch_global_kw FROM users WHERE id = ?", [uid]).fetchone()
    return json.loads(row["watch_global_kw"] or "[]") if row else []


def _merge_kw(global_kw, company_kw):
    """Vereint globale und unternehmensspezifische Keywords, dedupliziert, behält Reihenfolge."""
    return list(dict.fromkeys(global_kw + company_kw))

def _extract_jobs_from_html(html, base_url, kw_lower, found, seen):
    """Extrahiert keyword-passende Treffer aus HTML und fügt sie in found/seen ein."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["a", "h1", "h2", "h3", "h4", "li", "span"]):
        text = tag.get_text(strip=True)
        if len(text) < 4 or len(text) > 250:
            continue
        if any(kw in text.lower() for kw in kw_lower):
            href = tag.get("href", "") if tag.name == "a" else ""
            if href and not href.startswith("http"):
                href = urljoin(base_url, href)
            key = href or text
            if key not in seen:
                seen.add(key)
                found.append({"title": text, "url": href or base_url})


def _find_next_page(pw_page, base_url):
    """Sucht die URL der nächsten Seite (rel=next, aria-label, Text). Gibt URL oder None zurück."""
    # 1. <link rel="next"> oder <a rel="next">
    for sel in ['link[rel="next"]', 'a[rel="next"]']:
        el = pw_page.query_selector(sel)
        if el:
            href = el.get_attribute("href")
            if href:
                return urljoin(base_url, href)

    # 2. Aria-Label-basierte Selektoren
    for sel in [
        'a[aria-label*="next" i]', 'a[aria-label*="weiter" i]', 'a[aria-label*="nächste" i]',
        'button[aria-label*="next" i]', 'button[aria-label*="weiter" i]',
        '.pagination .next a', '.pagination__next a', '.pager__next a',
        '[class*="pagination"] [class*="next"]:not([disabled])',
        '[class*="pagination"] [class*="Next"]:not([disabled])',
    ]:
        try:
            el = pw_page.query_selector(sel)
            if el and el.is_visible() and el.is_enabled():
                href = el.get_attribute("href")
                if href and href not in ("#", "javascript:void(0)", "javascript:", ""):
                    return urljoin(base_url, href)
        except Exception:
            pass

    # 3. Text-basierte Suche: "›", "»", "Weiter", "Next", ">"
    for text_candidate in ["›", "»", "→", "Weiter", "Next"]:
        try:
            links = pw_page.query_selector_all("a, button")
            for el in links:
                if not el.is_visible():
                    continue
                label = (el.inner_text() or "").strip()
                if label == text_candidate or label.endswith(text_candidate):
                    href = el.get_attribute("href") or ""
                    if href and href not in ("#", "javascript:void(0)", "javascript:", ""):
                        return urljoin(base_url, href)
        except Exception:
            pass

    return None


def _find_load_more_btn(pw_page):
    """Sucht einen 'Mehr anzeigen'-Button, der Inhalte ohne Seitenwechsel nachlädt."""
    # 1. CSS-Klassen-Selektoren (typische Load-More-Patterns)
    for sel in [
        'button[class*="load-more"]', 'a[class*="load-more"]', '[class*="load-more"] button',
        'button[class*="loadMore"]',  'a[class*="loadMore"]',
        'button[class*="show-more"]', 'a[class*="show-more"]', '[class*="show-more"] button',
        '[class*="moreResults"]',     '[class*="more-results"]',
        '[data-load-more]',           '[data-action*="loadMore"]', '[data-action*="load-more"]',
    ]:
        try:
            el = pw_page.query_selector(sel)
            if el and el.is_visible() and el.is_enabled():
                href = el.get_attribute("href") or ""
                # Echte Navigations-URLs überspringen (werden von _find_next_page behandelt)
                if href and href not in ("#", "javascript:void(0)", "javascript:", "") \
                        and not href.startswith("javascript:"):
                    continue
                return el
        except Exception:
            pass

    # 2. Text-basierte Suche (Deutsch + Englisch)
    load_more_texts = [
        "mehr anzeigen", "mehr laden", "mehr jobs", "weitere stellen",
        "weitere jobs", "weitere ergebnisse", "mehr ergebnisse",
        "alle stellen", "mehr stellenanzeigen", "load more", "show more", "more jobs",
    ]
    try:
        for el in pw_page.query_selector_all("button, [role='button'], a[onclick], a[href='#']"):
            if not el.is_visible() or not el.is_enabled():
                continue
            label = (el.inner_text() or "").strip().lower()
            if any(t in label for t in load_more_texts):
                href = el.get_attribute("href") or ""
                if href and href not in ("#", "javascript:void(0)", "javascript:", "") \
                        and not href.startswith("javascript:"):
                    continue
                return el
    except Exception:
        pass

    return None


def _scrape_career_page(url, keywords):
    """Rendert Karriereseiten mit Playwright inkl. Pagination + Load-More und extrahiert Treffer."""
    from playwright.sync_api import sync_playwright
    kw_lower = [k.strip().lower() for k in keywords if k.strip()]
    found, seen = [], set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (compatible; JobPipeline-CareerMonitor/1.0; "
                "+https://github.com/Nilshh/JobFinder; automated career-page monitor)"
            ),
            extra_http_headers={"Accept-Language": "de-DE,de;q=0.9,en;q=0.8"},
        )
        page = ctx.new_page()
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)

        used_load_more = False
        for page_num in range(WATCH_MAX_PAGES):
            prev_count = len(found)
            _extract_jobs_from_html(page.content(), url, kw_lower, found, seen)
            new_this_round = len(found) - prev_count
            print(f"[Watch] Runde {page_num + 1}: {new_this_round} neue Treffer ({len(found)} gesamt)", flush=True)

            # Nach "Mehr anzeigen"-Klick ohne neue Keyword-Treffer → stoppen
            if used_load_more and new_this_round == 0:
                print("[Watch] 'Mehr anzeigen' ohne neue Treffer – stoppe.", flush=True)
                break

            if page_num + 1 >= WATCH_MAX_PAGES:
                break

            # Strategie 1: klassische Pagination (neue URL)
            next_url = _find_next_page(page, url)
            if next_url:
                used_load_more = False
                time.sleep(max(1, WATCH_SCRAPE_DELAY // 2))
                try:
                    page.goto(next_url, wait_until="networkidle", timeout=30000)
                    page.wait_for_timeout(1200)
                except Exception as e:
                    print(f"[Watch] Pagination-Fehler: {e}", flush=True)
                    break
                continue

            # Strategie 2: "Mehr anzeigen"-Button (gleiche Seite, JS lädt mehr Inhalt)
            btn = _find_load_more_btn(page)
            if btn:
                used_load_more = True
                try:
                    btn.scroll_into_view_if_needed()
                    btn.click()
                    try:
                        page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        page.wait_for_timeout(2000)
                    page.wait_for_timeout(800)
                except Exception as e:
                    print(f"[Watch] 'Mehr anzeigen'-Fehler: {e}", flush=True)
                    break
                continue

            # Weder Pagination noch Load-More → fertig
            print(f"[Watch] Keine weiteren Inhalte. Gesamt: {len(found)} Treffer.", flush=True)
            break

        browser.close()

    return found


def _save_watch_results(wid, jobs):
    """Speichert Scraping-Ergebnisse: neue Jobs einfügen, bestehende updaten. Gibt Anzahl neuer zurück."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as db:
        existing = {r["url"] for r in db.execute(
            "SELECT url FROM watch_jobs WHERE company_id = ?", [wid]
        ).fetchall()}
        new_count = 0
        for j in jobs:
            if j["url"] not in existing:
                db.execute(
                    "INSERT INTO watch_jobs (company_id, title, url) VALUES (?, ?, ?)",
                    [wid, j["title"], j["url"]]
                )
                new_count += 1
            else:
                db.execute(
                    "UPDATE watch_jobs SET last_seen_at = ? WHERE company_id = ? AND url = ?",
                    [now, wid, j["url"]]
                )
        db.execute(
            "UPDATE company_watches SET last_checked_at = ?, last_check_status = 'ok' WHERE id = ?",
            [now, wid]
        )
    return new_count


def _mark_watch_error(wid, error):
    """Markiert einen Watch-Check als fehlgeschlagen."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as db:
        db.execute(
            "UPDATE company_watches SET last_checked_at = ?, last_check_status = ? WHERE id = ?",
            [now, f"error: {str(error)[:200]}", wid]
        )


def _run_watch_checks():
    """Prüft alle fälligen aktiven Watches und speichert neue Treffer."""
    with get_db() as db:
        due = db.execute("""
            SELECT * FROM company_watches WHERE active = 1
            AND (last_checked_at IS NULL
              OR datetime(last_checked_at, '+' || check_interval_hours || ' hours') <= datetime('now'))
        """).fetchall()
    user_kw_cache = {}   # uid → globale Keywords (vermeidet mehrfache DB-Abfragen)
    for idx, w in enumerate([dict(r) for r in due]):
        if idx > 0:
            time.sleep(WATCH_SCRAPE_DELAY)   # Pause zwischen Unternehmen
        uid = w["user_id"]
        if uid not in user_kw_cache:
            user_kw_cache[uid] = _get_global_kw(uid)
        merged_kw = _merge_kw(user_kw_cache[uid], json.loads(w["keywords"]))
        try:
            jobs = _scrape_career_page(w["career_url"], merged_kw)
            new_count = _save_watch_results(w["id"], jobs)
            print(f"[Watch] '{w['name']}' geprüft – {len(jobs)} Treffer ({new_count} neu)", flush=True)
            _notify_after_watch_check(uid, new_count)
        except Exception as e:
            _mark_watch_error(w["id"], e)
            print(f"[Watch] Fehler bei '{w['name']}': {e}", flush=True)


def _schedule_watch_checks():
    """Startet einen Daemon-Thread, der alle WATCH_INTERVAL_MINUTES fällige Watches prüft."""
    def _loop():
        while True:
            time.sleep(WATCH_INTERVAL_MINUTES * 60)
            try:
                _run_watch_checks()
            except Exception as e:
                print(f"[Watch] Scheduler-Fehler: {e}", flush=True)
    threading.Thread(target=_loop, daemon=True, name="watch-checker").start()


# ── Watch-Benachrichtigungen ──────────────────────────────────────

_notify_last_sent = {}   # user_id → timestamp (Throttle: max 1x/Stunde bei instant)

def _send_watch_notification(user_id, new_jobs):
    """Sendet eine E-Mail mit neuen Watch-Treffern an den Nutzer."""
    if not SMTP_HOST or not SMTP_USER:
        return
    with get_db() as db:
        user = db.execute("SELECT email, username, watch_notify_enabled FROM users WHERE id = ?", [user_id]).fetchone()
    if not user or not user["email"] or not user["watch_notify_enabled"]:
        return
    # Throttle: max 1x pro Stunde
    now = time.time()
    if user_id in _notify_last_sent and now - _notify_last_sent[user_id] < 3600:
        return
    _notify_last_sent[user_id] = now
    job_rows = "".join(
        f'<tr><td style="padding:8px 12px;border-bottom:1px solid #1e1e30;">'
        f'<a href="{j["url"]}" style="color:#ff4d6d;text-decoration:none;font-weight:600;">{j["title"]}</a>'
        f'<br><span style="color:#6b6b80;font-size:12px;">{j.get("company_name", "")}</span></td></tr>'
        for j in new_jobs[:20]
    )
    more = f'<tr><td style="padding:8px 12px;color:#6b6b80;font-size:12px;">… und {len(new_jobs)-20} weitere</td></tr>' if len(new_jobs) > 20 else ""
    body = f"""
<div style="font-family:'Segoe UI',sans-serif;max-width:520px;margin:0 auto;background:#0a0a0f;color:#f0f0f5;border-radius:14px;padding:32px 28px;">
  <div style="font-size:22px;font-weight:900;margin-bottom:4px;background:linear-gradient(135deg,#ff4d6d,#ffd166);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">JobPipeline</div>
  <h3 style="margin:0 0 16px;color:#f0f0f5;font-size:18px;">🔔 {len(new_jobs)} neue Stellen gefunden</h3>
  <p style="color:#9090a0;line-height:1.6;margin-bottom:20px;">Der Karriere-Monitor hat neue Treffer für dich entdeckt:</p>
  <table style="width:100%;border-collapse:collapse;background:#111120;border-radius:10px;overflow:hidden;">
    {job_rows}{more}
  </table>
  <div style="text-align:center;margin:24px 0 16px;">
    <a href="{APP_URL}" style="background:linear-gradient(135deg,#ff4d6d,#c9184a);color:#fff;padding:13px 28px;border-radius:10px;text-decoration:none;font-weight:700;font-size:15px;display:inline-block;">Alle ansehen</a>
  </div>
  <p style="color:#6b6b80;font-size:11px;text-align:center;">
    <a href="{APP_URL}" style="color:#555570;">Benachrichtigungen verwalten</a>
  </p>
</div>"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"JobPipeline – {len(new_jobs)} neue Stellen gefunden"
    msg["From"]    = SMTP_FROM
    msg["To"]      = user["email"]
    msg.attach(MIMEText(body, "html"))
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASS)
            smtp.sendmail(SMTP_FROM, user["email"], msg.as_string())
        print(f"[Notify] E-Mail an {user['username']} gesendet ({len(new_jobs)} Jobs)", flush=True)
    except Exception as e:
        print(f"[Notify] E-Mail-Fehler für {user['username']}: {e}", flush=True)


def _notify_after_watch_check(user_id, new_count):
    """Prüft Benachrichtigungs-Einstellung und sendet ggf. sofort eine E-Mail."""
    if new_count <= 0:
        return
    with get_db() as db:
        user = db.execute(
            "SELECT watch_notify_enabled, watch_notify_frequency FROM users WHERE id = ?", [user_id]
        ).fetchone()
    if not user or not user["watch_notify_enabled"]:
        return
    if user["watch_notify_frequency"] == "instant":
        # Neue Jobs für diesen User laden
        with get_db() as db:
            jobs = [dict(r) for r in db.execute("""
                SELECT j.title, j.url, w.name AS company_name
                FROM watch_jobs j
                JOIN company_watches w ON w.id = j.company_id
                WHERE w.user_id = ? AND j.is_new = 1
                ORDER BY j.found_at DESC LIMIT 30
            """, [user_id]).fetchall()]
        if jobs:
            _send_watch_notification(user_id, jobs)


def _run_digest():
    """Sendet tägliche/wöchentliche Digest-E-Mails an Nutzer mit ungelesenen Watch-Jobs."""
    now = datetime.now(timezone.utc)
    with get_db() as db:
        users = db.execute("""
            SELECT u.id, u.watch_notify_frequency, u.watch_last_digest_at
            FROM users u
            WHERE u.watch_notify_enabled = 1
              AND u.watch_notify_frequency IN ('daily', 'weekly')
              AND u.email IS NOT NULL AND u.email != ''
        """).fetchall()
    for u in [dict(r) for r in users]:
        freq = u["watch_notify_frequency"]
        last = u["watch_last_digest_at"]
        delta = timedelta(days=1) if freq == "daily" else timedelta(weeks=1)
        if last and datetime.fromisoformat(last) + delta > now:
            continue
        with get_db() as db:
            jobs = [dict(r) for r in db.execute("""
                SELECT j.title, j.url, w.name AS company_name
                FROM watch_jobs j
                JOIN company_watches w ON w.id = j.company_id
                WHERE w.user_id = ? AND j.is_new = 1
                ORDER BY j.found_at DESC LIMIT 30
            """, [u["id"]]).fetchall()]
        if not jobs:
            continue
        _send_watch_notification(u["id"], jobs)
        with get_db() as db:
            db.execute("UPDATE users SET watch_last_digest_at = ? WHERE id = ?",
                       [now.isoformat(), u["id"]])


def _schedule_digest():
    """Startet Daemon-Thread für tägliche/wöchentliche Digest-E-Mails (prüft stündlich)."""
    def _loop():
        while True:
            time.sleep(3600)  # Stündlich prüfen
            try:
                _run_digest()
            except Exception as e:
                print(f"[Digest] Fehler: {e}", flush=True)
    threading.Thread(target=_loop, daemon=True, name="digest-mailer").start()


# ── Database ──────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    with get_db() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT UNIQUE NOT NULL COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                email         TEXT,
                created_at    TEXT DEFAULT (datetime('now'))
            )
        """)
        # Migration: email column for existing installations
        try:
            db.execute("ALTER TABLE users ADD COLUMN email TEXT")
        except Exception:
            pass
        db.execute("""
            CREATE TABLE IF NOT EXISTS user_data (
                user_id     INTEGER PRIMARY KEY,
                saved       TEXT NOT NULL DEFAULT '{}',
                ignored     TEXT NOT NULL DEFAULT '[]',
                jira_config TEXT NOT NULL DEFAULT '{}',
                updated_at  TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                token      TEXT PRIMARY KEY,
                user_id    INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        # Migrations: new columns for existing installations
        for col, definition in [
            ("is_admin",                "INTEGER NOT NULL DEFAULT 0"),
            ("is_locked",               "INTEGER NOT NULL DEFAULT 0"),
            ("watch_global_kw",         "TEXT DEFAULT '[]'"),
            ("watch_notify_enabled",    "INTEGER NOT NULL DEFAULT 1"),
            ("watch_notify_frequency",  "TEXT DEFAULT 'instant'"),
            ("watch_last_digest_at",    "TEXT"),
        ]:
            try:
                db.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
            except Exception:
                pass
        db.execute("""
            CREATE TABLE IF NOT EXISTS company_watches (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id              INTEGER NOT NULL,
                name                 TEXT NOT NULL,
                career_url           TEXT NOT NULL,
                keywords             TEXT NOT NULL DEFAULT '[]',
                active               INTEGER NOT NULL DEFAULT 1,
                check_interval_hours INTEGER NOT NULL DEFAULT 24,
                last_checked_at      TEXT,
                last_check_status    TEXT,
                created_at           TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS watch_jobs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id   INTEGER NOT NULL,
                title        TEXT NOT NULL,
                url          TEXT,
                found_at     TEXT DEFAULT (datetime('now')),
                last_seen_at TEXT DEFAULT (datetime('now')),
                is_new       INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (company_id) REFERENCES company_watches(id)
            )
        """)
        # ── Search Alerts ──
        db.execute("""
            CREATE TABLE IF NOT EXISTS saved_searches (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id              INTEGER NOT NULL,
                name                 TEXT NOT NULL,
                titles               TEXT NOT NULL DEFAULT '[]',
                location             TEXT,
                plz                  TEXT,
                km                   INTEGER NOT NULL DEFAULT 50,
                days                 INTEGER NOT NULL DEFAULT 7,
                remote_only          INTEGER NOT NULL DEFAULT 0,
                country              TEXT NOT NULL DEFAULT 'de',
                check_interval_hours INTEGER NOT NULL DEFAULT 6,
                active               INTEGER NOT NULL DEFAULT 1,
                notify_enabled       INTEGER NOT NULL DEFAULT 1,
                last_run_at          TEXT,
                last_run_status      TEXT,
                created_at           TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS alert_jobs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                search_id    INTEGER NOT NULL,
                job_key      TEXT NOT NULL,
                title        TEXT NOT NULL,
                company      TEXT,
                url          TEXT,
                location     TEXT,
                salary_min   INTEGER,
                salary_max   INTEGER,
                source       TEXT,
                found_at     TEXT DEFAULT (datetime('now')),
                is_new       INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (search_id) REFERENCES saved_searches(id)
            )
        """)
        # ── Company Boards (Greenhouse/Lever) ──
        db.execute("""
            CREATE TABLE IF NOT EXISTS company_boards (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id              INTEGER NOT NULL,
                provider             TEXT NOT NULL,
                slug                 TEXT NOT NULL,
                name                 TEXT,
                active               INTEGER NOT NULL DEFAULT 1,
                check_interval_hours INTEGER NOT NULL DEFAULT 24,
                last_checked_at      TEXT,
                last_check_status    TEXT,
                created_at           TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS board_jobs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id     INTEGER NOT NULL,
                title        TEXT NOT NULL,
                url          TEXT,
                location     TEXT,
                found_at     TEXT DEFAULT (datetime('now')),
                last_seen_at TEXT DEFAULT (datetime('now')),
                is_new       INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (board_id) REFERENCES company_boards(id)
            )
        """)
        # Indexes
        db.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_reset_tokens_user ON password_reset_tokens(user_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_reset_tokens_expires ON password_reset_tokens(expires_at)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_watches_user ON company_watches(user_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_watch_jobs_company ON watch_jobs(company_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_searches_user ON saved_searches(user_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_alert_jobs_search ON alert_jobs(search_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_boards_user ON company_boards(user_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_board_jobs_board ON board_jobs(board_id)")

    # Bootstrap: promote ADMIN_USER from env if set
    if ADMIN_USER:
        with get_db() as db:
            db.execute(
                "UPDATE users SET is_admin = 1 WHERE username = ? COLLATE NOCASE",
                [ADMIN_USER]
            )
        print(f"[init] Admin-Promotion: '{ADMIN_USER}'")

init_db()


# ── Helpers ──────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method == "OPTIONS":
            return "", 204
        if "user_id" not in session:
            return jsonify({"error": "Nicht angemeldet"}), 401
        return f(*args, **kwargs)
    return decorated

def _parse(r):
    """Safely parse Jira response – falls back to text if body isn't JSON."""
    try:
        return jsonify(r.json()), r.status_code
    except ValueError:
        print(f"[jira] Non-JSON response HTTP {r.status_code}: {r.text[:300]}")
        return jsonify({
            "errorMessages": [f"Unerwartete Antwort vom Server (HTTP {r.status_code})"],
            "detail": r.text[:300]
        }), r.status_code

def send_reset_email(to_email, reset_url):
    if not SMTP_HOST or not SMTP_USER:
        raise ValueError(
            "SMTP nicht konfiguriert – bitte SMTP_HOST, SMTP_USER, SMTP_PASSWORD in .env setzen"
        )
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "JobPipeline – Passwort zurücksetzen"
    msg["From"]    = SMTP_FROM
    msg["To"]      = to_email
    body = f"""
<div style="font-family:'Segoe UI',sans-serif;max-width:480px;margin:0 auto;background:#0a0a0f;color:#f0f0f5;border-radius:14px;padding:32px 28px;">
  <div style="font-size:22px;font-weight:900;margin-bottom:4px;background:linear-gradient(135deg,#ff4d6d,#ffd166);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">JobPipeline</div>
  <h3 style="margin:0 0 16px;color:#f0f0f5;font-size:18px;">Passwort zurücksetzen</h3>
  <p style="color:#9090a0;line-height:1.6;margin-bottom:24px;">Du hast eine Anfrage zum Zurücksetzen deines Passworts gestellt. Klicke auf den Button, um ein neues Passwort zu vergeben.</p>
  <div style="text-align:center;margin-bottom:28px;">
    <a href="{reset_url}" style="background:linear-gradient(135deg,#ff4d6d,#c9184a);color:#fff;padding:13px 28px;border-radius:10px;text-decoration:none;font-weight:700;font-size:15px;display:inline-block;">Passwort zurücksetzen</a>
  </div>
  <p style="color:#6b6b80;font-size:12px;line-height:1.6;">Dieser Link ist <strong style="color:#9090a0;">1 Stunde</strong> gültig. Falls du kein Passwort-Reset angefordert hast, ignoriere diese E-Mail.</p>
  <p style="color:#6b6b80;font-size:11px;word-break:break-all;">Link: {reset_url}</p>
</div>"""
    msg.attach(MIMEText(body, "html"))
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(SMTP_USER, SMTP_PASS)
        smtp.sendmail(SMTP_FROM, to_email, msg.as_string())


# ── CORS ──────────────────────────────────────────────────────────

@app.after_request
def add_cors(response):
    origin = request.headers.get("Origin", "")
    response.headers["Access-Control-Allow-Origin"]      = origin if origin else "*"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Allow-Headers"]     = "Content-Type, Authorization, X-Jira-Domain"
    response.headers["Access-Control-Allow-Methods"]     = "GET, POST, PATCH, DELETE, OPTIONS"
    return response


# ── Auth ──────────────────────────────────────────────────────────

@app.route("/auth/register", methods=["POST", "OPTIONS"])
def auth_register():
    if request.method == "OPTIONS":
        return "", 204
    data     = request.get_json(force=True)
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    email    = (data.get("email")    or "").strip().lower()
    if not username or not password:
        return jsonify({"error": "Benutzername und Passwort erforderlich"}), 400
    if len(username) < 3:
        return jsonify({"error": "Benutzername muss mindestens 3 Zeichen lang sein"}), 400
    if len(password) < 8:
        return jsonify({"error": "Passwort muss mindestens 8 Zeichen lang sein"}), 400
    if email and "@" not in email:
        return jsonify({"error": "Ungültige E-Mail-Adresse"}), 400
    pw_hash = generate_password_hash(password)
    try:
        with get_db() as db:
            db.execute(
                "INSERT INTO users (username, password_hash, email) VALUES (?, ?, ?)",
                [username, pw_hash, email or None]
            )
            user = db.execute(
                "SELECT id FROM users WHERE username = ? COLLATE NOCASE", [username]
            ).fetchone()
            db.execute("INSERT INTO user_data (user_id) VALUES (?)", [user["id"]])
        session.permanent = True
        session["user_id"]  = user["id"]
        session["username"] = username
        session["is_admin"] = False
        return jsonify({"ok": True, "username": username, "is_admin": False, "email": email})
    except sqlite3.IntegrityError:
        return jsonify({"error": "Benutzername bereits vergeben"}), 409


@app.route("/auth/login", methods=["POST", "OPTIONS"])
def auth_login():
    if request.method == "OPTIONS":
        return "", 204
    data     = request.get_json(force=True)
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    with get_db() as db:
        user = db.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE", [username]
        ).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Ungültiger Benutzername oder Passwort"}), 401
    if user["is_locked"]:
        return jsonify({"error": "Dieses Konto ist gesperrt. Bitte wende dich an einen Administrator."}), 403
    session.permanent = True
    session["user_id"]  = user["id"]
    session["username"] = user["username"]
    session["is_admin"] = bool(user["is_admin"])
    return jsonify({"ok": True, "username": user["username"], "is_admin": bool(user["is_admin"]), "email": user["email"] or ""})


@app.route("/auth/logout", methods=["POST", "OPTIONS"])
def auth_logout():
    if request.method == "OPTIONS":
        return "", 204
    session.clear()
    return jsonify({"ok": True})


@app.route("/auth/me")
def auth_me():
    if "user_id" not in session:
        return jsonify({"user": None})
    with get_db() as db:
        user = db.execute(
            "SELECT is_admin, is_locked, email FROM users WHERE id = ?", [session["user_id"]]
        ).fetchone()
    if not user or user["is_locked"]:
        session.clear()
        return jsonify({"user": None})
    session["is_admin"] = bool(user["is_admin"])
    return jsonify({"user": {
        "id":       session["user_id"],
        "username": session["username"],
        "is_admin": bool(user["is_admin"]),
        "email":    user["email"] or "",
    }})


@app.route("/auth/forgot", methods=["POST", "OPTIONS"])
def auth_forgot():
    if request.method == "OPTIONS":
        return "", 204
    data  = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    if not email:
        return jsonify({"error": "E-Mail-Adresse erforderlich"}), 400

    with get_db() as db:
        # Clean up expired tokens opportunistically
        db.execute(
            "DELETE FROM password_reset_tokens WHERE expires_at < ?",
            [datetime.now(timezone.utc).isoformat()]
        )
        user = db.execute(
            "SELECT * FROM users WHERE lower(email) = ?", [email]
        ).fetchone()

    if user:
        if not SMTP_HOST:
            return jsonify({"error": "E-Mail-Versand nicht konfiguriert (SMTP_HOST fehlt in .env)"}), 500
        token      = secrets.token_urlsafe(32)
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        with get_db() as db:
            db.execute("DELETE FROM password_reset_tokens WHERE user_id = ?", [user["id"]])
            db.execute(
                "INSERT INTO password_reset_tokens (token, user_id, expires_at) VALUES (?, ?, ?)",
                [token, user["id"], expires_at]
            )
        reset_url = f"{APP_URL}/?reset={token}"
        try:
            send_reset_email(email, reset_url)
        except Exception as e:
            print(f"[forgot] E-Mail-Fehler: {e}")
            return jsonify({"error": f"E-Mail konnte nicht gesendet werden: {e}"}), 500

    # Always return success to prevent user enumeration
    return jsonify({"ok": True})


@app.route("/auth/reset", methods=["POST", "OPTIONS"])
def auth_reset():
    if request.method == "OPTIONS":
        return "", 204
    data     = request.get_json(force=True)
    token    = (data.get("token")    or "").strip()
    password = (data.get("password") or "")
    if not token or not password:
        return jsonify({"error": "Token und Passwort erforderlich"}), 400
    if len(password) < 8:
        return jsonify({"error": "Passwort muss mindestens 8 Zeichen lang sein"}), 400

    with get_db() as db:
        row = db.execute(
            "SELECT * FROM password_reset_tokens WHERE token = ?", [token]
        ).fetchone()
    if not row:
        return jsonify({"error": "Ungültiger oder bereits verwendeter Reset-Link"}), 400
    if row["expires_at"] < datetime.now(timezone.utc).isoformat():
        with get_db() as db:
            db.execute("DELETE FROM password_reset_tokens WHERE token = ?", [token])
        return jsonify({"error": "Dieser Reset-Link ist abgelaufen (1 Stunde)"}), 400

    pw_hash = generate_password_hash(password)
    with get_db() as db:
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?", [pw_hash, row["user_id"]])
        db.execute("DELETE FROM password_reset_tokens WHERE token = ?", [token])
    return jsonify({"ok": True})


# ── User Data ─────────────────────────────────────────────────────

@app.route("/user/data", methods=["GET"])
@login_required
def get_user_data():
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM user_data WHERE user_id = ?", [session["user_id"]]
        ).fetchone()
    if not row:
        return jsonify({"saved": {}, "ignored": [], "jira": {}})
    return jsonify({
        "saved":   json.loads(row["saved"]),
        "ignored": json.loads(row["ignored"]),
        "jira":    json.loads(row["jira_config"])
    })


@app.route("/user/data", methods=["POST", "OPTIONS"])
@login_required
def save_user_data():
    data = request.get_json(force=True)
    with get_db() as db:
        db.execute("""
            INSERT INTO user_data (user_id, saved, ignored, jira_config)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                saved       = excluded.saved,
                ignored     = excluded.ignored,
                jira_config = excluded.jira_config,
                updated_at  = datetime('now')
        """, [
            session["user_id"],
            json.dumps(data.get("saved",   {})),
            json.dumps(data.get("ignored", [])),
            json.dumps(data.get("jira",    {}))
        ])
    return jsonify({"ok": True})


@app.route("/user/profile", methods=["PATCH"])
@login_required
def update_profile():
    data  = request.get_json(force=True)
    email = (data.get("email") or "").strip()
    with get_db() as db:
        db.execute("UPDATE users SET email=? WHERE id=?", [email, session["user_id"]])
    return jsonify({"ok": True, "email": email})


@app.route("/user/password", methods=["POST"])
@login_required
def change_password():
    data       = request.get_json(force=True)
    current_pw = data.get("current", "")
    new_pw     = data.get("new", "")
    if len(new_pw) < 8:
        return jsonify({"ok": False, "error": "Passwort muss mindestens 8 Zeichen haben"}), 400
    with get_db() as db:
        row = db.execute(
            "SELECT password_hash FROM users WHERE id=?", [session["user_id"]]
        ).fetchone()
    if not check_password_hash(row["password_hash"], current_pw):
        return jsonify({"ok": False, "error": "Aktuelles Passwort ist falsch"}), 400
    new_hash = generate_password_hash(new_pw)
    with get_db() as db:
        db.execute("UPDATE users SET password_hash=? WHERE id=?", [new_hash, session["user_id"]])
    return jsonify({"ok": True})


# ── Benachrichtigungs-Einstellungen ──────────────────────────────

@app.route("/user/notifications", methods=["GET"])
@login_required
def get_notifications():
    with get_db() as db:
        row = db.execute(
            "SELECT watch_notify_enabled, watch_notify_frequency FROM users WHERE id = ?",
            [session["user_id"]]
        ).fetchone()
    return jsonify({
        "enabled":   bool(row["watch_notify_enabled"]) if row else True,
        "frequency": row["watch_notify_frequency"] if row else "instant",
    })


@app.route("/user/notifications", methods=["PATCH"])
@login_required
def update_notifications():
    data = request.get_json(force=True)
    updates = {}
    if "enabled" in data:
        updates["watch_notify_enabled"] = 1 if data["enabled"] else 0
    if "frequency" in data and data["frequency"] in ("instant", "daily", "weekly"):
        updates["watch_notify_frequency"] = data["frequency"]
    if not updates:
        return jsonify({"error": "Keine gültigen Felder"}), 400
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [session["user_id"]]
    with get_db() as db:
        db.execute(f"UPDATE users SET {set_clause} WHERE id = ?", values)
    return jsonify({"ok": True})


# ── Synonyme (Spiegelbild der Frontend-Map für Search-Alerts) ─────

SYNONYMS = {
    "CTO":            ["Chief Technology Officer", "VP Engineering", "VP of Engineering", "Head of Engineering", "Technischer Geschäftsführer"],
    "CIO":            ["Chief Information Officer", "IT Director", "Director IT"],
    "CDO":            ["Chief Digital Officer", "Chief Data Officer", "Head of Digital"],
    "Head of IT":     ["IT-Leiter", "Leiter IT", "IT Director", "Director IT", "VP IT"],
    "Leiter IT":      ["IT-Leiter", "Head of IT", "IT Director"],
    "Direktor IT":    ["IT Director", "Director IT", "Head of IT"],
    "IT-Manager":     ["IT Manager", "IT Leader", "Senior IT Manager"],
    "VP of Engineering": ["VP Engineering", "Vice President Engineering", "Head of Engineering", "CTO"],
    "CISO":           ["Chief Information Security Officer", "Head of Security", "Head of InfoSec"],
    "CFO":            ["Chief Financial Officer", "Finanzchef", "Finanzleiter", "VP Finance"],
    "COO":            ["Chief Operating Officer", "Operations Director", "Head of Operations"],
    "CEO":            ["Chief Executive Officer", "Geschäftsführer", "Managing Director"],
    "Product Manager":["Produktmanager", "Senior Product Manager", "Head of Product"],
    "Data Scientist": ["Senior Data Scientist", "ML Engineer", "Machine Learning Engineer"],
    "DevOps Engineer":["Site Reliability Engineer", "SRE", "Platform Engineer", "Cloud Engineer"],
}

def expand_titles(arr):
    """Erweitert Jobtitel um bekannte Synonyme."""
    out = []
    seen = set()
    keys_lower = {k.lower(): k for k in SYNONYMS}
    for t in arr:
        if t not in seen:
            seen.add(t); out.append(t)
        key = keys_lower.get(t.lower())
        if key:
            for s in SYNONYMS[key]:
                if s not in seen:
                    seen.add(s); out.append(s)
    return out


# ── API-Cache ─────────────────────────────────────────────────────

_api_cache = {}
_API_CACHE_TTL  = int(os.environ.get("API_CACHE_TTL", "300"))   # Sekunden (5 Min)
_API_CACHE_MAX  = 200

def _cache_key(prefix, params):
    raw = prefix + json.dumps(params, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()

def _cached_api_get(cache_prefix, url, params, headers=None):
    """GET mit TTL-Cache. Gibt (data_dict, status_code) zurück."""
    key = _cache_key(cache_prefix, params)
    now = time.time()
    if key in _api_cache:
        ts, data, status = _api_cache[key]
        if now - ts < _API_CACHE_TTL:
            return data, status
    r = requests.get(url, params=params, headers=headers or {}, timeout=10)
    data, status = r.json(), r.status_code
    # Nur erfolgreiche Antworten cachen
    if status < 400:
        if len(_api_cache) >= _API_CACHE_MAX:
            oldest = min(_api_cache, key=lambda k: _api_cache[k][0])
            del _api_cache[oldest]
        _api_cache[key] = (now, data, status)
    return data, status


# ── Jobs (Adzuna proxy) ──────────────────────────────────────────

@app.route("/jobs")
def jobs():
    title    = request.args.get("what", "")
    location = request.args.get("where", "")
    radius   = request.args.get("distance", "50")
    country  = request.args.get("country", "de")
    params = {
        "app_id":           APP_ID,
        "app_key":          APP_KEY,
        "results_per_page": 20,
        "what":             title,
        "distance":         radius,
        "content-type":     "application/json",
    }
    if location:
        params["where"] = location
    url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
    try:
        data, status = _cached_api_get("adzuna", url, params)
        return jsonify(data), status
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Jobs (Bundesagentur für Arbeit proxy) ───────────────────────

@app.route("/jobs/ba")
def jobs_ba():
    title    = request.args.get("what", "")
    location = request.args.get("where", "")
    radius   = request.args.get("distance", "50")
    params = {
        "angebotsart": 1,
        "page":        1,
        "pav":         "false",
        "size":        25,
        "umkreis":     radius,
    }
    if title:    params["was"] = title
    if location: params["wo"]  = location
    try:
        data, status = _cached_api_get(
            "ba",
            "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/app/jobs",
            params,
            headers={"X-API-Key": "jobboerse-jobsuche"}
        )
        return jsonify(data), status
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Jobs (Jobicy proxy – Remote Jobs) ───────────────────────────

@app.route("/jobs/jobicy")
def jobs_jobicy():
    title   = request.args.get("what", "")
    country = request.args.get("country", "")
    geo_map = {"de": "germany", "at": "austria", "ch": "switzerland",
               "gb": "uk", "us": "usa"}
    params  = {"count": 50}
    if title:
        params["tag"] = title
    geo = geo_map.get(country, "")
    if geo:
        params["geo"] = geo
    try:
        data, status = _cached_api_get("jobicy", "https://jobicy.com/api/v2/remote-jobs", params)
        return jsonify(data), status
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Jobs (RemoteOK proxy – Remote Jobs) ─────────────────────────

@app.route("/jobs/remoteok")
def jobs_remoteok():
    """Liefert alle aktuellen RemoteOK-Jobs. Filterung nach Jobtitel passiert clientseitig."""
    try:
        # RemoteOK gibt ein Array zurück, erstes Element ist ein Meta-Objekt
        data, status = _cached_api_get("remoteok", "https://remoteok.com/api", {})
        jobs = [j for j in (data or []) if isinstance(j, dict) and "id" in j]
        return jsonify({"jobs": jobs, "count": len(jobs)}), status
    except Exception as e:
        return jsonify({"error": str(e), "jobs": [], "count": 0}), 500


# ── Jobs (The Muse proxy) ───────────────────────────────────────

@app.route("/jobs/muse")
def jobs_muse():
    category = request.args.get("category", "")
    location = request.args.get("location", "")
    page     = request.args.get("page", "1")
    params   = {"page": page}
    if category: params["category"] = category
    if location: params["location"] = location
    try:
        data, status = _cached_api_get("muse", "https://www.themuse.com/api/public/jobs", params)
        return jsonify(data), status
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Jira ──────────────────────────────────────────────────────────

@app.route("/jira/test", methods=["GET", "OPTIONS"])
def jira_test():
    if request.method == "OPTIONS":
        return "", 204
    domain = request.headers.get("X-Jira-Domain", "").strip()
    auth   = request.headers.get("Authorization", "")
    print(f"[jira/test] domain={domain!r} auth_present={bool(auth)}")
    if not domain or not auth:
        return jsonify({"errorMessages": ["Fehlende Header: X-Jira-Domain oder Authorization"]}), 400
    url = f"https://{domain}/rest/api/3/myself"
    try:
        r = requests.get(
            url, headers={"Authorization": auth, "Accept": "application/json"}, timeout=10
        )
        print(f"[jira/test] HTTP {r.status_code}")
        return _parse(r)
    except Exception as e:
        print(f"[jira/test] Exception: {e}")
        return jsonify({"errorMessages": [str(e)]}), 500


@app.route("/jira/fields", methods=["GET", "OPTIONS"])
def jira_fields():
    if request.method == "OPTIONS":
        return "", 204
    domain    = request.headers.get("X-Jira-Domain", "").strip()
    auth      = request.headers.get("Authorization", "")
    project   = request.args.get("project", "")
    issuetype = request.args.get("issuetype", "")
    print(f"[jira/fields] domain={domain!r} project={project!r} issuetype={issuetype!r}")
    if not domain or not auth or not project:
        return jsonify({"error": "Fehlende Parameter"}), 400
    if issuetype:
        url = f"https://{domain}/rest/api/3/issue/createmeta/{project}/issuetypes/{issuetype}"
    else:
        url = f"https://{domain}/rest/api/3/issue/createmeta/{project}/issuetypes"
    try:
        r = requests.get(
            url, headers={"Authorization": auth, "Accept": "application/json"}, timeout=10
        )
        print(f"[jira/fields] HTTP {r.status_code}")
        return _parse(r)
    except Exception as e:
        print(f"[jira/fields] Exception: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/jira/issue", methods=["POST", "OPTIONS"])
def jira_issue():
    if request.method == "OPTIONS":
        return "", 204
    domain = request.headers.get("X-Jira-Domain", "").strip()
    auth   = request.headers.get("Authorization", "")
    print(f"[jira/issue] domain={domain!r} auth_present={bool(auth)}")
    if not domain or not auth:
        return jsonify({"errorMessages": ["Fehlende Header: X-Jira-Domain oder Authorization"]}), 400
    url = f"https://{domain}/rest/api/3/issue"
    try:
        r = requests.post(
            url,
            json=request.get_json(force=True),
            headers={
                "Authorization": auth,
                "Content-Type":  "application/json",
                "Accept":        "application/json",
            },
            timeout=15,
        )
        print(f"[jira/issue] HTTP {r.status_code}")
        if r.status_code >= 400:
            print(f"[jira/issue] Error body: {r.text[:500]}")
        return _parse(r)
    except Exception as e:
        print(f"[jira/issue] Exception: {e}")
        return jsonify({"errorMessages": [str(e)]}), 500


# ── Admin ─────────────────────────────────────────────────────────

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method == "OPTIONS":
            return "", 204
        if "user_id" not in session:
            return jsonify({"error": "Nicht angemeldet"}), 401
        if not session.get("is_admin"):
            return jsonify({"error": "Keine Administratorrechte"}), 403
        return f(*args, **kwargs)
    return decorated


@app.route("/admin/users", methods=["GET", "OPTIONS"])
@admin_required
def admin_list_users():
    with get_db() as db:
        rows = db.execute(
            "SELECT id, username, email, is_admin, is_locked, created_at FROM users ORDER BY created_at DESC"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/admin/users/<int:uid>", methods=["PATCH", "OPTIONS"])
@admin_required
def admin_update_user(uid):
    if request.method == "OPTIONS":
        return "", 204
    data = request.get_json(force=True)
    allowed = {"email", "is_locked", "is_admin"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({"error": "Keine gültigen Felder"}), 400

    # Admins dürfen sich nicht selbst sperren oder Adminrechte entziehen
    if uid == session["user_id"]:
        if "is_locked" in updates and updates["is_locked"]:
            return jsonify({"error": "Du kannst dich nicht selbst sperren"}), 400
        if "is_admin" in updates and not updates["is_admin"]:
            return jsonify({"error": "Du kannst dir nicht selbst die Adminrechte entziehen"}), 400

    if "email" in updates:
        email = (updates["email"] or "").strip().lower()
        if email and "@" not in email:
            return jsonify({"error": "Ungültige E-Mail-Adresse"}), 400
        updates["email"] = email or None

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [uid]
    with get_db() as db:
        db.execute(f"UPDATE users SET {set_clause} WHERE id = ?", values)
    return jsonify({"ok": True})


@app.route("/admin/users/<int:uid>", methods=["DELETE", "OPTIONS"])
@admin_required
def admin_delete_user(uid):
    if request.method == "OPTIONS":
        return "", 204
    if uid == session["user_id"]:
        return jsonify({"error": "Du kannst dich nicht selbst löschen"}), 400
    with get_db() as db:
        db.execute("DELETE FROM alert_jobs WHERE search_id IN (SELECT id FROM saved_searches WHERE user_id = ?)", [uid])
        db.execute("DELETE FROM saved_searches WHERE user_id = ?", [uid])
        db.execute("DELETE FROM board_jobs WHERE board_id IN (SELECT id FROM company_boards WHERE user_id = ?)", [uid])
        db.execute("DELETE FROM company_boards WHERE user_id = ?", [uid])
        db.execute("DELETE FROM watch_jobs WHERE company_id IN (SELECT id FROM company_watches WHERE user_id = ?)", [uid])
        db.execute("DELETE FROM company_watches WHERE user_id = ?", [uid])
        db.execute("DELETE FROM user_data WHERE user_id = ?", [uid])
        db.execute("DELETE FROM password_reset_tokens WHERE user_id = ?", [uid])
        db.execute("DELETE FROM users WHERE id = ?", [uid])
    return jsonify({"ok": True})


# ── Backup / Restore ──────────────────────────────────────────────

@app.route("/admin/backup", methods=["GET", "OPTIONS"])
@admin_required
def admin_backup():
    if request.method == "OPTIONS":
        return "", 204
    return jsonify(_build_backup_payload())


@app.route("/admin/restore", methods=["POST", "OPTIONS"])
@admin_required
def admin_restore():
    if request.method == "OPTIONS":
        return "", 204
    data = request.get_json(force=True)
    if not isinstance(data, dict) or "users" not in data or data.get("app") != "JobPipeline":
        return jsonify({"error": "Ungültiges oder inkompatibles Backup-Format"}), 400
    users     = data.get("users", [])
    user_data = data.get("user_data", [])
    watches   = data.get("company_watches", [])
    wjobs     = data.get("watch_jobs", [])
    try:
        with get_db() as db:
            db.execute("DELETE FROM watch_jobs")
            db.execute("DELETE FROM company_watches")
            db.execute("DELETE FROM password_reset_tokens")
            db.execute("DELETE FROM user_data")
            db.execute("DELETE FROM users")
            for u in users:
                db.execute(
                    "INSERT INTO users (id, username, password_hash, email, is_admin, is_locked, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [u["id"], u["username"], u["password_hash"],
                     u.get("email"), int(u.get("is_admin", 0)),
                     int(u.get("is_locked", 0)), u.get("created_at")]
                )
            for ud in user_data:
                db.execute(
                    "INSERT INTO user_data (user_id, saved, ignored, jira_config) VALUES (?, ?, ?, ?)",
                    [ud["user_id"], ud.get("saved", "{}"),
                     ud.get("ignored", "[]"), ud.get("jira_config", "{}")]
                )
            for w in watches:
                db.execute(
                    "INSERT INTO company_watches (id, user_id, name, career_url, keywords, active, "
                    "check_interval_hours, last_checked_at, last_check_status, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [w["id"], w["user_id"], w["name"], w["career_url"], w.get("keywords", "[]"),
                     int(w.get("active", 1)), int(w.get("check_interval_hours", 24)),
                     w.get("last_checked_at"), w.get("last_check_status"), w.get("created_at")]
                )
            for wj in wjobs:
                db.execute(
                    "INSERT INTO watch_jobs (id, company_id, title, url, found_at, last_seen_at, is_new) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [wj["id"], wj["company_id"], wj["title"], wj.get("url"),
                     wj.get("found_at"), wj.get("last_seen_at"), int(wj.get("is_new", 1))]
                )
        session.clear()
        return jsonify({"ok": True, "users": len(users)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/admin/backups", methods=["GET"])
@admin_required
def list_backups():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    files = sorted(glob.glob(os.path.join(BACKUP_DIR, "backup_*.json")), reverse=True)
    result = []
    for f in files:
        stat = os.stat(f)
        result.append({
            "name": os.path.basename(f),
            "size": stat.st_size,
            "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        })
    return jsonify(result)


@app.route("/admin/backups/<filename>", methods=["GET"])
@admin_required
def download_backup(filename):
    if not re.match(r'^backup_[\d_-]+\.json$', filename):
        return jsonify({"error": "Ungültiger Dateiname"}), 400
    path = os.path.join(BACKUP_DIR, filename)
    if not os.path.isfile(path):
        return jsonify({"error": "Datei nicht gefunden"}), 404
    return send_file(path, as_attachment=True, download_name=filename, mimetype="application/json")


@app.route("/admin/backups/trigger", methods=["POST"])
@admin_required
def trigger_backup():
    try:
        path = _make_backup()
        return jsonify({"ok": True, "file": os.path.basename(path)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Karriere-Monitor: Routen ──────────────────────────────────────

@app.route("/watch/companies", methods=["GET", "OPTIONS"])
@login_required
def watch_list():
    uid = session["user_id"]
    with get_db() as db:
        rows = db.execute("""
            SELECT w.*, COUNT(j.id) AS total_jobs,
                   SUM(j.is_new) AS new_jobs
            FROM company_watches w
            LEFT JOIN watch_jobs j ON j.company_id = w.id
            WHERE w.user_id = ?
            GROUP BY w.id
            ORDER BY w.created_at DESC
        """, [uid]).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/watch/companies", methods=["POST"])
@login_required
def watch_create():
    uid  = session["user_id"]
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    url  = (data.get("career_url") or "").strip()
    if not name or not url:
        return jsonify({"error": "Name und URL sind Pflichtfelder"}), 400
    keywords = json.dumps([k.strip() for k in data.get("keywords", []) if str(k).strip()])
    interval = int(data.get("check_interval_hours", 24))
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO company_watches (user_id, name, career_url, keywords, check_interval_hours) "
            "VALUES (?, ?, ?, ?, ?)",
            [uid, name, url, keywords, interval]
        )
        row = db.execute("SELECT * FROM company_watches WHERE id = ?", [cur.lastrowid]).fetchone()
    return jsonify(dict(row)), 201


@app.route("/watch/companies/<int:wid>", methods=["PATCH", "OPTIONS"])
@login_required
def watch_update(wid):
    uid  = session["user_id"]
    data = request.get_json(force=True) or {}
    with get_db() as db:
        row = db.execute("SELECT id FROM company_watches WHERE id = ? AND user_id = ?", [wid, uid]).fetchone()
        if not row:
            return jsonify({"error": "Nicht gefunden"}), 404
        allowed = {"name", "career_url", "keywords", "active", "check_interval_hours"}
        for field, val in data.items():
            if field not in allowed:
                continue
            if field == "keywords":
                val = json.dumps([k.strip() for k in val if str(k).strip()])
            db.execute(f"UPDATE company_watches SET {field} = ? WHERE id = ?", [val, wid])
    return jsonify({"ok": True})


@app.route("/watch/companies/<int:wid>", methods=["DELETE", "OPTIONS"])
@login_required
def watch_delete(wid):
    uid = session["user_id"]
    with get_db() as db:
        row = db.execute("SELECT id FROM company_watches WHERE id = ? AND user_id = ?", [wid, uid]).fetchone()
        if not row:
            return jsonify({"error": "Nicht gefunden"}), 404
        db.execute("DELETE FROM watch_jobs WHERE company_id = ?", [wid])
        db.execute("DELETE FROM company_watches WHERE id = ?", [wid])
    return jsonify({"ok": True})


@app.route("/watch/companies/<int:wid>/check", methods=["POST", "OPTIONS"])
@login_required
def watch_check_now(wid):
    uid = session["user_id"]
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM company_watches WHERE id = ? AND user_id = ?", [wid, uid]
        ).fetchone()
        if not row:
            return jsonify({"error": "Nicht gefunden"}), 404
        w = dict(row)
    merged_kw = _merge_kw(_get_global_kw(uid), json.loads(w["keywords"]))
    try:
        jobs = _scrape_career_page(w["career_url"], merged_kw)
        new_count = _save_watch_results(wid, jobs)
        _notify_after_watch_check(uid, new_count)
        return jsonify({"ok": True, "total": len(jobs), "new": new_count})
    except Exception as e:
        _mark_watch_error(wid, e)
        return jsonify({"error": str(e)}), 500


@app.route("/watch/jobs", methods=["GET", "OPTIONS"])
@login_required
def watch_jobs_list():
    uid     = session["user_id"]
    new_only = request.args.get("new") == "1"
    query = """
        SELECT j.*, w.name AS company_name, w.career_url
        FROM watch_jobs j
        JOIN company_watches w ON w.id = j.company_id
        WHERE w.user_id = ?
    """
    params = [uid]
    if new_only:
        query += " AND j.is_new = 1"
    query += " ORDER BY j.found_at DESC LIMIT 200"
    with get_db() as db:
        rows = db.execute(query, params).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/watch/jobs/<int:jid>", methods=["DELETE", "OPTIONS"])
@login_required
def watch_job_delete(jid):
    uid = session["user_id"]
    with get_db() as db:
        row = db.execute(
            "SELECT j.id FROM watch_jobs j "
            "JOIN company_watches w ON w.id = j.company_id "
            "WHERE j.id = ? AND w.user_id = ?", [jid, uid]
        ).fetchone()
        if not row:
            return jsonify({"error": "Nicht gefunden"}), 404
        db.execute("DELETE FROM watch_jobs WHERE id = ?", [jid])
    return jsonify({"ok": True})


@app.route("/watch/jobs/read-all", methods=["POST", "OPTIONS"])
@login_required
def watch_jobs_read_all():
    uid = session["user_id"]
    with get_db() as db:
        db.execute("""
            UPDATE watch_jobs SET is_new = 0
            WHERE company_id IN (SELECT id FROM company_watches WHERE user_id = ?)
        """, [uid])
    return jsonify({"ok": True})


@app.route("/watch/keywords", methods=["GET", "OPTIONS"])
@login_required
def watch_keywords_get():
    uid = session["user_id"]
    return jsonify({"keywords": _get_global_kw(uid)})


@app.route("/watch/keywords", methods=["PATCH", "OPTIONS"])
@login_required
def watch_keywords_update():
    uid  = session["user_id"]
    data = request.get_json(force=True) or {}
    kw   = json.dumps([k.strip() for k in data.get("keywords", []) if str(k).strip()])
    with get_db() as db:
        db.execute("UPDATE users SET watch_global_kw = ? WHERE id = ?", [kw, uid])
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════════════
# Search Alerts
# ══════════════════════════════════════════════════════════════════

def _job_key(j):
    """Eindeutiger Key für Dedup. Nutzt URL oder Titel+Company."""
    url = (j.get("redirect_url") or j.get("url") or "").strip()
    if url:
        return url[:180]
    return ((j.get("title", "") + "|" + (j.get("company", {}).get("display_name", "") if isinstance(j.get("company"), dict) else (j.get("company") or "")))[:180])


def _fetch_jobs_for_search(s):
    """Führt eine gespeicherte Suche aus und gibt eine Liste normalisierter Jobs zurück."""
    titles = json.loads(s["titles"] or "[]")
    expanded = expand_titles(titles)
    location = s["location"] or ""
    plz      = s["plz"] or ""
    where    = (plz + " " + location).strip() if plz else location
    country  = s["country"] or "de"
    remote_only = bool(s["remote_only"])
    cutoff_days = s["days"] or 7
    radius = s["km"] or 50

    found = []
    for title in expanded:
        # Adzuna
        try:
            params = {"app_id": APP_ID, "app_key": APP_KEY, "results_per_page": 20,
                      "what": (title + " remote") if remote_only else title,
                      "distance": radius, "content-type": "application/json"}
            if where: params["where"] = where
            url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
            data, _ = _cached_api_get("adzuna", url, params)
            for j in (data.get("results") or []):
                if remote_only:
                    text = (j.get("title", "") + " " + j.get("description", "")).lower()
                    if "remote" not in text:
                        continue
                found.append({"title": j.get("title", ""), "company": (j.get("company") or {}).get("display_name", ""),
                              "url": j.get("redirect_url", ""), "location": (j.get("location") or {}).get("display_name", ""),
                              "salary_min": j.get("salary_min"), "salary_max": j.get("salary_max"),
                              "source": "Adzuna", "created": j.get("created", "")})
        except Exception as e:
            print(f"[Alert] Adzuna-Fehler: {e}", flush=True)

        # BA (nur DE, nicht remote)
        if not remote_only and country == "de":
            try:
                ba_params = {"angebotsart": 1, "page": 1, "pav": "false", "size": 25, "umkreis": radius, "was": title}
                if where: ba_params["wo"] = where
                data, _ = _cached_api_get("ba",
                    "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/app/jobs",
                    ba_params, headers={"X-API-Key": "jobboerse-jobsuche"})
                for j in (data.get("stellenangebote") or []):
                    refnr = j.get("refnr", "")
                    loc_obj = j.get("arbeitsort") or {}
                    found.append({
                        "title": j.get("titel", ""),
                        "company": j.get("arbeitgeber", ""),
                        "url": j.get("externeUrl") or (f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}" if refnr else ""),
                        "location": ", ".join(filter(None, [loc_obj.get("ort"), loc_obj.get("region")])),
                        "salary_min": None, "salary_max": None,
                        "source": "BA", "created": j.get("aktuelleVeroeffentlichungsdatum", "")
                    })
            except Exception as e:
                print(f"[Alert] BA-Fehler: {e}", flush=True)

    # Cutoff nach Datum
    if cutoff_days > 0:
        cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=cutoff_days)).isoformat()
        found = [j for j in found if not j.get("created") or j["created"] >= cutoff_iso[:10]]

    return found


def _save_alert_results(search_id, jobs):
    """Vergleicht mit existierenden alert_jobs, fügt neue ein. Gibt new_count zurück."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as db:
        existing = {r["job_key"] for r in db.execute(
            "SELECT job_key FROM alert_jobs WHERE search_id = ?", [search_id]
        ).fetchall()}
        new_count = 0
        for j in jobs:
            key = (j.get("url") or (j.get("title", "") + "|" + (j.get("company") or "")))[:180]
            if key in existing:
                continue
            db.execute("""
                INSERT INTO alert_jobs (search_id, job_key, title, company, url, location,
                                        salary_min, salary_max, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [search_id, key, j.get("title", ""), j.get("company", ""), j.get("url", ""),
                  j.get("location", ""), j.get("salary_min"), j.get("salary_max"), j.get("source", "")])
            new_count += 1
        db.execute(
            "UPDATE saved_searches SET last_run_at = ?, last_run_status = 'ok' WHERE id = ?",
            [now, search_id]
        )
    return new_count


def _mark_alert_error(search_id, error):
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as db:
        db.execute(
            "UPDATE saved_searches SET last_run_at = ?, last_run_status = ? WHERE id = ?",
            [now, f"error: {str(error)[:200]}", search_id]
        )


def _send_alert_notification(user_id, search_name, new_jobs):
    """Sendet eine E-Mail mit neuen Alert-Treffern."""
    if not SMTP_HOST or not SMTP_USER:
        return
    with get_db() as db:
        user = db.execute("SELECT email, username, watch_notify_enabled FROM users WHERE id = ?", [user_id]).fetchone()
    if not user or not user["email"] or not user["watch_notify_enabled"]:
        return
    now = time.time()
    if user_id in _notify_last_sent and now - _notify_last_sent[user_id] < 3600:
        return
    _notify_last_sent[user_id] = now
    job_rows = "".join(
        f'<tr><td style="padding:8px 12px;border-bottom:1px solid #1e1e30;">'
        f'<a href="{j.get("url", "#")}" style="color:#ca98ff;text-decoration:none;font-weight:600;">{j.get("title", "")}</a>'
        f'<br><span style="color:#c1a0cb;font-size:12px;">{j.get("company", "")} · {j.get("source", "")}</span></td></tr>'
        for j in new_jobs[:20]
    )
    more = f'<tr><td style="padding:8px 12px;color:#c1a0cb;font-size:12px;">… und {len(new_jobs)-20} weitere</td></tr>' if len(new_jobs) > 20 else ""
    body = f"""
<div style="font-family:'Inter',sans-serif;max-width:520px;margin:0 auto;background:#1a0425;color:#f9dcff;border-radius:14px;padding:32px 28px;">
  <div style="font-size:22px;font-weight:900;margin-bottom:4px;background:linear-gradient(135deg,#ca98ff,#00bdfd);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">JobPipeline</div>
  <h3 style="margin:0 0 16px;color:#f9dcff;font-size:18px;">🔔 {len(new_jobs)} neue Treffer für „{search_name}"</h3>
  <p style="color:#c1a0cb;line-height:1.6;margin-bottom:20px;">Deine gespeicherte Suche hat neue Stellen gefunden:</p>
  <table style="width:100%;border-collapse:collapse;background:#290c36;border-radius:10px;overflow:hidden;">
    {job_rows}{more}
  </table>
  <div style="text-align:center;margin:24px 0 16px;">
    <a href="{APP_URL}" style="background:linear-gradient(135deg,#9c42f4,#00bdfd);color:#fff;padding:13px 28px;border-radius:10px;text-decoration:none;font-weight:700;font-size:15px;display:inline-block;">Alle ansehen</a>
  </div>
  <p style="color:#c1a0cb;font-size:11px;text-align:center;">
    <a href="{APP_URL}" style="color:#896b93;">Benachrichtigungen verwalten</a>
  </p>
</div>"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"JobPipeline – {len(new_jobs)} neue Treffer für „{search_name}\""
    msg["From"]    = SMTP_FROM
    msg["To"]      = user["email"]
    msg.attach(MIMEText(body, "html"))
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.ehlo(); smtp.starttls(); smtp.login(SMTP_USER, SMTP_PASS)
            smtp.sendmail(SMTP_FROM, user["email"], msg.as_string())
        print(f"[Alert] E-Mail an {user['username']} ({len(new_jobs)} Jobs für „{search_name}\")", flush=True)
    except Exception as e:
        print(f"[Alert] E-Mail-Fehler: {e}", flush=True)


def _run_alert_checks():
    """Prüft alle fälligen aktiven Alerts."""
    with get_db() as db:
        due = [dict(r) for r in db.execute("""
            SELECT * FROM saved_searches WHERE active = 1
            AND (last_run_at IS NULL
              OR datetime(last_run_at, '+' || check_interval_hours || ' hours') <= datetime('now'))
        """).fetchall()]
    for s in due:
        try:
            jobs = _fetch_jobs_for_search(s)
            new_count = _save_alert_results(s["id"], jobs)
            print(f"[Alert] „{s['name']}\" geprüft – {len(jobs)} Treffer ({new_count} neu)", flush=True)
            if new_count > 0 and s["notify_enabled"]:
                # Neue Jobs für die Mail laden
                with get_db() as db:
                    new_jobs = [dict(r) for r in db.execute(
                        "SELECT title, company, url, source FROM alert_jobs WHERE search_id = ? AND is_new = 1 ORDER BY found_at DESC LIMIT 30",
                        [s["id"]]
                    ).fetchall()]
                _send_alert_notification(s["user_id"], s["name"], new_jobs)
        except Exception as e:
            _mark_alert_error(s["id"], e)
            print(f"[Alert] Fehler bei „{s['name']}\": {e}", flush=True)


def _schedule_alert_checks():
    def _loop():
        while True:
            time.sleep(WATCH_INTERVAL_MINUTES * 60)
            try:
                _run_alert_checks()
            except Exception as e:
                print(f"[Alert] Scheduler-Fehler: {e}", flush=True)
    threading.Thread(target=_loop, daemon=True, name="alert-checker").start()


@app.route("/search/alerts", methods=["GET", "OPTIONS"])
@login_required
def alerts_list():
    uid = session["user_id"]
    with get_db() as db:
        rows = db.execute("""
            SELECT s.*,
                   COUNT(j.id) AS total_jobs,
                   SUM(j.is_new) AS new_jobs
            FROM saved_searches s
            LEFT JOIN alert_jobs j ON j.search_id = s.id
            WHERE s.user_id = ?
            GROUP BY s.id
            ORDER BY s.created_at DESC
        """, [uid]).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/search/alerts", methods=["POST"])
@login_required
def alerts_create():
    uid  = session["user_id"]
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name ist Pflicht"}), 400
    titles = json.dumps([t.strip() for t in (data.get("titles") or []) if str(t).strip()])
    with get_db() as db:
        cur = db.execute("""
            INSERT INTO saved_searches (user_id, name, titles, location, plz, km, days,
                                        remote_only, country, check_interval_hours, notify_enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [uid, name, titles, data.get("location", ""), data.get("plz", ""),
              int(data.get("km", 50)), int(data.get("days", 7)),
              1 if data.get("remote_only") else 0, data.get("country", "de"),
              int(data.get("check_interval_hours", 6)),
              1 if data.get("notify_enabled", True) else 0])
        row = db.execute("SELECT * FROM saved_searches WHERE id = ?", [cur.lastrowid]).fetchone()
    return jsonify(dict(row)), 201


@app.route("/search/alerts/<int:sid>", methods=["PATCH", "OPTIONS"])
@login_required
def alerts_update(sid):
    uid  = session["user_id"]
    data = request.get_json(force=True) or {}
    with get_db() as db:
        row = db.execute("SELECT id FROM saved_searches WHERE id = ? AND user_id = ?", [sid, uid]).fetchone()
        if not row:
            return jsonify({"error": "Nicht gefunden"}), 404
        allowed = {"name", "active", "notify_enabled", "check_interval_hours"}
        for field, val in data.items():
            if field in allowed:
                db.execute(f"UPDATE saved_searches SET {field} = ? WHERE id = ?", [val, sid])
    return jsonify({"ok": True})


@app.route("/search/alerts/<int:sid>", methods=["DELETE", "OPTIONS"])
@login_required
def alerts_delete(sid):
    uid = session["user_id"]
    with get_db() as db:
        row = db.execute("SELECT id FROM saved_searches WHERE id = ? AND user_id = ?", [sid, uid]).fetchone()
        if not row:
            return jsonify({"error": "Nicht gefunden"}), 404
        db.execute("DELETE FROM alert_jobs WHERE search_id = ?", [sid])
        db.execute("DELETE FROM saved_searches WHERE id = ?", [sid])
    return jsonify({"ok": True})


@app.route("/search/alerts/<int:sid>/run", methods=["POST", "OPTIONS"])
@login_required
def alerts_run_now(sid):
    uid = session["user_id"]
    with get_db() as db:
        row = db.execute("SELECT * FROM saved_searches WHERE id = ? AND user_id = ?", [sid, uid]).fetchone()
        if not row:
            return jsonify({"error": "Nicht gefunden"}), 404
        s = dict(row)
    try:
        jobs = _fetch_jobs_for_search(s)
        new_count = _save_alert_results(sid, jobs)
        return jsonify({"ok": True, "total": len(jobs), "new": new_count})
    except Exception as e:
        _mark_alert_error(sid, e)
        return jsonify({"error": str(e)}), 500


@app.route("/search/alerts/<int:sid>/jobs", methods=["GET", "OPTIONS"])
@login_required
def alerts_jobs(sid):
    uid = session["user_id"]
    with get_db() as db:
        row = db.execute("SELECT id FROM saved_searches WHERE id = ? AND user_id = ?", [sid, uid]).fetchone()
        if not row:
            return jsonify({"error": "Nicht gefunden"}), 404
        jobs = db.execute(
            "SELECT * FROM alert_jobs WHERE search_id = ? ORDER BY found_at DESC LIMIT 200", [sid]
        ).fetchall()
    return jsonify([dict(r) for r in jobs])


@app.route("/search/alerts/<int:sid>/read-all", methods=["POST", "OPTIONS"])
@login_required
def alerts_read_all(sid):
    uid = session["user_id"]
    with get_db() as db:
        row = db.execute("SELECT id FROM saved_searches WHERE id = ? AND user_id = ?", [sid, uid]).fetchone()
        if not row:
            return jsonify({"error": "Nicht gefunden"}), 404
        db.execute("UPDATE alert_jobs SET is_new = 0 WHERE search_id = ?", [sid])
    return jsonify({"ok": True})


@app.route("/search/alerts/jobs/<int:jid>", methods=["DELETE", "OPTIONS"])
@login_required
def alerts_job_delete(jid):
    uid = session["user_id"]
    with get_db() as db:
        row = db.execute(
            "SELECT j.id FROM alert_jobs j JOIN saved_searches s ON s.id = j.search_id WHERE j.id = ? AND s.user_id = ?",
            [jid, uid]
        ).fetchone()
        if not row:
            return jsonify({"error": "Nicht gefunden"}), 404
        db.execute("DELETE FROM alert_jobs WHERE id = ?", [jid])
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════════════
# Company Boards (Greenhouse / Lever)
# ══════════════════════════════════════════════════════════════════

def _fetch_greenhouse_jobs(slug):
    """Lädt Jobs von Greenhouse-Board."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()
    return [{
        "title":    j.get("title", ""),
        "url":      j.get("absolute_url", ""),
        "location": (j.get("location") or {}).get("name", ""),
    } for j in (data.get("jobs") or [])]


def _fetch_lever_jobs(slug):
    """Lädt Jobs von Lever-Board."""
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()
    return [{
        "title":    j.get("text", ""),
        "url":      j.get("hostedUrl", ""),
        "location": (j.get("categories") or {}).get("location", ""),
    } for j in (data or [])]


def _save_board_results(board_id, jobs):
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as db:
        existing = {r["url"] for r in db.execute(
            "SELECT url FROM board_jobs WHERE board_id = ?", [board_id]
        ).fetchall()}
        new_count = 0
        for j in jobs:
            if j["url"] not in existing:
                db.execute(
                    "INSERT INTO board_jobs (board_id, title, url, location) VALUES (?, ?, ?, ?)",
                    [board_id, j["title"], j["url"], j.get("location", "")]
                )
                new_count += 1
            else:
                db.execute(
                    "UPDATE board_jobs SET last_seen_at = ? WHERE board_id = ? AND url = ?",
                    [now, board_id, j["url"]]
                )
        db.execute(
            "UPDATE company_boards SET last_checked_at = ?, last_check_status = 'ok' WHERE id = ?",
            [now, board_id]
        )
    return new_count


def _check_board(board):
    """Lädt Jobs für ein Board, speichert neue. Gibt new_count zurück."""
    if board["provider"] == "greenhouse":
        jobs = _fetch_greenhouse_jobs(board["slug"])
    elif board["provider"] == "lever":
        jobs = _fetch_lever_jobs(board["slug"])
    else:
        raise ValueError(f"Unbekannter Provider: {board['provider']}")
    return _save_board_results(board["id"], jobs), len(jobs)


def _run_board_checks():
    """Prüft alle fälligen aktiven Boards."""
    with get_db() as db:
        due = [dict(r) for r in db.execute("""
            SELECT * FROM company_boards WHERE active = 1
            AND (last_checked_at IS NULL
              OR datetime(last_checked_at, '+' || check_interval_hours || ' hours') <= datetime('now'))
        """).fetchall()]
    for b in due:
        try:
            new_count, total = _check_board(b)
            print(f"[Board] {b['provider']}/{b['slug']} – {total} Jobs ({new_count} neu)", flush=True)
        except Exception as e:
            now = datetime.now(timezone.utc).isoformat()
            with get_db() as db:
                db.execute(
                    "UPDATE company_boards SET last_checked_at = ?, last_check_status = ? WHERE id = ?",
                    [now, f"error: {str(e)[:200]}", b["id"]]
                )
            print(f"[Board] Fehler bei {b['provider']}/{b['slug']}: {e}", flush=True)


@app.route("/boards", methods=["GET", "OPTIONS"])
@login_required
def boards_list():
    uid = session["user_id"]
    with get_db() as db:
        rows = db.execute("""
            SELECT b.*, COUNT(j.id) AS total_jobs, SUM(j.is_new) AS new_jobs
            FROM company_boards b
            LEFT JOIN board_jobs j ON j.board_id = b.id
            WHERE b.user_id = ?
            GROUP BY b.id
            ORDER BY b.created_at DESC
        """, [uid]).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/boards", methods=["POST"])
@login_required
def boards_create():
    uid  = session["user_id"]
    data = request.get_json(force=True) or {}
    provider = (data.get("provider") or "").strip().lower()
    slug     = (data.get("slug") or "").strip()
    name     = (data.get("name") or slug).strip()
    if provider not in ("greenhouse", "lever"):
        return jsonify({"error": "Provider muss greenhouse oder lever sein"}), 400
    if not slug:
        return jsonify({"error": "Slug ist Pflicht"}), 400
    interval = int(data.get("check_interval_hours", 24))
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO company_boards (user_id, provider, slug, name, check_interval_hours) VALUES (?, ?, ?, ?, ?)",
            [uid, provider, slug, name, interval]
        )
        row = db.execute("SELECT * FROM company_boards WHERE id = ?", [cur.lastrowid]).fetchone()
    return jsonify(dict(row)), 201


@app.route("/boards/<int:bid>", methods=["PATCH", "OPTIONS"])
@login_required
def boards_update(bid):
    uid  = session["user_id"]
    data = request.get_json(force=True) or {}
    with get_db() as db:
        row = db.execute("SELECT id FROM company_boards WHERE id = ? AND user_id = ?", [bid, uid]).fetchone()
        if not row:
            return jsonify({"error": "Nicht gefunden"}), 404
        allowed = {"name", "active", "check_interval_hours"}
        for field, val in data.items():
            if field in allowed:
                db.execute(f"UPDATE company_boards SET {field} = ? WHERE id = ?", [val, bid])
    return jsonify({"ok": True})


@app.route("/boards/<int:bid>", methods=["DELETE", "OPTIONS"])
@login_required
def boards_delete(bid):
    uid = session["user_id"]
    with get_db() as db:
        row = db.execute("SELECT id FROM company_boards WHERE id = ? AND user_id = ?", [bid, uid]).fetchone()
        if not row:
            return jsonify({"error": "Nicht gefunden"}), 404
        db.execute("DELETE FROM board_jobs WHERE board_id = ?", [bid])
        db.execute("DELETE FROM company_boards WHERE id = ?", [bid])
    return jsonify({"ok": True})


@app.route("/boards/<int:bid>/check", methods=["POST", "OPTIONS"])
@login_required
def boards_check_now(bid):
    uid = session["user_id"]
    with get_db() as db:
        row = db.execute("SELECT * FROM company_boards WHERE id = ? AND user_id = ?", [bid, uid]).fetchone()
        if not row:
            return jsonify({"error": "Nicht gefunden"}), 404
    try:
        new_count, total = _check_board(dict(row))
        return jsonify({"ok": True, "total": total, "new": new_count})
    except Exception as e:
        now = datetime.now(timezone.utc).isoformat()
        with get_db() as db:
            db.execute(
                "UPDATE company_boards SET last_checked_at = ?, last_check_status = ? WHERE id = ?",
                [now, f"error: {str(e)[:200]}", bid]
            )
        return jsonify({"error": str(e)}), 500


@app.route("/boards/jobs", methods=["GET", "OPTIONS"])
@login_required
def boards_jobs():
    uid = session["user_id"]
    with get_db() as db:
        rows = db.execute("""
            SELECT j.*, b.name AS board_name, b.provider, b.slug
            FROM board_jobs j
            JOIN company_boards b ON b.id = j.board_id
            WHERE b.user_id = ?
            ORDER BY j.found_at DESC LIMIT 200
        """, [uid]).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/boards/jobs/<int:jid>", methods=["DELETE", "OPTIONS"])
@login_required
def boards_job_delete(jid):
    uid = session["user_id"]
    with get_db() as db:
        row = db.execute(
            "SELECT j.id FROM board_jobs j JOIN company_boards b ON b.id = j.board_id WHERE j.id = ? AND b.user_id = ?",
            [jid, uid]
        ).fetchone()
        if not row:
            return jsonify({"error": "Nicht gefunden"}), 404
        db.execute("DELETE FROM board_jobs WHERE id = ?", [jid])
    return jsonify({"ok": True})


@app.route("/boards/jobs/read-all", methods=["POST", "OPTIONS"])
@login_required
def boards_jobs_read_all():
    uid = session["user_id"]
    with get_db() as db:
        db.execute("""
            UPDATE board_jobs SET is_new = 0
            WHERE board_id IN (SELECT id FROM company_boards WHERE user_id = ?)
        """, [uid])
    return jsonify({"ok": True})


# ── Legal Meta ────────────────────────────────────────────────────

@app.route("/meta/legal")
def meta_legal():
    return jsonify({
        "operator_name":    os.environ.get("OPERATOR_NAME", ""),
        "operator_street":  os.environ.get("OPERATOR_STREET", ""),
        "operator_city":    os.environ.get("OPERATOR_CITY", ""),
        "operator_country": os.environ.get("OPERATOR_COUNTRY", ""),
        "operator_email":   os.environ.get("OPERATOR_EMAIL", ""),
        "operator_phone":   os.environ.get("OPERATOR_PHONE", ""),
        "log_retention":    os.environ.get("LOG_RETENTION_DAYS", "30"),
        "backup_retention": os.environ.get("BACKUP_RETENTION_DAYS", "30"),
    })

# ── Startup ───────────────────────────────────────────────────────

_schedule_backup()
_schedule_watch_checks()
_schedule_digest()
_schedule_alert_checks()


def _schedule_board_checks():
    def _loop():
        while True:
            time.sleep(WATCH_INTERVAL_MINUTES * 60)
            try:
                _run_board_checks()
            except Exception as e:
                print(f"[Board] Scheduler-Fehler: {e}", flush=True)
    threading.Thread(target=_loop, daemon=True, name="board-checker").start()

_schedule_board_checks()

if __name__ == "__main__":
    print("✅ JobPipeline Server läuft auf http://localhost:5500")
    app.run(host="0.0.0.0", port=5500, debug=False)
