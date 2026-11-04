
import importlib
import json
import os
import re

from pathlib import Path
from collections import defaultdict
from contextlib import redirect_stdout
from difflib import SequenceMatcher
from html import unescape
from io import StringIO
from urllib.parse import urlparse


SOURCES = ["headcount", "lever", "ashby", "greenhouse"]

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_FILE = ROOT / "data/processed/deduplicated_jobs.json"


# Clean text
def clean(value):
    if isinstance(value, dict):
        value = value.get("value", "")

    value = unescape(str(value or "")).lower()
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)

    return " ".join(value.split())


def company_name(value):
    endings = {
        "inc", "llc", "ltd", "corp",
        "corporation", "incorporated"
    }

    return " ".join(
        word for word in clean(value).split()
        if word not in endings
    )


def get_value(value):
    if isinstance(value, dict):
        if value.get("state") not in (None, "known"):
            return None
        return value.get("value")

    return value


def get_id(value):
    value = get_value(value)

    if value is None or isinstance(value, bool):
        return ""

    return str(value).strip()


def similar(first, second):
    return SequenceMatcher(None, first, second).ratio()


# Get ATS job identity
def ats_id(url):
    parsed = urlparse(str(get_value(url) or ""))
    domain = (parsed.hostname or "").lower().removeprefix("www.")
    parts = parsed.path.strip("/").lower().split("/")

    if domain in ("boards.greenhouse.io", "job-boards.greenhouse.io"):
        if len(parts) >= 3 and parts[1] == "jobs" and parts[2].isdigit():
            return ("greenhouse", parts[0], parts[2])

    if domain == "jobs.lever.co" and len(parts) >= 2:
        return ("lever", parts[0], parts[1])

    if domain == "jobs.ashbyhq.com" and len(parts) >= 2:
        return ("ashby", parts[0], parts[1])

    return None


# Get job URLs
def job_urls(job, source):
    if source == "headcount":
        urls = []

        for posting in job.get("postings") or []:
            if isinstance(posting, dict):
                for field in ("posting_url", "application_url"):
                    url = get_value(posting.get(field))

                    if url:
                        urls.append(url)

        return urls

    if source == "lever":
        return [job.get("hostedUrl"), job.get("applyUrl")]

    if source == "ashby":
        return [job.get("jobUrl"), job.get("applyUrl")]

    return [job.get("absolute_url")]


# Get Headcount posting IDs
def posting_ids(job):
    ids = set()

    for posting in job.get("postings") or []:
        if isinstance(posting, dict):
            source = get_id(posting.get("source")).lower()
            posting_id = get_id(posting.get("source_posting_id"))

            if source and posting_id:
                ids.add((source, posting_id))

    return ids


# Prepare job information
def prepare_job(job, source):
    if source == "headcount":
        company = job.get("employer_name")
        job_id = job.get("job_id")
        title = job.get("title")
        description = job.get("description")
        locations = []

        for place in job.get("locations") or []:
            if isinstance(place, dict):
                locations.append(
                    place.get("name")
                    or place.get("city")
                    or place.get("region")
                )
            else:
                locations.append(place)

    elif source == "lever":
        url = job.get("hostedUrl") or ""
        company = urlparse(url).path.strip("/").split("/")[0]
        job_id = job.get("id")
        title = job.get("text")
        description = job.get("descriptionPlain") or job.get("description")

        categories = job.get("categories") or {}
        location = categories.get("location") if isinstance(categories, dict) else None
        locations = [location or job.get("location")]

    elif source == "ashby":
        url = job.get("jobUrl") or ""
        company = urlparse(url).path.strip("/").split("/")[0]
        job_id = job.get("id")
        title = job.get("title")
        description = job.get("descriptionPlain")
        locations = [job.get("location")]

    else:
        company = job.get("company_name")
        job_id = job.get("id")
        title = job.get("title")
        description = job.get("content")

        location = job.get("location") or {}
        locations = [
            location.get("name") if isinstance(location, dict) else location
        ]

    identities = set()

    for url in job_urls(job, source):
        identity = ats_id(url)

        if identity:
            identities.add(identity)

    return {
        "source": source,
        "job_id": get_id(job_id),
        "job": job,
        "company": company_name(company),
        "title": clean(title),
        "description": clean(description)[:3000],
        "locations": {
            clean(place) for place in locations if clean(place)
        },
        "identities": identities,
        "source_posting_ids": posting_ids(job) if source == "headcount" else set()
    }


