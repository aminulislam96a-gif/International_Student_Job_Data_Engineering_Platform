import requests
import csv 
import json 
from pathlib import Path
from datetime import datetime, timezone

# Locate employer configuration and ashby data

project_root = Path(__file__).resolve().parents[1]
config_file = project_root / "config" / "employer_sources.csv"
source_folder = project_root / "data" / "raw" /"ashby"

# Read active AShby boards
with open(config_file, encoding="utf-8", newline="")as f:
    employers = list(csv.DictReader(f))

    board_names = []

    for employer in employers:
        source = (employer.get("ats_source") or "").strip().lower()
        active = (employer.get("is_active") or "").strip().lower()


        if source == "ashby" and active == "true" and board:
            board_names.append(board)


# Calling the API one company at a time  
for board_name in dict.fromkeys(board_names):
    url = f"https://api.ashbyhq.com/posting-api/job-board/{board_name}"

    try:
        # Request jibs and available compensation data
        response = requests.get(url, params={"includeCompensation": "true"},\
                                headers={"Accept": "application/json"},\
                                      timeout=30)

        response.raise_for_status()

        data = response.json()
        jobs = data["jobs"]

        if not isinstance(jobs,list):
            raise TypeError(f"Expected 'jobs' to be a list ")


        # validate IDs and prepare comparison independent of job order
        current_jobs = {}

        for job in jobs:
            job_id = job["id"]

            if not job_id:
                raise ValueError("A job has empty ID")
            
            if job_id in current_jobs:
                raise ValueError(f"Repeated job ID: {job_id}")

            current_jobs[job_id] = job

        #  Find the latest saved snapshot for this board 
        previous_file = list(source_folder.glob(f"*/{board_name}_*.json"))

        if previous_file:
            latest_file = max(previous_file, key=lambda path: path.stat().st_mtime)

            with open(latest_file, encoding="utf_8")as f:
                previous_data = json.load(f)


            # support older wrapped snapshorts
            previous_data = previous_data.get("source_payload", previous_data)

            previous_jobs ={
                job["id"]: job
                for job in previous_data["jobs"]
            }

            # skip saving if job IDs all jiob detailes match

            if current_jobs == previous_jobs:
                print(f"{board_name}: no jobs chnages _ skipped saving")
                continue

        # Create or resue the UTC adte folder 

        run_time = datetime.now(timezone.utc)
        date_folder = run_time.strftime("%Y-%m-%d")
        timestamp = run_time.strftime("%H%M%S_%f")


        folder = source_folder / date_folder
        folder.mkdir(parents=True, exist_ok=True)

        output_file = folder / f"{board_name}_{timestamp}.json"

        # Save the complete response for new or changed snapshorts
        with open(output_file, "w", encoding="utf-8")as f:
            json.dump(data, f, indent=2, ensure_ascii=False)



        print(f"Company board: {board_name}")
        print(f"Connection successful: HTTP {response.status_code}")
        print(f"Total jobs:{len(jobs)}")
        print(f"Saved: {output_file}")

    except requests.exceptions.RequestException as e:
        print(f"{board_name}: request failed {e}")

    except(OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        print(f"{board_name}: response data error -{e}")
