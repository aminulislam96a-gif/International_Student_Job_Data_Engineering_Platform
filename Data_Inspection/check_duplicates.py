
import importlib
import re
import sys
from collections import defaultdict
from contextlib import redirect_stdout
from difflib import SequenceMatcher
from html import unescape
from io import StringIO
from urllib.parse import urlparse


SOURCES = ["headcount", "lever", "ashby", "greenhouse"]


# Clean text
def clean(value):
    if isinstance(value, dict):
        value = value.get("value", "")

    value = unescape(str(value or "")).lower()
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)

    return " ".join(value.split())


def company_name(value):
    words = clean(value).split()
    endings = {
        "inc", "llc", "ltd",
        "corp", "corporation", "incorporated"
    }

    return " ".join(
        word for word in words
        if word not in endings
    )


def similar(first, second):
    if not first or not second:
        return 0

    return SequenceMatcher(None, first, second).ratio()


# Get official ATS job identity
def ats_id(url):
    parsed = urlparse(str(url or ""))
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


# Get job URLs from each source
def job_urls(job, source):
    if source == "headcount":
        urls = []

        for posting in job.get("postings") or []:
            if isinstance(posting, dict):
                for field in ("posting_url", "application_url"):
                    url = posting.get(field)

                    if isinstance(url, dict):
                        url = url.get("value")

                    urls.append(url)

        return urls

    if source == "lever":
        return [job.get("hostedUrl"), job.get("applyUrl")]

    if source == "ashby":
        return [job.get("jobUrl"), job.get("applyUrl")]

    return [job.get("absolute_url")]


# Prepare job information for comparison
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
            location.get("name")
            if isinstance(location, dict)
            else location
        ]

    identities = set()

    for url in job_urls(job, source):
        identity = ats_id(url)

        if identity:
            identities.add(identity)

    return {
        "source": source,
        "job_id": str(job_id or ""),
        "job": job,
        "company": company_name(company),
        "title": clean(title),
        "description": clean(description)[:3000],
        "locations": {
            clean(place) for place in locations
            if clean(place)
        },
        "identities": identities
    }


# Load accepted jobs from saved files
def load_jobs():
    jobs = []

    print("\nACCEPTED JOBS FROM SAVED FILES")
    print("=" * 55)

    for source in SOURCES:
        module = importlib.import_module("inspect_" + source)
        inspector = None

        for name in ("inspect", "inspect_" + source, "run_inspection"):
            inspector = getattr(module, name, None)

            if callable(inspector):
                break
        else:
            raise RuntimeError(
                f"Inspection function not found: inspect_{source}.py"
            )

        with redirect_stdout(StringIO()):
            result = inspector()

        if not isinstance(result, (tuple, list)) or len(result) != 2:
            raise RuntimeError(
                f"inspect_{source}.py must return "
                "(accepted_jobs, review_jobs)"
            )

        accepted, review = result

        print(
            f"{source}: {len(accepted)} accepted, "
            f"{len(review)} review"
        )

        for job in accepted:
            jobs.append(prepare_job(job, source))

    return jobs