# Load accepted jobs
def load_jobs():
    jobs = []

    print("\nACCEPTED JOBS")
    print("=" * 45)

    for source in SOURCES:
        module = importlib.import_module("inspect_" + source)
        inspector = None

        for name in ("inspect", "inspect_" + source, "run_inspection"):
            inspector = getattr(module, name, None)

            if callable(inspector):
                break

        if inspector is None:
            raise RuntimeError(f"Inspection function missing: {source}")

        with redirect_stdout(StringIO()):
            accepted, review = inspector()

        print(f"{source}: {len(accepted)} accepted, {len(review)} review")

        for job in accepted:
            jobs.append(prepare_job(job, source))

    return jobs


# Load existing deduplicated jobs
def load_previous_jobs():
    if not OUTPUT_FILE.exists():
        return [], 0

    with OUTPUT_FILE.open("r", encoding="utf-8") as file:
        saved = json.load(file)

    if not isinstance(saved, list):
        raise ValueError("Invalid saved JSON")

    jobs = []

    for record in saved:
        sources = record.get("source_records")

        if sources:
            for item in sources:
                if item.get("source") not in SOURCES:
                    raise ValueError("Invalid saved source")

                jobs.append(
                    prepare_job(item["job"], item["source"])
                )
        else:
            if record.get("source") not in SOURCES:
                raise ValueError("Invalid saved source")

            jobs.append(
                prepare_job(record["job"], record["source"])
            )

    return jobs, len(saved)


# Combine old and new jobs
def combine_jobs(previous, new):
    combined = {}

    for job in previous + new:
        key = (job["source"], job["job_id"])

        if not job["job_id"]:
            raise ValueError("Job ID is missing")

        if key in combined and job["source"] == "headcount":
            old_postings = combined[key]["job"].get("postings") or []
            new_postings = job["job"].get("postings") or []

            postings = []
            seen = set()

            for posting in old_postings + new_postings:
                if not isinstance(posting, dict):
                    continue

                posting_key = (
                    get_id(posting.get("source")),
                    get_id(posting.get("source_posting_id")),
                    get_id(posting.get("posting_url")),
                    get_id(posting.get("application_url"))
                )

                if posting_key not in seen:
                    seen.add(posting_key)
                    postings.append(posting)

            updated = dict(job["job"])
            updated["postings"] = postings
            job = prepare_job(updated, "headcount")

        combined[key] = job

    return list(combined.values())


