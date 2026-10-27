
import json
import re
from html import unescape
from pathlib import Path
from collections import Counter, defaultdict
from urllib.parse import urlparse


# -----------------------------
# File paths
# -----------------------------
ROOT = Path(__file__).resolve().parents[1]
RAW_FOLDER = ROOT / "data" / "raw" / "lever"


# -----------------------------
# Restriction patterns
# -----------------------------
CITIZEN = [
    r"\b(?:u\.?s\.?|united states)\s+citizenship\s+(?:is\s+)?(?:required|mandatory|only)\b",
    r"\b(?:must\s+be|required\s+to\s+be)\s+(?:a\s+|an\s+|current\s+)?(?:u\.?s\.?|united states)\s+citizen\b",
    r"\b(?:u\.?s\.?|united states)\s+citizens?\s+only\b",
    r"\bonly\s+(?:u\.?s\.?|united states)\s+citizens\b",
    r"\b(?:requires?|requiring)\s+(?:u\.?s\.?|united states)\s+citizenship\b",
    r"\b(?:u\.?s\.?|united states)\s+citizenship\s+required\b",
    r"\b(?:u\.?s\.?|united states)\s+citizen(?:ship)?\s+(?:with|and)\s+(?:an?\s+)?(?:active|ability)\b",
    r"\b(?:u\.?s\.?|united states)\s+citizenship\s+(?:is\s+)?(?:a\s+)?requirement\b",
    r"\b(?:u\.?s\.?|united states)\s+citizens?\s+(?:are\s+)?required\b",
]

US_PERSON = [
    r"\bmust\s+be\s+(?:a\s+)?u\.?s\.?\s+person\b",
    r"\bu\.?s\.?\s+person\s+status\s+(?:is\s+)?required\b",
    r"\bu\.?s\.?\s+persons?\s+only\b",
    r"\b(?:require[ds]?|mandatory)\b.{0,45}\bu\.?s\.?\s+person\b",
]

GREEN_CARD = [
    r"\b(?:must|required|requires?|need)\b.{0,90}\b(?:green\s*card|permanent\s+residen(?:t|cy))\b",
    r"\b(?:green\s*card|permanent\s+residen(?:t|cy))\b.{0,60}\b(?:required|mandatory|only)\b",
    r"\b(?:citizens?|permanent\s+residents?|green\s*card\s+holders?)\s+only\b",
]

CLEARANCE = [
    r"\b(?:must|shall)\s+(?:already\s+)?(?:have|hold|possess|maintain)\b.{0,80}\b(?:security\s+)?clearance\b",
    r"\b(?:must|shall)\s+(?:already\s+)?(?:have|hold|possess)\b.{0,80}\b(?:secret|top[ -]?secret|ts\s*/\s*sci)\b",
    r"\b(?:currently\s+hold|currently\s+possess)\b.{0,80}\bclearance\b",
    r"\b(?:active|current|existing)\b.{0,55}\b(?:secret|top[ -]?secret|ts\s*/\s*sci)\b.{0,35}\bclearance\b",
    r"\b(?:active|current|existing)\b.{0,35}\bclearance\b.{0,35}\b(?:secret|top[ -]?secret|ts\s*/\s*sci)\b",
    r"\b(?:secret|top[ -]?secret|ts\s*/\s*sci)\b.{0,35}\bclearance\b.{0,40}\b(?:required|mandatory|at\s+time\s+of\s+hire|prior\s+to\s+start)\b",
    r"\b(?:clearance|cleared)\b.{0,45}\b(?:required\s+at\s+time\s+of\s+hire|required\s+prior\s+to\s+start)\b",
]

ELIGIBLE_TO_OBTAIN = [
    r"\b(?:eligible|eligibility|ability|able|willing)\s+to\s+obtain\b",
    r"\bcan\s+obtain\b",
    r"\bcapable\s+of\s+obtaining\b",
    r"\bability\s+to\s+(?:get|secure)\b",
]

ABILITY_TO_POSSESS = [
    r"\bability\s+to\s+possess\b.{0,80}\bclearance\b",
    r"\bable\s+to\s+possess\b.{0,80}\bclearance\b",
]

CLEARANCE_AT_HIRE = [
    r"\b(?:active|current|existing)\b.{0,65}\bclearance\b.{0,60}\b(?:required\s+at\s+time\s+of\s+hire|prior\s+to\s+start)\b",
    r"\b(?:active|current|existing)\b.{0,65}\bclearance\s+(?:is\s+)?required\b",
    r"\b(?:must\s+currently\s+hold|must\s+already\s+possess)\b",
    r"\bclearance\s+required\s+to\s+start\b",
]

