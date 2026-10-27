
import json
import os
import sys
import time

from collections import Counter, defaultdict
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from check_duplicates import load_jobs, deduplicate
from dotenv import load_dotenv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


HEADCOUNT_URL = "https://api.headcountlabs.com"
PAGE_SIZE = 250
MAX_PAGES = 100


# Read data from an API
def fetch_json(url, api_key=None):
    headers = {
        "Accept": "application/json",
        "User-Agent": "JobDataPipeline/1.0"
    }

    if api_key:
        headers["Authorization"] = "Bearer " + api_key

    request = Request(url, headers=headers)

    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)

        except HTTPError as error:
            if error.code == 429:
                print("API rate limit reached")
                return None

            if error.code in (401, 402, 403):
                print(f"API access error: {error.code}")
                return None

            if error.code not in (408, 500, 502, 503, 504):
                print(f"HTTP error: {error.code}")
                return None

        except (URLError, TimeoutError, OSError, ValueError):
            pass

        if attempt < 2:
            time.sleep(2 * (attempt + 1))

    print("API request failed")
    return None


# Check Greenhouse jobs
def check_greenhouse(board):
    url = (
        "https://boards-api.greenhouse.io/v1/boards/"
        + quote(board, safe="")
        + "/jobs"
    )

    data = fetch_json(url)

    if not isinstance(data, dict):
        return None

    jobs = data.get("jobs")

    if not isinstance(jobs, list):
        return None

    ids = set()

    for job in jobs:
        if not isinstance(job, dict) or job.get("id") is None:
            return None

        ids.add(str(job["id"]).lower())

    return ids


# Check Lever jobs
def check_lever(board):
    for page_size in (100, 50, 25):
        ids = set()
        skip = 0

        while skip < 10000:
            params = urlencode({
                "mode": "json",
                "skip": skip,
                "limit": page_size
            })

            url = (
                "https://api.lever.co/v0/postings/"
                + quote(board, safe="")
                + "?"
                + params
            )

            jobs = fetch_json(url)

            if not isinstance(jobs, list):
                break

            if len(jobs) > page_size:
                break

            valid = True

            for job in jobs:
                if not isinstance(job, dict) or job.get("id") is None:
                    valid = False
                    break

                ids.add(str(job["id"]).lower())

            if not valid:
                break

            if len(jobs) < page_size:
                return ids

            skip += page_size

    return None


# Check Ashby jobs
def check_ashby(board):
    url = (
        "https://api.ashbyhq.com/posting-api/job-board/"
        + quote(board, safe="")
    )

    data = fetch_json(url)

    if not isinstance(data, dict):
        return None

    jobs = data.get("jobs")

    if not isinstance(jobs, list):
        return None

    ids = set()

    for job in jobs:
        if not isinstance(job, dict) or job.get("id") is None:
            return None

        if job.get("isListed") is False:
            continue

        ids.add(str(job["id"]).lower())

    return ids


# Check a public ATS board
def check_board(source, board):
    if source == "greenhouse":
        return check_greenhouse(board)

    if source == "lever":
        return check_lever(board)

    if source == "ashby":
        return check_ashby(board)

    return None


# Get job identities
def get_identities(job):
    identities = set()

    for record in job.get("source_records", [job]):
        identities.update(record.get("identities", set()))

    return identities


# Check availability using ATS
def check_ats_status(job, boards):
    identities = get_identities(job)

    if not identities:
        return "UNKNOWN", "No supported ATS identity"

    failed = False

    for source, board, job_id in identities:
        current_ids = boards.get((source, board))

        if current_ids is None:
            failed = True

        elif str(job_id).lower() in current_ids:
            return "ACTIVE", "Found in live ATS board"

    if failed:
        return "UNKNOWN", "ATS verification unavailable"

    return "CLOSED", "No longer listed on public ATS board"


