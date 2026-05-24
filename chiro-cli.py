import json
import os
import sys
import time
import requests

# 1. Determine tracking mode from command-line arguments
VALID_MODES = ["anime", "manga", "movie", "tv"]
if len(sys.argv) < 2 or sys.argv[1].lower() not in VALID_MODES:
    print("\033[91mError: Please specify a valid mode.\033[0m")
    print("Usage: python chiro_live.py [anime | manga | movie | tv]")
    sys.exit(1)

MODE = sys.argv[1].lower()
DATA_FILE = f"{MODE}_list.json"
CONFIG_FILE = "config.json"

# UI Colors
GREEN = "\033[38;2;38;162;105m"  # Hex #26A269
RED = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"

def print_success(message):
    print(f"\n{GREEN}✓ {message}{RESET}\n")

def print_error(message):
    print(f"\n{RED}✗ {message}{RESET}\n")

# 2. Configuration helper for TMDB API Key
def get_tmdb_key():
    config = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
            
    if "tmdb_api_key" in config and config["tmdb_api_key"]:
        return config["tmdb_api_key"]
        
    print(f"{BOLD}TMDB API Key required for Movie/TV tracking.{RESET}")
    key = input("Enter your TMDB API Key: ").strip()
    if not key:
        print_error("API key cannot be empty.")
        sys.exit(1)
        
    config["tmdb_api_key"] = key
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)
    print_success("API Key saved to config.json")
    return key

# Set up API parameters based on Ecosystem
if MODE in ["movie", "tv"]:
    TMDB_API_KEY = get_tmdb_key()
    TMDB_BASE = "https://api.themoviedb.org/3"
else:
    JIKAN_BASE = "https://api.jikan.moe/v4"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

# 3. Dynamic Network Request Routers
def fetch_item_by_id(item_id):
    try:
        if MODE in ["movie", "tv"]:
            url = f"{TMDB_BASE}/{MODE}/{item_id}"
            response = requests.get(url, params={"api_key": TMDB_API_KEY})
        else:
            url = f"{JIKAN_BASE}/{MODE}/{item_id}"
            response = requests.get(url)

        if response.status_code == 200:
            return response.json() if MODE in ["movie", "tv"] else response.json().get("data")
        elif response.status_code in [401, 403]:
            print_error("Invalid API Key. Check your config.json file.")
        elif response.status_code == 404:
            print_error(f"{MODE.upper()} ID not found.")
    except requests.RequestException:
        print_error("Network timeout or connection drop.")
    return None

def search_item_by_title(title):
    try:
        if MODE in ["movie", "tv"]:
            url = f"{TMDB_BASE}/search/{MODE}"
            response = requests.get(url, params={"api_key": TMDB_API_KEY, "query": title})
            if response.status_code == 200:
                return response.json().get("results", [])[:5]
        else:
            url = f"{JIKAN_BASE}/{MODE}"
            response = requests.get(url, params={"q": title, "limit": 5})
            if response.status_code == 200:
                return response.json().get("data", [])
    except requests.RequestException:
        print_error("Network error during search execution.")
    return []

# 4. Contextual Interface Adjustments
def get_metric_label():
    if MODE == "anime": return "Progress"
    if MODE == "manga": return "Chapters"
    if MODE == "tv": return "Episodes"
    return "Runtime"  # Movies

def get_default_statuses(progress, total):
    if progress == total and total != "?":
        return "Completed"
    
    if progress == "0" or progress == "0/0":
        if MODE in ["anime", "tv", "movie"]: return "Plan to Watch"
        return "Plan to Read"
        
    if MODE == "manga": return "Reading"
    return "Watching"

def list_items(data):
    if not data:
        print(f"\nYour {MODE} list is empty. Use 'add' to begin tracking.\n")
        return
    
    metric_label = get_metric_label()
    print(f"\n{BOLD}| {'ID':<8} | {'Title':<35} | {'Type':<12} | {metric_label:<10} | {'Status':<12} | {'Rating':<6} |{RESET}")
    print("-" * 102) # FIX: Extended from 100 to 103 to perfectly cap the right margin
    
    for item_id, info in data.items():
        prog_str = info['progress'] if MODE == "tv" else f"{info['progress']}/{info['total']}"
        print(f"| {item_id:<8} | {info['title'][:35]:<35} | {info['type'][:12]:<12} | {prog_str:<10} | {info['status']:<12} | {info['rating']:<6} |")
    print()