F1 = [
    r"\b(?:cannot|can\s*not|will\s*not|do\s*not|does\s*not|not\s+able\s+to|aren.t\s+able\s+to)\b.{0,100}\b(?:hire|employ|accept|consider|support)\b.{0,100}\b(?:opt|cpt|f\s*-?\s*1)\b",
    r"\b(?:must\s+not|cannot|can\s*not)\b.{0,120}\b(?:work\s+authorization\s+based\s+on\s+)?(?:opt|cpt)\b",
    r"\b(?:opt|cpt|f\s*-?\s*1)\b.{0,90}\b(?:not\s+eligible|not\s+accepted|not\s+supported|not\s+considered|ineligible)\b",
    r"\b(?:no\s+|not\s+)(?:opt|cpt)\s+(?:work\s+authorization|applicants|candidates|students)\b",
    r"\b(?:no|without)\s+(?:f\s*-?\s*1|opt|cpt)\s+(?:visa|authorization|candidates)\b",
    r"\b(?:opt|cpt)\b.{0,80}\b(?:not\s+permitted|not\s+accepted|not\s+eligible|cannot\s+be\s+considered)\b",
    r"\b(?:no|not\s+accepting)\s+(?:cpt|opt|f\s*-?\s*1)\b",
]

OPTIONAL = [
    r"\bpreferred\b",
    r"\bdesired\b",
    r"\ba\s+plus\b",
    r"\bnice\s+to\s+have\b",
]


# -----------------------------
# Helper functions
# -----------------------------
def matches(patterns, text):
    return any(
        re.search(pattern, str(text), re.IGNORECASE)
        for pattern in patterns
    )


def plain(text):
    text = re.sub(
        r"<\s*(?:br|/p|/li|/div)\b[^>]*>",
        "\n",
        str(text or ""),
        flags=re.IGNORECASE
    )

    text = re.sub(r"<[^>]+>", " ", text)

    return unescape(text).replace("\xa0", " ")


def description_lines(job):
    parts = [
        job.get("openingPlain"),
        job.get("descriptionPlain"),
        job.get("additionalPlain")
    ]

    if not job.get("descriptionPlain"):
        parts.append(job.get("description"))

    if not job.get("additionalPlain"):
        parts.append(job.get("additional"))

    for block in parts:
        for line in plain(block).splitlines():
            line = " ".join(line.split())

            if line:
                yield line, False

    for section in job.get("lists") or []:
        if not isinstance(section, dict):
            continue

        heading = str(section.get("text") or "")

        preferred = (
            matches(OPTIONAL, heading)
            or matches([r"\bbonus\b"], heading)
        )

        for line in plain(section.get("content")).splitlines():
            line = " ".join(line.split())

            if line:
                yield line, preferred


# -----------------------------
# Employer verification
# -----------------------------
def employer_slug(job):
    url = urlparse(
        str(job.get("hostedUrl") or job.get("applyUrl") or "")
    )

    parts = url.path.strip("/").split("/")

    if url.hostname == "jobs.lever.co" and parts[0]:
        return parts[0].lower()

    return "UNKNOWN"


def check_employer(job):
    hosted = job.get("hostedUrl")
    apply = job.get("applyUrl")

    companies = set()

    for url in (hosted, apply):
        if not url:
            continue

        parsed = urlparse(str(url))
        parts = parsed.path.strip("/").split("/")

        if parsed.hostname != "jobs.lever.co":
            return "UNVERIFIED"

        if not parts[0]:
            return "UNVERIFIED"

        companies.add(parts[0].lower())

    if len(companies) == 1:
        return "MATCH"

    return "UNVERIFIED"


# -----------------------------
# US location verification
# -----------------------------
def check_location(job):
    country = str(job.get("country") or "").strip().upper()

    categories = job.get("categories") or {}

    if isinstance(categories, dict):
        location = str(
            categories.get("location") or ""
        ).strip().upper()
    else:
        location = ""

    if not location:
        location = str(job.get("location") or "").strip().upper()

    us_names = {
        "US", "USA",
        "UNITED STATES",
        "UNITED STATES OF AMERICA"
    }

    # Use the API's structured country code
    if country in us_names:
        if location in ("EUROPE", "EUROPEAN UNION"):
            return "UNKNOWN"

        return "US"

    if len(country) == 2 and country.isalpha():
        return "OUTSIDE_US"

    if country:
        return "UNKNOWN"

    # The country field is missing
    if location in us_names:
        return "US"

    if location in ("EUROPE", "EUROPEAN UNION"):
        return "OUTSIDE_US"

    return "UNKNOWN"


