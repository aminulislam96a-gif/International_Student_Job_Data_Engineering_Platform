
import os
import json
import requests
from pathlib import Path
from datetime import datetime, timezone


# ---------------------------------
# Configuration
# ---------------------------------

project_root = Path(__file__).resolve().parents[1]
source_folder = project_root / "data" / "raw" / "headcount"

api_key = os.getenv("HEADCOUNT_API_KEY")

if not api_key:
    raise SystemExit("HEADCOUNT_API_KEY is missing")

url = "https://api.headcountlabs.com/v1/jobs"

headers = {
    "Authorization": f"Bearer {api_key}"
}

companies = [
    "Alarm.com",
    "Appian",
    "Capital One",
    "Hilton",
    "Cvent",
    "Freddie Mac",
    "Mars",
    "Booz Allen Hamilton",
    "Leidos",
    "Noblis"
]

PAGE_SIZE = 250
MAX_PAGES = None


# ---------------------------------
# Extract jobs
# ---------------------------------

def extract_jobs(company):
    pages = []
    cursor = None
    seen_cursors = set()

    while True:
        params = {
            "country": "US",
            "currentness": "current",
            "company": company,
            "limit": PAGE_SIZE
        }

        if cursor:
            params["cursor"] = cursor

        try:
            response = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=30
            )

            response.raise_for_status()
            data = response.json()

            if not isinstance(data, dict):
                raise ValueError("Invalid API response")

            if not isinstance(data.get("data"), list):
                raise ValueError("Missing jobs list")

            if "next_cursor" not in data:
                raise ValueError("Missing pagination field")

            pages.append(data)

            print(
                f"{company}: Page {len(pages)} - "
                f"{len(data['data'])} jobs"
            )

            next_cursor = data["next_cursor"]

            if not next_cursor:
                return pages, True

            if next_cursor == cursor or next_cursor in seen_cursors:
                print(f"{company}: Repeated pagination cursor")
                return None, False

            seen_cursors.add(next_cursor)
            cursor = next_cursor

            if MAX_PAGES is not None and len(pages) >= MAX_PAGES:
                return pages, False

        except (requests.RequestException, ValueError) as e:
            print(f"{company}: Extraction failed - {e}")
            return None, False


# ---------------------------------
# Save raw JSON
# ---------------------------------

def save_jobs(company, pages, complete):

    company_name = company.lower().replace(" ", "_")

    # Compare jobs without depending on API result order
    jobs = {
        job["job_id"]: job
        for page in pages
        for job in page["data"]
        if job.get("job_id")
    }

    previous_files = list(
        source_folder.glob(f"*/{company_name}_*.json")
    )

    if previous_files:
        latest_file = max(
            previous_files,
            key=lambda path: path.stat().st_mtime
        )

        with open(latest_file, encoding="utf-8") as f:
            previous = json.load(f)

        previous_jobs = {
            job["job_id"]: job
            for page in previous["pages"]
            for job in page["data"]
            if job.get("job_id")
        }

        if (
            jobs == previous_jobs
            and complete == previous.get("complete")
        ):
            print(f"{company}: No job changes - skipped saving")
            return

    # Create timestamped snapshot
    run_time = datetime.now(timezone.utc)

    date_folder = run_time.strftime("%Y-%m-%d")
    timestamp = run_time.strftime("%H%M%S_%f")

    folder = source_folder / date_folder
    folder.mkdir(parents=True, exist_ok=True)

    output_file = folder / f"{company_name}_{timestamp}.json"

    snapshot = {
        "source": "headcount",
        "company_query": company,
        "extracted_at": run_time.isoformat(),
        "complete": complete,
        "pages": pages
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)

    print(f"{company}: Unique jobs: {len(jobs)}")
    print(f"Extraction complete: {complete}")
    print(f"Saved: {output_file}")


# ---------------------------------
# Run extraction
# ---------------------------------

for company in companies:
    pages, complete = extract_jobs(company)

    if pages is not None:
        save_jobs(company, pages, complete)