# Deduplicate jobs
def deduplicate(jobs):
    parent = list(range(len(jobs)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]

        return index

    def merge(first, second):
        first = find(first)
        second = find(second)

        if first != second:
            parent[second] = first

    seen = {}

    for index, job in enumerate(jobs):
        keys = [("ats", identity) for identity in job["identities"]]

        if job["job_id"]:
            keys.append(("source", job["source"], job["job_id"]))

        for key in keys:
            if key in seen:
                merge(index, seen[key])
            else:
                seen[key] = index

    # Headcount duplicate postings
    seen_postings = {}

    for index, job in enumerate(jobs):
        if job["source"] != "headcount":
            continue

        if not job["company"] or not job["title"]:
            continue

        for source, posting_id in job["source_posting_ids"]:
            key = (source, posting_id, job["company"], job["title"])

            if key in seen_postings:
                merge(index, seen_postings[key])
            else:
                seen_postings[key] = index

    groups = defaultdict(list)

    for index, job in enumerate(jobs):
        groups[find(index)].append(job)

    unique = []
    confirmed = []

    for group in groups.values():
        if len(group) > 1:
            confirmed.append(group)

        best = min(
            group,
            key=lambda job: (
                job["source"] == "headcount",
                -len(job["description"])
            )
        )

        record = dict(best)

        record["sources"] = [
            (job["source"], job["job_id"])
            for job in group
        ]

        record["source_records"] = group

        # Keep all source postings
        postings = []
        seen_postings = set()

        for original in group:
            if original["source"] != "headcount":
                continue

            for posting in original["job"].get("postings") or []:
                if not isinstance(posting, dict):
                    continue

                key = (
                    get_id(posting.get("source")),
                    get_id(posting.get("source_posting_id")),
                    get_id(posting.get("posting_url")),
                    get_id(posting.get("application_url"))
                )

                if key not in seen_postings:
                    seen_postings.add(key)
                    postings.append(posting)

        if record["source"] == "headcount":
            record["job"] = dict(record["job"])
            record["job"]["postings"] = postings

        record["all_source_postings"] = postings
        unique.append(record)

    return unique, confirmed


# Check possible duplicates
def check_possible_duplicates(jobs):
    title_words = defaultdict(list)

    for index, job in enumerate(jobs):
        words = {
            word for word in job["title"].split()
            if len(word) >= 4
        }

        for word in words:
            title_words[word].append(index)

    compared = set()
    matches = []

    for indices in title_words.values():
        for position, first_id in enumerate(indices):
            for second_id in indices[position + 1:]:
                pair = tuple(sorted((first_id, second_id)))

                if pair in compared:
                    continue

                compared.add(pair)

                first = jobs[first_id]
                second = jobs[second_id]

                first_sources = {s for s, _ in first["sources"]}
                second_sources = {s for s, _ in second["sources"]}

                if first_sources == second_sources:
                    continue

                title_score = similar(first["title"], second["title"])

                if title_score < 0.85:
                    continue

                company_score = similar(first["company"], second["company"])
                same_location = bool(first["locations"] & second["locations"])

                description_score = 0

                if min(len(first["description"]), len(second["description"])) >= 250:
                    description_score = similar(
                        first["description"][:1500],
                        second["description"][:1500]
                    )

                if (
                    (company_score >= 0.88 and (
                        (title_score >= 0.94 and same_location)
                        or description_score >= 0.88
                    ))
                    or (title_score >= 0.96 and description_score >= 0.96)
                ):
                    matches.append(pair)

    parent = list(range(len(jobs)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]

        return index

    held = set()

    for first, second in matches:
        parent[find(second)] = find(first)
        held.update((first, second))

    groups = defaultdict(list)

    for index in sorted(held):
        groups[find(index)].append(jobs[index])

    possible = list(groups.values())

    ready = [
        job for index, job in enumerate(jobs)
        if index not in held
    ]

    return ready, possible


# Save JSON
def save_jobs(jobs):
    def make_json(value):
        if isinstance(value, dict):
            return {
                key: make_json(item)
                for key, item in value.items()
            }

        if isinstance(value, (list, tuple, set)):
            return [make_json(item) for item in value]

        return value

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    temp_file = OUTPUT_FILE.with_suffix(".json.tmp")

    try:
        with temp_file.open("w", encoding="utf-8") as file:
            json.dump(
                make_json(jobs),
                file,
                ensure_ascii=False,
                indent=2
            )

        os.replace(temp_file, OUTPUT_FILE)

    finally:
        if temp_file.exists():
            temp_file.unlink()


# Show duplicate records
def show_duplicates(groups):
    if not groups:
        return

    print("\nDUPLICATE RECORDS")
    print("=" * 45)

    for number, group in enumerate(groups, 1):
        first = group[0]

        print(f"\nGroup {number}")
        print("Company:", first["company"])
        print("Title:", first["title"])
        print("Records:", len(group))

        for job in group:
            print(" ", job["source"], "|", job["job_id"])


# Run deduplication
def check_duplicates():
    new_jobs = load_jobs()
    previous_jobs, previous_count = load_previous_jobs()

    combined = combine_jobs(previous_jobs, new_jobs)
    unique, confirmed = deduplicate(combined)

    ready, possible = check_possible_duplicates(unique)

    if len(unique) != len(ready) + sum(len(group) for group in possible):
        raise ValueError("Job count mismatch")

    if possible:
        print("\nPossible duplicates found. JSON not updated.")

    else:
        save_jobs(unique)

    print("\nDEDUPLICATION RESULTS")
    print("=" * 45)
    print("Previously saved jobs:", previous_count)
    print("Incoming jobs:", len(new_jobs))
    print("Combined source jobs:", len(combined))
    print("Duplicate groups:", len(confirmed))
    print("Duplicate records merged:", len(combined) - len(unique))
    print("Possible duplicate groups:", len(possible))
    print("Final unique jobs:", len(unique))
    print("Ready for transformation:", len(ready))

    show_duplicates(confirmed)

    if possible:
        print("\nJOBS NEEDING REVIEW")

        for group in possible:
            for job in group:
                print(job["company"], "|", job["title"], "|", job["job_id"])

    else:
        print("\nSaved to:", OUTPUT_FILE)

    return ready, possible


if __name__ == "__main__":
    check_duplicates()