# -----------------------------
# Check application URLs
# -----------------------------
def check_application(job):
    application = job.get("applyUrl") or job.get("hostedUrl")

    if not application:
        return "INVALID"

    if not isinstance(application, str) or not application.startswith(
        ("https://", "http://")
    ):
        return "INVALID"

    for field in ("hostedUrl", "applyUrl"):
        url = job.get(field)

        if not url:
            continue

        parsed = urlparse(str(url))
        parts = parsed.path.strip("/").split("/")

        if (
            parsed.scheme not in ("http", "https")
            or parsed.hostname != "jobs.lever.co"
            or len(parts) < 2
        ):
            return "UNVERIFIED"

        if job.get("id") and parts[1] != str(job["id"]):
            return "UNVERIFIED"

    return "VALID"


# -----------------------------
# Job description inspection
# -----------------------------
def check_description(job):
    reasons = set()

    for line, preferred in description_lines(job):
        eeo = matches([
            r"\bwithout\s+regard\s+to\b",
            r"\bregardless\s+of\b"
        ], line)

        optional = preferred or matches(OPTIONAL, line)

        if not eeo and not optional:
            if matches(CITIZEN, line):
                reasons.add("US citizenship required")

            if matches(US_PERSON, line):
                reasons.add("US-person status required")

            if matches(GREEN_CARD, line):
                reasons.add(
                    "Permanent residency or citizenship required"
                )

            if matches(CLEARANCE, line):
                can_obtain = matches(ELIGIBLE_TO_OBTAIN, line)
                can_possess = matches(ABILITY_TO_POSSESS, line)
                required_now = matches(CLEARANCE_AT_HIRE, line)

                if required_now or (
                    not can_obtain and not can_possess
                ):
                    reasons.add(
                        "Existing security clearance required"
                    )

        if matches(F1, line):
            reasons.add("Explicit OPT/CPT/F-1 restriction")

        if matches([
            r"\b(?:contingent\s+(?:on|upon)|subject\s+to)\s+(?:a\s+)?contract\s+award\b"
        ], line):
            reasons.add("Contract award contingent")

    return reasons


# -----------------------------
# Check real job opening
# -----------------------------
def check_posting(job):
    title = str(job.get("text") or "")

    if matches([
        r"\btalent\s+(?:pool|network|community)\b",
        r"\bgeneral\s+application\b",
        r"\bconfidential\s+requisition\b"
    ], title):
        return "Not a specific job opening"

    return None


# -----------------------------
# Inspect one job
# -----------------------------
def inspect_job(job):
    reject_reasons = set()
    review_reasons = set()

    # Required information
    if not job.get("id"):
        review_reasons.add("Missing job ID")

    if not job.get("text") or not any(description_lines(job)):
        review_reasons.add("Missing title or description")

    # Employer verification
    if check_employer(job) == "UNVERIFIED":
        review_reasons.add("Employer source unverified")

    # Location verification
    location = check_location(job)

    if location == "OUTSIDE_US":
        reject_reasons.add("Outside US")

    elif location == "UNKNOWN":
        review_reasons.add("US location unverified")

    # Application URL
    application = check_application(job)

    if application == "INVALID":
        reject_reasons.add("Missing or invalid application URL")

    elif application == "UNVERIFIED":
        review_reasons.add("Application URL unverified")

    # Real job opening
    posting_issue = check_posting(job)

    if posting_issue:
        reject_reasons.add(posting_issue)

    # Work authorization and other restrictions
    reject_reasons.update(check_description(job))

    # Same decision priority as Headcount
    if reject_reasons:
        decision = "REJECT"

    elif review_reasons:
        decision = "REVIEW"

    else:
        decision = "KEEP"

    return decision, reject_reasons | review_reasons