# Deduplicate all jobs together
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

    # Check confirmed duplicates
    seen = {}

    for index, job in enumerate(jobs):
        keys = [
            ("ats", identity)
            for identity in job["identities"]
        ]

        if job["job_id"]:
            keys.append(
                ("source", job["source"], job["job_id"])
            )

        for key in keys:
            if key in seen:
                merge(index, seen[key])
            else:
                seen[key] = index

    groups = defaultdict(list)

    for index, job in enumerate(jobs):
        groups[find(index)].append(job)

    confirmed = []
    unique = []

    for group in groups.values():
        if len(group) > 1:
            confirmed.append(group)

        # Prefer original ATS records over Headcount
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
        unique.append(record)

    # Find possible duplicates
    title_words = defaultdict(list)

    for index, job in enumerate(unique):
        words = {
            word for word in job["title"].split()
            if len(word) >= 4
        }

        for word in words:
            title_words[word].append(index)

    compared = set()
    review_pairs = []

    for indices in title_words.values():
        for position, first_id in enumerate(indices):
            for second_id in indices[position + 1:]:
                pair = tuple(sorted((first_id, second_id)))

                if pair in compared:
                    continue

                compared.add(pair)

                first = unique[first_id]
                second = unique[second_id]

                first_sources = {
                    source for source, _ in first["sources"]
                }

                second_sources = {
                    source for source, _ in second["sources"]
                }

                if first_sources == second_sources:
                    continue

                title_score = similar(
                    first["title"], second["title"]
                )

                if title_score < 0.85:
                    continue

                company_score = similar(
                    first["company"], second["company"]
                )

                same_location = bool(
                    first["locations"] & second["locations"]
                )

                description_score = 0

                if min(
                    len(first["description"]),
                    len(second["description"])
                ) >= 250:
                    description_score = similar(
                        first["description"][:1500],
                        second["description"][:1500]
                    )

                possible = (
                    (
                        company_score >= 0.88
                        and (
                            (title_score >= 0.94 and same_location)
                            or description_score >= 0.88
                        )
                    )
                    or (
                        title_score >= 0.96
                        and description_score >= 0.96
                    )
                )

                if possible:
                    review_pairs.append(pair)

    # Group jobs needing review
    review_parent = list(range(len(unique)))

    def review_find(index):
        while review_parent[index] != index:
            review_parent[index] = review_parent[
                review_parent[index]
            ]

            index = review_parent[index]

        return index

    held_indices = set()

    for first, second in review_pairs:
        review_parent[review_find(second)] = review_find(first)
        held_indices.update((first, second))

    possible_groups = defaultdict(list)

    for index in sorted(held_indices):
        possible_groups[review_find(index)].append(unique[index])

    possible = list(possible_groups.values())

    ready = [
        job for index, job in enumerate(unique)
        if index not in held_indices
    ]

    # Validate counts
    removed = sum(len(group) - 1 for group in confirmed)
    held = sum(len(group) for group in possible)

    assert len(jobs) == len(unique) + removed
    assert len(unique) == len(ready) + held

    return ready, possible, confirmed, unique


# Print final results
def check_duplicates():
    jobs = load_jobs()
    ready, possible, confirmed, unique = deduplicate(jobs)

    held = sum(len(group) for group in possible)

    print("\nCROSS-SOURCE DEDUPLICATION")
    print("=" * 55)

    print(f"Accepted jobs: {len(jobs)}")
    print(f"Confirmed duplicate groups: {len(confirmed)}")
    print(f"Duplicate records merged: {len(jobs) - len(unique)}")
    print(f"Possible duplicate groups: {len(possible)}")
    print(f"Jobs held for review: {held}")
    print(f"Ready for availability checks: {len(ready)}")

    for group in confirmed[:20]:
        print(
            "MERGED:",
            [(job["source"], job["job_id"]) for job in group]
        )

    for group in possible[:20]:
        print(
            "REVIEW:",
            [
                (job["source"], job["job_id"], job["title"])
                for job in group
            ]
        )

    print("\nAll records accounted for: YES")

    return ready, possible


# Test confirmed duplicate matching
def self_test():
    first = prepare_job({
        "job_id": "100",
        "title": "Data Engineer",
        "employer_name": "Acme",
        "postings": [{
            "posting_url":
            "https://boards.greenhouse.io/acme/jobs/1234"
        }]
    }, "headcount")

    second = prepare_job({
        "id": 1234,
        "title": "Data Engineer",
        "company_name": "Acme",
        "absolute_url":
        "https://job-boards.greenhouse.io/acme/jobs/1234"
    }, "greenhouse")

    third = prepare_job({
        "id": 1235,
        "title": "Data Engineer",
        "company_name": "Acme",
        "absolute_url":
        "https://job-boards.greenhouse.io/acme/jobs/1235"
    }, "greenhouse")

    ready, possible, confirmed, unique = deduplicate(
        [first, second, third]
    )

    assert len(confirmed) == 1
    assert len(unique) == 2
    assert (
        len(ready) + sum(len(group) for group in possible)
        == 2
    )

    print(
        "Self-test passed: matching posting merged; "
        "separate requisition retained."
    )


if __name__ == "__main__":
    if "--test" in sys.argv:
        self_test()
    else:
        check_duplicates()