# Get Headcount job ID and employer
def get_headcount_info(job):
    for record in job.get("source_records", [job]):
        if record.get("source") != "headcount":
            continue

        raw_job = record.get("job") or {}
        company = raw_job.get("employer_name")

        if isinstance(company, dict):
            company = company.get("value")

        return (
            str(record.get("job_id") or "").lower(),
            str(company or "").strip()
        )

    return None, None


# Check saved Headcount jobs using batches
def check_headcount(company, target_ids, api_key):
    found = {}
    cursor = None
    used_cursors = set()

    for page in range(MAX_PAGES):
        params = {
            "company": company,
            "currentness": "current,uncertain,not_current",
            "fields": "job_id,currentness",
            "limit": PAGE_SIZE
        }

        if cursor:
            params["cursor"] = cursor

        url = HEADCOUNT_URL + "/v1/jobs?" + urlencode(params)

        data = fetch_json(url, api_key)

        if not isinstance(data, dict):
            print(f"{company}: Batch request failed")
            return found, False

        jobs = data.get("data")

        if not isinstance(jobs, list):
            print(f"{company}: Invalid response")
            return found, False

        for job in jobs:
            if not isinstance(job, dict) or job.get("job_id") is None:
                return found, False

            job_id = str(job["job_id"]).lower()

            if job_id in target_ids:
                found[job_id] = job.get("currentness")

        # Stop when all required jobs are found
        if len(found) == len(target_ids):
            return found, True

        next_cursor = data.get("next_cursor")

        if not next_cursor:
            return found, True

        if next_cursor in used_cursors:
            print(f"{company}: Repeated cursor")
            return found, False

        used_cursors.add(next_cursor)
        cursor = next_cursor

    print(f"{company}: Maximum pages reached")
    return found, False


# Convert Headcount currentness
def headcount_status(currentness):
    if currentness == "current":
        return "ACTIVE", "Current in Headcount API"

    if currentness == "not_current":
        return "CLOSED", "Not current in Headcount API"

    return "UNKNOWN", "Currentness not confirmed"


# Load accepted and deduplicated jobs
def load_ready_jobs():
    with redirect_stdout(StringIO()):
        jobs = load_jobs()

    ready, possible, confirmed, unique = deduplicate(jobs)

    if possible:
        held = sum(len(group) for group in possible)
        print(f"Jobs held for duplicate review: {held}")

    return ready