# -----------------------------
# Load and deduplicate jobs
# -----------------------------
def load_jobs():
    jobs = {}
    files_read = 0
    duplicates = 0
    errors = []

    for path in sorted(RAW_FOLDER.rglob("*.json")):
        try:
            with open(path, "r", encoding="utf-8") as file:
                data = json.load(file)

        except (OSError, ValueError) as error:
            errors.append(f"{path.name}: {error}")
            continue

        if isinstance(data, list):
            batch = data

        elif isinstance(data, dict) and isinstance(
            data.get("data"), list
        ):
            batch = data["data"]

        elif isinstance(data, dict) and isinstance(
            data.get("jobs"), list
        ):
            batch = data["jobs"]

        elif isinstance(data, dict) and isinstance(
            data.get("pages"), list
        ):
            batch = [
                job
                for page in data["pages"]
                if isinstance(page, dict)
                for job in page.get("data") or []
            ]

        else:
            errors.append(
                f"{path.name}: Unexpected JSON structure"
            )
            continue

        files_read += 1

        for index, job in enumerate(batch):
            if not isinstance(job, dict):
                continue

            job_id = job.get("id")

            if job_id:
                key = (employer_slug(job), str(job_id))

                if key in jobs:
                    duplicates += 1
                    continue
            else:
                key = (str(path), index)

            jobs[key] = job

    return list(jobs.values()), files_read, duplicates, errors


# -----------------------------
# Main inspection
# -----------------------------
def inspect():
    jobs, files_read, duplicates, errors = load_jobs()

    totals = Counter()
    employers = defaultdict(Counter)
    rejection_reasons = Counter()
    review_reasons = Counter()

    accepted_jobs = []
    review_jobs = []

    for job in jobs:
        company = employer_slug(job)
        decision, reasons = inspect_job(job)

        totals[decision] += 1
        employers[company][decision] += 1

        if decision == "KEEP":
            accepted_jobs.append(job)

        elif decision == "REVIEW":
            review_reasons.update(reasons)

            review_jobs.append({
                "company": company,
                "employer": company,
                "title": job.get("text"),
                "job_id": job.get("id"),
                "country": job.get("country"),
                "location": (
                    job.get("categories") or {}
                ).get("location")
                if isinstance(job.get("categories"), dict)
                else None,
                "reasons": sorted(reasons)
            })

        else:
            rejection_reasons.update(reasons)

    # -----------------------------
    # Terminal output
    # -----------------------------
    print("\nLEVER EXTRACTION DATA")
    print("=" * 60)

    for company, counts in sorted(employers.items()):
        print(f"{company}: {sum(counts.values())} jobs")

    print("\nLEVER INSPECTION RESULTS")
    print("=" * 60)

    print(f"Files inspected: {files_read}")
    print(f"Jobs inspected: {len(jobs)}")
    print(f"Duplicate records skipped: {duplicates}")
    print(f"Files with errors: {len(errors)}")

    print("\nFINAL DECISIONS")
    print("-" * 60)

    print(f"KEEPING FOR TRANSFORMATION: {totals['KEEP']}")
    print(f"REJECTED: {totals['REJECT']}")
    print(f"NEEDS REVIEW: {totals['REVIEW']}")

    print("\nREJECTION REASONS (CAN OVERLAP)")
    print("-" * 60)

    for reason, count in rejection_reasons.most_common():
        print(f"{reason}: {count}")

    print("\nREVIEW REASONS (CAN OVERLAP)")
    print("-" * 60)

    for reason, count in review_reasons.most_common():
        print(f"{reason}: {count}")

    print("\nBY EMPLOYER")
    print("-" * 60)

    for company, counts in sorted(employers.items()):
        total = sum(counts.values())

        print(
            f"{company:<18}"
            f"Total: {total:<6}"
            f"Keeping: {counts['KEEP']:<6}"
            f"Rejected: {counts['REJECT']:<6}"
            f"Review: {counts['REVIEW']}"
        )

    print("\nDATA VALIDATION")
    print("-" * 60)

    all_classified = (
        totals["KEEP"]
        + totals["REJECT"]
        + totals["REVIEW"]
        == len(jobs)
    )

    print(
        f"All jobs classified: "
        f"{'YES' if all_classified else 'NO'}"
    )

    print(f"Jobs needing review: {len(review_jobs)}")

    if errors:
        print("\nFILE ERRORS")
        print("-" * 60)

        for error in errors:
            print(error)

    if review_jobs:
        print("\nJOBS NEEDING REVIEW")
        print("-" * 60)

        for number, job in enumerate(review_jobs, start=1):
            print(f"{number}. Company: {job['company']}")
            print(f"   Title: {job['title']}")
            print(f"   Job ID: {job['job_id']}")
            print(f"   Country: {job['country']}")
            print(f"   Location: {job['location']}")
            print(f"   Reasons: {', '.join(job['reasons'])}")

    print("\nINSPECTION COMPLETED")
    print("=" * 60)

    return accepted_jobs, review_jobs


if __name__ == "__main__":
    inspect()
