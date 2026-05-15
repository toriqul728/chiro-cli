#!/usr/bin/env python3
import os
import sys
import json
import requests
import shlex

# Enable arrow keys and command history
try:
    import readline
except ImportError:
    pass

# --- CONFIGURATION & AESTHETICS ---
MAGENTA, BOLD, RESET, DIM = '\033[95m', '\033[1m', '\033[0m', '\033[2m'

BANNER = rf"""
{MAGENTA}{BOLD} ██████╗██╗  ██╗██╗██████╗  ██████╗ 
██╔════╝██║  ██║██║██╔══██╗██╔═══██╗
██║     ███████║██║██████╔╝██║   ██║
██║     ██╔══██║██║██╔══██╗██║   ██║
╚██████╗██║  ██║██║██║  ██║╚██████╔╝
 ╚═════╝╚═╝  ╚═╝╚═╝╚═╝  ╚═╝ ╚═════╝{RESET}
"""

CH_DIR = os.path.expanduser("~/.chiro")
CONFIG_FILE = os.path.join(CH_DIR, "config.json")

VALID_STATUSES = ["Planning", "Watching", "Reading", "On-Hold", "Dropped", "Completed"]

# Priority order: higher index = higher priority. Auto-status never downgrades.
STATUS_PRIORITY = {"Completed": 0, "Planning": 1, "Dropped": 2, "On-Hold": 3, "Reading": 4, "Watching": 4}

def auto_status(cat, new_p, total, current_s):
    """Return the appropriate auto status without downgrading current priority."""
    active = "Reading" if cat == "manga" else "Watching"
    current_rank = STATUS_PRIORITY.get(current_s, 0)

    if total != "?" and str(new_p) == str(total):
        # Always complete when total reached
        return "Completed", "Total reached! Status forced to 'Completed'."

    if int(new_p) > 0 and current_s == "Planning":
        # Only upgrade Planning -> Watching/Reading, never touch higher statuses
        if current_rank <= STATUS_PRIORITY[active]:
            return active, f"Progress detected — status auto-set to '{active}'."

    return current_s, None


# --- SETUP & PERSISTENCE ---

def setup():
    if not os.path.exists(CH_DIR):
        os.makedirs(CH_DIR)
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'w') as f:
            json.dump({"tmdb_key": ""}, f)

def load_db(cat):
    path = os.path.join(CH_DIR, f"{cat}.json")
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return {}

def save_db(cat, data):
    with open(os.path.join(CH_DIR, f"{cat}.json"), 'w') as f:
        json.dump(data, f, indent=4)

def load_config():
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)


# --- VALIDATION ---

def validate_progress(val, total):
    """Returns (int_value, error_string). error_string is None if valid."""
    try:
        v = int(val)
        if v < 0:
            return None, "Progress cannot be negative."
        if total != "?":
            try:
                if v > int(total):
                    return None, f"Progress ({v}) exceeds total ({total})."
            except ValueError:
                pass
        return v, None
    except ValueError:
        return None, f"Invalid progress value '{val}' — must be a whole number."

def validate_rate(val):
    """Returns (int_value, error_string). error_string is None if valid."""
    try:
        v = int(float(val))
        if not (0 <= v <= 10):
            return None, "Rate must be between 0 and 10."
        return v, None
    except ValueError:
        return None, f"Invalid rate '{val}' — must be a number between 0 and 10."

def format_rate(val):
    try:
        return f"{int(float(val)):02d}/10"
    except (ValueError, TypeError):
        return "00/10"

def prompt_progress(label, current, total):
    """Prompt for progress with validation loop. Returns validated string."""
    while True:
        raw = input(label).strip() or str(current)
        val, err = validate_progress(raw, total)
        if err:
            print(f"  !! {err}")
        else:
            return str(val)

def prompt_rate(label, current):
    """Prompt for rate with validation loop. Returns validated string."""
    while True:
        raw = input(label).strip() or str(current)
        val, err = validate_rate(raw)
        if err:
            print(f"  !! {err}")
        else:
            return str(val)