# Check availability of all jobs
def check_availability(jobs=None, fetch_board=None,
                       fetch_headcount=None):

    if jobs is None:
        jobs = load_ready_jobs()

    if fetch_board is None:
        fetch_board = check_board

    api_key = os.getenv("HEADCOUNT_API_KEY")

    if fetch_headcount is None:
        def fetch_headcount(company, target_ids):
            if not api_key:
                print("HEADCOUNT_API_KEY is missing")
                return {}, False

            return check_headcount(company, target_ids, api_key)

    # Get all public ATS boards
    board_keys = set()

    for job in jobs:
        for source, board, job_id in get_identities(job):
            board_keys.add((source, board))

    boards = {}

    print("\nLIVE ATS AVAILABILITY CHECK")
    print("=" * 55)

    for source, board in sorted(board_keys):
        current_ids = fetch_board(source, board)
        boards[(source, board)] = current_ids

        if current_ids is None:
            print(f"{source}/{board}: UNKNOWN")
        else:
            print(f"{source}/{board}: {len(current_ids)} postings")

    # Check jobs using ATS results
    checked_at = datetime.now(timezone.utc).isoformat()
    results = []

    for job in jobs:
        status, reason = check_ats_status(job, boards)

        results.append({
            "job": job,
            "availability_status": status,
            "availability_reason": reason,
            "checked_at": checked_at
        })

    # Group unresolved Headcount jobs by employer
    employers = defaultdict(list)

    for index, result in enumerate(results):
        if result["availability_status"] != "UNKNOWN":
            continue

        job_id, company = get_headcount_info(result["job"])

        if job_id and company:
            employers[company].append((index, job_id))

    # Check Headcount jobs
    print("\nHEADCOUNT AVAILABILITY CHECK")
    print("=" * 55)

    for company, records in sorted(employers.items()):
        target_ids = {job_id for index, job_id in records}

        found, complete = fetch_headcount(company, target_ids)

        active_count = 0
        closed_count = 0
        unknown_count = 0

        for index, job_id in records:
            if job_id in found:
                status, reason = headcount_status(found[job_id])
            else:
                status = "UNKNOWN"
                reason = "Not verified in Headcount batch"

            results[index]["availability_status"] = status
            results[index]["availability_reason"] = reason

            if status == "ACTIVE":
                active_count += 1

            elif status == "CLOSED":
                closed_count += 1

            else:
                unknown_count += 1

        print(
            f"{company}: "
            f"ACTIVE={active_count}, "
            f"CLOSED={closed_count}, "
            f"UNKNOWN={unknown_count}"
        )

        if not complete:
            print(f"  Verification incomplete: {company}")

    # Separate jobs by availability status
    active_jobs = []
    closed_jobs = []
    unknown_jobs = []

    for result in results:
        status = result["availability_status"]

        if status == "ACTIVE":
            active_jobs.append(result)

        elif status == "CLOSED":
            closed_jobs.append(result)

        else:
            unknown_jobs.append(result)

    # Check total counts
    total = (
        len(active_jobs)
        + len(closed_jobs)
        + len(unknown_jobs)
    )

    assert total == len(jobs)

    # Final results
    print("\nAVAILABILITY RESULTS")
    print("=" * 55)

    print(f"Jobs checked: {len(jobs)}")
    print(f"ACTIVE: {len(active_jobs)}")
    print(f"CLOSED: {len(closed_jobs)}")
    print(f"UNKNOWN: {len(unknown_jobs)}")

    # Results by source
    print("\nBY SOURCE")
    print("-" * 55)

    categories = {
        "ACTIVE": active_jobs,
        "CLOSED": closed_jobs,
        "UNKNOWN": unknown_jobs
    }

    for source in ("headcount", "lever", "ashby", "greenhouse"):
        counts = Counter()

        for status, records in categories.items():
            for result in records:
                sources = {
                    record["source"]
                    for record in result["job"].get(
                        "source_records", [result["job"]]
                    )
                }

                if source in sources:
                    counts[status] += 1

        print(
            f"{source}: "
            f"ACTIVE={counts['ACTIVE']}, "
            f"CLOSED={counts['CLOSED']}, "
            f"UNKNOWN={counts['UNKNOWN']}"
        )

    # Data validation
    print("\nDATA VALIDATION")
    print("-" * 55)

    print("All jobs accounted for: YES")
    print(f"Ready for transformation: {len(active_jobs)}")
    print(f"No longer listed: {len(closed_jobs)}")
    print(f"Awaiting verification: {len(unknown_jobs)}")

    print("\nAVAILABILITY CHECK COMPLETED")

    return active_jobs, closed_jobs, unknown_jobs


# Test without calling APIs
def self_test():
    assert headcount_status("current")[0] == "ACTIVE"
    assert headcount_status("not_current")[0] == "CLOSED"
    assert headcount_status("uncertain")[0] == "UNKNOWN"

    job = {
        "identities": {
            ("greenhouse", "acme", "123")
        }
    }

    assert check_ats_status(
        job,
        {("greenhouse", "acme"): {"123"}}
    )[0] == "ACTIVE"

    assert check_ats_status(
        job,
        {("greenhouse", "acme"): set()}
    )[0] == "CLOSED"

    assert check_ats_status(
        job,
        {("greenhouse", "acme"): None}
    )[0] == "UNKNOWN"

    print("Self-test passed.")


if __name__ == "__main__":
    if "--test" in sys.argv:
        self_test()
    else:
        check_availability()
