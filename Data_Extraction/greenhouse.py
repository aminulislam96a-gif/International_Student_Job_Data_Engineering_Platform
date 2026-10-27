import requests
import json
import csv
from pathlib import Path
from datetime import datetime, timezone


# Locate the project folder and employer configuration
project_root = Path(__file__).resolve().parents[1]
config_file = project_root / "config" / "employer_sources.csv"

# Read each CSV row as a dictionary
with open(config_file, encoding="utf-8", newline="") as f:
    employers = list(csv.DictReader(f))

# Select active Greenhouse employer boards
board_names = []

for employer in employers:
    source = employer("ats_source") or ("").strip().lower()
    active = employer("is_active") or ("").strip().lower()

    if source == "greenhouse" and active == "true":
        board_names.append(employer["board_name"].strip())

# Request each board once, removing repeated names from the configuration
for board_name in dict.fromkeys(board_names):
    url = f"https://boards-api.greenhouse.io/v1/boards/{board_name}/jobs"

    try:
        # Fetch postings with full descriptions and check for HTTP errors
        response = requests.get(
            url,
            params={"content": "true"},
            timeout=30
        )
        response.raise_for_status()
        data = response.json()

        # Find this board's previously saved snapshots across date folders
        source_folder = project_root / "data" / "raw" / "greenhouse"
        previous_files = sorted(
            source_folder.glob(f"*/{board_name}_*.json")
        )

        if previous_files:
            # Select the snapshot with the latest file modification time
            latest_file = max(
                previous_files,
                key=lambda path: path.stat().st_mtime
            )

            with open(latest_file, encoding="utf-8") as f:
                previous_data = json.load(f)

            # Support older snapshots that wrap the response in source_payload
            previous_data = previous_data.get(
                "source_payload", previous_data
            )

            # Compare jobs by ID so changes in list order do not matter
            previous_jobs = {
                job["id"]: job
                for job in previous_data["jobs"]
            }

            current_jobs = {
                job["id"]: job
                for job in data["jobs"]
            }

            # Skip saving if no jobs were added, removed, or changed
            if current_jobs == previous_jobs:
                print(f"{board_name}: no job changes - skipped saving")
                continue

        # Use UTC date folders and timestamped filenames
        run_time = datetime.now(timezone.utc)
        date_folder = run_time.strftime("%Y-%m-%d")
        timestamp = run_time.strftime("%H%M%S_%f")

        folder = (
            project_root / "data" / "raw" / "greenhouse" / date_folder
        )

        # Create the date folder if needed; reuse it if it already exists
        folder.mkdir(parents=True, exist_ok=True)
        output_file = folder / f"{board_name}_{timestamp}.json"

        # Save the complete response for a new or changed board snapshot
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        jobs = data.get("jobs", [])

        # Display the collection result and saved location
        print(f"Company board: {board_name}")
        print(f"Connection successful: HTTP {response.status_code}")
        print(f"Total jobs: {len(jobs)}")
        print(f"Saved: {output_file}")

    # Report request failures and continue to the next board
    except requests.exceptions.RequestException as e:
        print(f"{board_name}: request failed - {e}")

    # Report file or data errors and continue to the next board
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"{board_name}: file or data error — {e}")