def prompt_status(label, current):
    """Prompt for status with validation loop. Returns validated string."""
    hint = "/".join(VALID_STATUSES)
    while True:
        raw = input(f"{label} [{hint}]: ").strip() or current
        if raw in VALID_STATUSES:
            return raw
        print(f"  !! Invalid status. Choose from: {hint}")


# --- API INTEGRATIONS ---

def fetch_metadata(cat, query):
    if cat in ["anime", "manga"]:
        url = f"https://api.jikan.moe/v4/{cat}?q={query}&limit=1"
        try:
            res = requests.get(url, timeout=8).json()
            if 'data' in res and res['data']:
                item = res['data'][0]
                return {
                    "id": str(item['mal_id']),
                    "title": item['title'],
                    "total": str(item.get('episodes') or item.get('chapters') or "?")
                }
        except Exception:
            return None

    elif cat in ["tv", "movies"]:
        config = load_config()
        key = config.get('tmdb_key', '').strip()
        if not key:
            print(f"  !! No TMDB API key set. Add it to {CONFIG_FILE} under 'tmdb_key'.")
            return None
        s_type = "tv" if cat == "tv" else "movie"
        search_url = f"https://api.themoviedb.org/3/search/{s_type}?api_key={key}&query={query}"
        try:
            res = requests.get(search_url, timeout=8).json()
            if 'results' not in res or not res['results']:
                return None
            item = res['results'][0]
            item_id = str(item['id'])
            title = item.get('name') or item.get('title')

            # Second call: fetch full details to get total count
            detail_url = f"https://api.themoviedb.org/3/{s_type}/{item_id}?api_key={key}"
            total = "?"
            try:
                detail = requests.get(detail_url, timeout=8).json()
                if cat == "tv":
                    # number_of_episodes is the full series total
                    total = str(detail.get('number_of_episodes') or "?")
                else:
                    # Movies are a single watch; runtime in minutes as context
                    runtime = detail.get('runtime')
                    total = "1" if not runtime else f"1"  # always 1 film
            except Exception:
                pass  # fall back to "?" if detail call fails

            return {"id": item_id, "title": title, "total": total}
        except Exception:
            return None

    return None


# --- SHELL ---

