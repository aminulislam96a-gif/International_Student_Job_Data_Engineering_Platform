import requests
import json
import csv
from pathlib import Path
from datetime import datetime, timezone


#Loacte empoyer configuration and raw data 

project_root = Path(__file__).resolve().parents[1]
config_file = project_root / "config" / "employer_sources.csv"
source_folder = project_root / "data" / "raw" / "lever"

#Read active lever empolyer sittes
with open(config_file, encoding="utf-8", newline="")as f:
    employers = list(csv.DictReader(f))

sites_name = []

for employer in employers:
    source = employer("ats_source") or ("").strip().lower()
    active = employer("is_active") or ("").strip().lower()

    if source =="lever" and active =="true":
        sites_name.append(employer["board_name"].strip())

# Request each employer once
for site_name in dict.fromkeys(sites_name):
    url = f"https://api.lever.co/v0/postings/{site_name}"


    try:
        all_jobs =[]
        skip = 0
        limit = 100

        # Collect all pages before comparing or saving
        while True:
            response = requests.get(url, params={"mode":"json", "skip": skip, "limit": limit}, timeout=30)
            response.raise_for_status()

            jobs = response.json()

            if not isinstance(jobs, list):
                raise TypeError("Expected a list of Lever jobs")

            all_jobs.extend(jobs)

            if len(jobs)< limit:
                break

            skip += len(jobs)

        # Validate IDs before using for comparison 
        current_jobs ={}

        for job in all_jobs:
            job_id =job["id"]

            if not job_id :
                raise ValueError ("A job has missing ID")

            if job_id in current_jobs:
                raise ValueError(f"Repeated job ID: {job_id}")

            current_jobs[job_id] = job

        # Fine this employer's latest saved snapshot
        previous_files =list(source_folder.glob(f"*/{site_name}_*.json"))

        if previous_files:
            latest_file = max(previous_files, key=lambda path: path.stat().st_mtime)  

            with open (latest_file,encoding="utf-8") as f:
                previous_data = json.load(f) 

            # support older snapshorts wrapped in source_payload
            if isinstance(previous_data,dict):
                previous_data = previous_data["source_payload"]

            previous_jobs = { job["id"]: job for job in previous_data}

            # Skip saving if all job IDs and details match
            if current_jobs == previous_jobs:
                print(f"{site_name}: no job changes _ skipped saving")
                continue
        # create or reuse today's UTC folder 
        run_time = datetime.now(timezone.utc)
        date_folder = run_time.strftime("%Y-%m-%d")
        timestamp = run_time.strftime("%H%M%S_%f")

        folder = source_folder / date_folder
        folder.mkdir(parents=True, exist_ok=True)

        output_file = folder / f"{site_name}_{timestamp}.json"

        # Save the complete combine list of jobs

        with open(output_file, "w", encoding="utf-8")as f:
            json.dump(all_jobs, f, indent=2, ensure_ascii=False)

        print(f"Company site : {site_name}")
        print(f"Connection successful: HTTP {response.status_code}")
        print(f"Total jobs: {len(all_jobs)}")
        print(f"Saved: {output_file}")

    except requests.exceptions.RequestException as e:
        print(f"{site_name}: request failed -{e}")

    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"{site_name}: file or data error -{e}")


