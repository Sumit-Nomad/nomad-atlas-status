#!/usr/bin/env python3
"""Run this yourself, locally, whenever the refresh-atlas-status GitHub Actions job
starts failing with a login/redirect error (see README_atlas_status.md). Fresh
automated logins to login.urbanpiper.com get silently bounced back to the login
page shortly after reaching /locations -- the same session-detection problem
save_swiggy_session.py exists for. The fix is the same: open a real browser
window, YOU log in to Atlas by hand (including any 2FA/CAPTCHA), and once a real
logged-in session is detected it's saved.

Uploaded straight to the dashboard's own Apps Script (2026-09-30) instead of a
GitHub secret -- a real session's localStorage runs 100KB+ (the UrbanPiper app
renders blank without it), well past GitHub Actions' 48KB per-secret cap. The
Apps Script stores it chunked across a Sheet (same pattern as its DashCache) and
refresh_atlas_status.py fetches it from there.

Needs DASHBOARD_URL/DASHBOARD_INGEST_KEY env vars - DASHBOARD_URL is the *main*
dashboard's /exec URL (NOT the same as scrape_swiggy_reviews.py's INGEST_URL,
which points at a separate standalone Swiggy-reviews-only Apps Script project -
uploading there would silently no-op with "unknown platform"). DASHBOARD_INGEST_KEY
must match that main dashboard's own INGEST_KEY script property (Apps Script
editor -> Project Settings -> Script Properties). Falls back to writing
atlas_storage_state.b64 locally if they're not set.

Nothing here handles your password -- Playwright just opens Chrome and waits for you.

    pip install playwright
    playwright install chromium
    DASHBOARD_URL=... DASHBOARD_INGEST_KEY=... python save_atlas_session.py
"""
import base64
import json
import os
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

TIMEOUT_S = 1800
CHROME_PATH = os.environ.get("CHROME_PATH", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
LOGIN_URL = "https://login.urbanpiper.com/login/email-mobile/?redirect=atlas"

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=CHROME_PATH, headless=False, args=["--disable-blink-features=AutomationControlled"])
    context = browser.new_context()
    page = context.new_page()
    page.goto(LOGIN_URL)
    print("Log in to UrbanPiper Atlas in the browser window (email/password, 2FA/CAPTCHA if asked).")
    print("If a business-selector screen appears after login, pick the right business by hand too.")
    print(f"Waiting up to {TIMEOUT_S // 60} minutes for a logged-in session on /locations...", flush=True)

    state = None
    deadline = time.time() + TIMEOUT_S
    n = 0
    stuck_since = None
    while time.time() < deadline:
        time.sleep(3)
        n += 1
        if n % 5 == 0:
            try:
                print("page:", page.url, "| cookies:", len(context.cookies()), flush=True)
            except Exception as e:
                print("page closed or unreadable:", e, flush=True)
        try:
            cookies = context.cookies()
        except Exception:
            continue
        atlas_cookies = [c for c in cookies if "urbanpiper" in c["domain"]]
        on_login = "login.urbanpiper.com" in page.url
        # Confirmed: after picking a business, this page's own JS redirect to
        # atlas.urbanpiper.com often just never fires (same failure the GitHub
        # Actions job hits) even though the business click registered (more
        # cookies show up). Don't wait passively for the URL to change on its
        # own - once enough cookies exist and we've been sitting on a
        # login.urbanpiper.com page for a bit, force the navigation ourselves,
        # the same way scrape_all_locations() in refresh_atlas_status.py does.
        if on_login and len(atlas_cookies) >= 6:
            if stuck_since is None:
                stuck_since = time.time()
            elif time.time() - stuck_since < 12:
                continue  # give the page's own redirect a brief chance first
        else:
            stuck_since = None
        # Accounts that land on prime.urbanpiper.com/home after login never reach atlas.* by themselves.
        on_portal = ("atlas.urbanpiper.com" in page.url or "prime.urbanpiper.com" in page.url) and not on_login
        logged_in = on_portal or (on_login and stuck_since is not None)
        if logged_in and atlas_cookies:
            # Nudge to /locations and confirm the table actually renders --
            # a cookie existing isn't proof the session survives navigation.
            try:
                page.goto("https://atlas.urbanpiper.com/locations", wait_until="networkidle", timeout=20000)
                if "login.urbanpiper.com" in page.url:
                    print("still bounced to login after forcing /locations - not logged in yet, retrying", flush=True)
                    stuck_since = None
                    continue
                page.wait_for_selector("tr[data-row-key]", timeout=15000)
            except Exception as e:
                print("forced /locations nav did not confirm yet:", e, flush=True)
                continue
            time.sleep(2)
            state = context.storage_state()
            break
    browser.close()

if not state or not [c for c in state["cookies"] if "urbanpiper" in c["domain"]]:
    print("No confirmed logged-in session on /locations; nothing saved.", file=sys.stderr)
    sys.exit(1)

b64 = base64.b64encode(json.dumps(state).encode()).decode()
# DASHBOARD_URL/DASHBOARD_INGEST_KEY, not INGEST_URL/INGEST_KEY - those point at a
# separate, standalone Swiggy-reviews-only Apps Script project (see module docstring).
dashboard_url = os.environ.get("DASHBOARD_URL")
dashboard_key = os.environ.get("DASHBOARD_INGEST_KEY")
if dashboard_url and dashboard_key:
    body = json.dumps({"key": dashboard_key, "platform": "atlas_session", "b64": b64}).encode()
    req = urllib.request.Request(dashboard_url, data=body, headers={"Content-Type": "text/plain"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            reply = json.loads(resp.read().decode())
        if reply.get("ok"):
            print(f"\nUploaded a session with {len(state['cookies'])} cookies "
                  f"({reply['result']['bytes']} bytes, {reply['result']['chunks']} chunks) to the dashboard.")
            print("refresh_atlas_status.py will pick it up on its next run - nothing else to do.")
            sys.exit(0)
        print(f"Dashboard rejected the upload: {reply}", file=sys.stderr)
    except Exception as e:
        print(f"Upload failed ({e}) - falling back to a local file.", file=sys.stderr)

with open("atlas_storage_state.b64", "w") as f:
    f.write(b64)
print(f"\nSaved a session with {len(state['cookies'])} cookies to atlas_storage_state.b64.")
print("Set DASHBOARD_URL/DASHBOARD_INGEST_KEY and rerun to upload it directly, or paste")
print("this file's contents into the ATLAS_STORAGE_STATE_B64 GitHub secret (note: real")
print("sessions run well past GitHub's 48KB secret limit, so that path may not work).")