def start_shell(cat):
    print(BANNER)
    print(f"{DIM}chiro for {cat}{RESET}")
    print("Commands: list, add, update, delete, refresh, clear, exit\n")
    db = load_db(cat)

    while True:
        try:
            raw = input(f"{BOLD}chiro({cat}) > {RESET}").strip()
            if not raw:
                continue
            try:
                cmd = shlex.split(raw)[0].lower()
            except ValueError:
                print("  !! Invalid input — check for unmatched quotes.")
                continue

            # ── EXIT ──────────────────────────────────────────────────────────
            if cmd == "exit":
                save_db(cat, db)
                print("Saved.")
                break

            # ── LIST ──────────────────────────────────────────────────────────
            elif cmd == "list":
                if not db:
                    print(f"\n{DIM}No entries yet.{RESET}\n")
                    continue
                print(f"\n{BOLD}{cat.upper()} LIST{RESET}")
                cols = [("ID", 8), ("Title", 35), ("Prog", 10), ("Rate", 8), ("Status", 12)]
                head = " | ".join([f"{n:<{w}}" for n, w in cols])
                print(head)
                print("-" * len(head))
                for aid in sorted(db.keys(), key=lambda k: db[k]['title']):
                    entry = db[aid]
                    prog = f"{entry['progress']}/{entry['total']}"
                    row = [
                        f"{aid[:8]:<8}",
                        f"{entry['title'][:33]:<35}",
                        f"{prog:<10}",
                        f"{format_rate(entry['rate']):<8}",
                        f"{entry['status']:<12}",
                    ]
                    print(" | ".join(row))
                print("")

            # ── ADD ───────────────────────────────────────────────────────────
            elif cmd == "add":
                title_in = input(f"{BOLD}Title: {RESET}").strip()
                if not title_in:
                    continue

                m = fetch_metadata(cat, title_in)
                if not m:
                    print("  Not found.")
                    continue

                if m['id'] in db:
                    print("  !! Already in list.")
                    continue

                print(f"{DIM}Found: {m['title']} | ID: {m['id']}{RESET}")

                new_p = prompt_progress(f"Progress (0): ", 0, m['total'])
                new_s = prompt_status(f"Status (Planning)", "Planning")
                new_r = prompt_rate(f"Rate (0): ", 0)

                # Auto-set status based on progress
                new_s, msg = auto_status(cat, new_p, m['total'], new_s)
                if msg:
                    print(f"{MAGENTA}{msg}{RESET}")

                if input(f"Confirm? (y/n): ").lower() == 'y':
                    db[m['id']] = {
                        "title": m['title'],
                        "total": m['total'],
                        "progress": new_p,
                        "status": new_s,
                        "rate": new_r,
                    }
                    save_db(cat, db)  # Auto-save after each mutation
                    print("  Added!")

            # ── UPDATE / DELETE ───────────────────────────────────────────────
            elif cmd in ["update", "delete"]:
                tid = input("Target ID: ").strip()

                if tid not in db:
                    print(f"  ID '{tid}' not found.")
                    continue

                if cmd == "delete":
                    if input(f"Delete '{db[tid]['title']}'? (y/n): ").lower() == 'y':
                        del db[tid]
                        save_db(cat, db)  # Auto-save after each mutation
                        print("  Deleted.")

                else:  # update
                    e = db[tid]
                    print(f"Updating {BOLD}{e['title']}{RESET}")

                    new_p = prompt_progress(f"Progress ({e['progress']}): ", e['progress'], e['total'])
                    new_s = prompt_status(f"Status ({e['status']})", e['status'])
                    new_r = prompt_rate(f"Rate ({e['rate']}): ", e['rate'])

                    # Auto-set status based on progress
                    new_s, msg = auto_status(cat, new_p, e['total'], new_s)
                    if msg:
                        print(f"{MAGENTA}{msg}{RESET}")

                    e.update({"progress": new_p, "status": new_s, "rate": new_r})
                    save_db(cat, db)  # Auto-save after each mutation
                    print("  Updated.")

            # ── CLEAR ────────────────────────────────────────────────────────
            elif cmd == "clear":
                os.system('clear')

            # ── REFRESH ───────────────────────────────────────────────────────
            elif cmd == "refresh":
                stale = {k: v for k, v in db.items() if v.get('total') == '?'}
                if not stale:
                    print("  All entries already have totals.")
                    continue
                print(f"  Refreshing {len(stale)} entr{'y' if len(stale) == 1 else 'ies'} with unknown totals...")
                updated = 0
                for eid, entry in stale.items():
                    m = fetch_metadata(cat, entry['title'])
                    if m and m.get('total', '?') != '?':
                        db[eid]['total'] = m['total']
                        print(f"  {entry['title'][:40]} -> {m['total']}")
                        updated += 1
                    else:
                        print(f"  {entry['title'][:40]} -> still unknown")
                if updated:
                    save_db(cat, db)
                print(f"  Done. {updated}/{len(stale)} updated.")

            else:
                print(f"  Unknown command '{cmd}'. Try: list, add, update, delete, refresh, clear, exit")

        except (KeyboardInterrupt, EOFError):
            save_db(cat, db)
            sys.exit()


def main():
    setup()
    if len(sys.argv) < 2:
        print("Usage: python3 chiro-cli.py <anime|manga|tv|movies>")
        return
    cat = sys.argv[1].lower()
    if cat in ["anime", "manga", "tv", "movies"]:
        start_shell(cat)
    else:
        print(f"Invalid category '{cat}'. Choose from: anime, manga, tv, movies")


if __name__ == "__main__":
    main()