def add_item(data):
    user_input = input(f"Enter {MODE.upper()} ID or Title to search: ").strip()
    if not user_input: return

    raw_data = None
    if user_input.isdigit():
        print("Fetching explicit ID...")
        raw_data = fetch_item_by_id(user_input)

    if not raw_data:
        print("Searching database...")
        results = search_item_by_title(user_input)
        if not results:
            print_error("No direct matches found.")
            return

        print("\nSearch Results:")
        for idx, item in enumerate(results, start=1):
            if MODE in ["movie", "tv"]:
                title = item.get("title") or item.get("name")
                date = item.get("release_date", "")[:4] if MODE == "movie" else item.get("first_air_date", "")[:4]
                item_id = item["id"]
            else:
                title = item["title"]
                date = item.get('published', {}).get('from', '')[:4] if MODE == "manga" else item.get('year', 'N/A')
                item_id = item["mal_id"]
            print(f"[{idx}] {title} ({date or 'N/A'}) - ID: {item_id}")

        choice = input("\nSelect choice (1-5) or 'c' to cancel: ").strip()
        if choice.lower() == 'c' or not choice.isdigit() or not (1 <= int(choice) <= len(results)): return
        
        # If it was a search result, we need to do a full lookup to get specific runtime/episode metrics
        selected = results[int(choice) - 1]
        target_id = selected["id"] if MODE in ["movie", "tv"] else selected["mal_id"]
        print("Fetching complete metadata details...")
        raw_data = fetch_item_by_id(target_id)

    if not raw_data: return

    # Normalize fields across disparate APIs
    if MODE in ["movie", "tv"]:
        item_id = str(raw_data["id"])
        title = raw_data.get("title") or raw_data.get("name")
        item_type = "Movie" if MODE == "movie" else "Scripted TV"
        
        if MODE == "movie":
            total_count = f"{raw_data.get('runtime', 0)}m"
            metric_prompt = "Minutes Watched"
        else:
            total_count = str(raw_data.get("number_of_episodes", "?"))
            metric_prompt = "Current Season/Episode (e.g., S01E05)"
    else:
        item_id = str(raw_data["mal_id"])
        title = raw_data["title"]
        item_type = raw_data.get("type", "Unknown")
        total_field = "episodes" if MODE == "anime" else "chapters"
        total_count = str(raw_data.get(total_field)) if raw_data.get(total_field) else "?"
        metric_prompt = f"Progress (0/{total_count})"

    print(f"\n    !! {MODE.upper()} found - {title}")
    
    progress = input(f"{metric_prompt}: ").strip() or "0"
    default_status = get_default_statuses(progress, total_count)
    status = input(f"Status ({default_status}): ").strip() or default_status
    rating = input("Rating (1-10, leave empty for none): ").strip() or "--"

    data[item_id] = {
        "title": title,
        "type": item_type,
        "progress": progress,
        "total": total_count,
        "status": status,
        "rating": rating
    }
    save_data(data)
    print_success("Added Successfully")

def update_item(data):
    item_id = input("ID to update: ").strip()
    if item_id not in data:
        print_error(f"Item not found in your local {MODE} list.")
        return

    item = data[item_id]
    print(f"Updating: {item['title']}")

    if MODE == "movie": metric_prompt = "Minutes Watched"
    elif MODE == "tv": metric_prompt = "Season/Episode"
    else: metric_prompt = "Progress"

    current_prog = item['progress'] if MODE == "tv" else f"{item['progress']}/{item['total']}"
    progress = input(f"{metric_prompt} ({current_prog}): ").strip() or item['progress']
    
    default_status = get_default_statuses(progress, item['total']) if progress != item['progress'] else item['status']
    status = input(f"Status ({default_status}): ").strip() or default_status
    rating = input(f"Rating ({item['rating']}): ").strip() or item['rating']

    data[item_id].update({"progress": progress, "status": status, "rating": rating})
    save_data(data)
    print_success("Updated Successfully")

def delete_item(data):
    item_id = input("ID to delete: ").strip()
    if item_id not in data:
        print_error("Item not found.")
        return
    if input(f"Are you sure you want to remove '{data[item_id]['title']}'? (y/n): ").strip().lower() == 'y':
        del data[item_id]
        save_data(data)
        print_success("Deleted Successfully")

def main():
    data = load_data()
    print(" ██████╗██╗  ██╗██╗██████╗  ██████╗ ")
    print("██╔════╝██║  ██║██║██╔══██╗██╔═══██╗")
    print("██║     ███████║██║██████╔╝██║   ██║")
    print("██║     ██╔══██║██║██╔══██╗██║   ██║")
    print("╚██████╗██║  ██║██║██║  ██║╚██████╔╝")
    print(" ╚═════╝╚═╝  ╚═╝╚═╝╚═╝  ╚═╝ ╚═════╝ ")
    print(f"             Chiro-cli ({MODE.upper()})      ")

    while True:
        try:
            cmd = input("command > ").strip().lower()
            if cmd == "exit": break
            elif cmd == "list": list_items(data)
            elif cmd == "add":
                add_item(data)
                if MODE in ["anime", "manga"]: time.sleep(1)
            elif cmd == "update": update_item(data)
            elif cmd == "delete": delete_item(data)
            else: print(f"Unknown command. Try list, add, update, delete, or exit.")
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break

if __name__ == "__main__":
    main()
