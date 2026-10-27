
import json
import re
from pathlib import Path
from collections import Counter, defaultdict
from urllib.parse import urlparse


# -----------------------------
# File paths
# -----------------------------
ROOT = Path(__file__).resolve().parents[1]
RAW_FOLDER = ROOT / "data" / "raw" / "ashby"


# -----------------------------
# Restriction patterns
# -----------------------------
CITIZEN = [
    r"\b(?:u\.?s\.?|united states)\s+citizenship\s+(?:is\s+)?(?:required|mandatory|only)\b",
    r"\b(?:must\s+be|required\s+to\s+be)\s+(?:a\s+|an\s+|current\s+)?(?:u\.?s\.?|united states)\s+citizen\b",
    r"\b(?:u\.?s\.?|united states)\s+citizens?\s+only\b",
    r"\bonly\s+(?:u\.?s\.?|united states)\s+citizens\b",
    r"\b(?:requires?|requiring)\b.{0,50}\b(?:u\.?s\.?|united states)\s+citizenship\b",
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
    r"\bactive\s+(?:security\s+)?clearance\b",
    r"\b(?:current|existing)\s+(?:security\s+)?clearance\s+required\b",
]

ELIGIBLE_TO_OBTAIN = [
    r"\b(?:eligible|eligibility|ability|able|willing)\s+to\s+obtain\b",
    r"\bcan\s+obtain\b",
    r"\bcapable\s+of\s+obtaining\b",
    r"\bability\s+to\s+(?:get|secure)\b",
    r"\bability\s+to\s+possess\b",
]

CLEARANCE_AT_HIRE = [
    r"\b(?:active|current|existing)\b.{0,65}\bclearance\s+(?:is\s+)?required\b",
    r"\bmust\s+(?:currently|already)\s+(?:have|hold|possess)\b",
    r"\bclearance\s+required\s+to\s+start\b",
    r"\bclearance\b.{0,50}\b(?:at\s+time\s+of\s+hire|prior\s+to\s+start)\b",
]

F1 = [
    r"\b(?:cannot|can\s*not|will\s*not|do\s*not|does\s*not|not\s+able\s+to)\b.{0,100}\b(?:hire|employ|accept|consider|support)\b.{0,100}\b(?:opt|cpt|f\s*-?\s*1)\b",
    r"\b(?:must\s+not|cannot|can\s*not)\b.{0,120}\b(?:work\s+authorization\s+based\s+on\s+)?(?:opt|cpt)\b",
    r"\b(?:opt|cpt|f\s*-?\s*1)\b.{0,90}\b(?:not\s+eligible|not\s+accepted|not\s+supported|not\s+considered|ineligible)\b",
    r"\b(?:no|not\s+accepting)\s+(?:cpt|opt|f\s*-?\s*1)\b",
    r"\b(?:opt|cpt)\b.{0,80}\b(?:not\s+permitted|not\s+accepted|not\s+eligible)\b",
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
        re.search(pattern, str(text or ""), re.IGNORECASE)
        for pattern in patterns
    )


def description_lines(job):
    description = str(job.get("descriptionPlain") or "")

    for line in description.splitlines():
        line = " ".join(line.split())

        if line:
            yield line


# -----------------------------
# Employer verification
# -----------------------------
def employer_slug(job):
    url = urlparse(str(job.get("jobUrl") or ""))

    parts = url.path.strip("/").split("/")

    if url.hostname == "jobs.ashbyhq.com" and parts[0]:
        return parts[0].lower()

    return "UNKNOWN"


def check_employer(job):
    company = employer_slug(job)

    if company == "UNKNOWN":
        return "UNVERIFIED"

    for field in ("jobUrl", "applyUrl"):
        url = job.get(field)

        if not url:
            continue

        parsed = urlparse(str(url))
        parts = parsed.path.strip("/").split("/")

        if (
            parsed.hostname != "jobs.ashbyhq.com"
            or not parts
            or parts[0].lower() != company
        ):
            return "UNVERIFIED"

    return "MATCH"


# -----------------------------
# US location verification
# -----------------------------
US_NAMES = {
    "US", "USA",
    "UNITED STATES",
    "UNITED STATES OF AMERICA"
}

# Used only when the API does not provide a country.
US_STATES = {
    "ALABAMA", "ALASKA", "ARIZONA", "ARKANSAS",
    "CALIFORNIA", "COLORADO", "CONNECTICUT",
    "DELAWARE", "FLORIDA", "GEORGIA", "HAWAII",
    "IDAHO", "ILLINOIS", "INDIANA", "IOWA",
    "KANSAS", "KENTUCKY", "LOUISIANA", "MAINE",
    "MARYLAND", "MASSACHUSETTS", "MICHIGAN",
    "MINNESOTA", "MISSISSIPPI", "MISSOURI",
    "MONTANA", "NEBRASKA", "NEVADA",
    "NEW HAMPSHIRE", "NEW JERSEY", "NEW MEXICO",
    "NEW YORK", "NORTH CAROLINA", "NORTH DAKOTA",
    "OHIO", "OKLAHOMA", "OREGON", "PENNSYLVANIA",
    "RHODE ISLAND", "SOUTH CAROLINA",
    "SOUTH DAKOTA", "TENNESSEE", "TEXAS",
    "UTAH", "VERMONT", "VIRGINIA", "WASHINGTON",
    "WEST VIRGINIA", "WISCONSIN", "WYOMING",
    "DISTRICT OF COLUMBIA"
}

# Confirmed non-US location labels found in current raw data.
# Unfamiliar labels go to REVIEW instead of being guessed.
NON_US_REGIONS = {
    "MIDDLE EAST",
    "KOREA",
    "SOUTH KOREA",
    "SINGAPORE",
}


def check_location(job):
    countries = []

    locations = [job]

    for item in job.get("secondaryLocations") or []:
        if isinstance(item, dict):
            locations.append(item)

    for item in locations:
        address = item.get("address") or {}

        if not isinstance(address, dict):
            continue

        postal = address.get("postalAddress") or {}

        if not isinstance(postal, dict):
            continue

        country = str(
            postal.get("addressCountry") or ""
        ).strip().upper()

        if country:
            countries.append(country)

    # Use structured API countries first.
    # A job may have several eligible locations.
    if any(country in US_NAMES for country in countries):
        return "US"

    # If all supplied structured countries are foreign,
    # check whether another location has no country.
    unknown_location = False

    for item in locations:
        address = item.get("address") or {}

        if not isinstance(address, dict):
            unknown_location = True
            continue

        postal = address.get("postalAddress") or {}

        if not isinstance(postal, dict):
            unknown_location = True
            continue

        if not postal.get("addressCountry"):
            unknown_location = True

    if countries and not unknown_location:
        return "OUTSIDE_US"

    # Fallback for jobs without structured country
    location = str(job.get("location") or "").strip().upper()

    if location in US_NAMES or location in US_STATES:
        return "US"

    if location in NON_US_REGIONS:
        return "OUTSIDE_US"

    return "UNKNOWN"


# -----------------------------
# Application verification
# -----------------------------
def check_application(job):
    job_id = str(job.get("id") or "")

    for field in ("jobUrl", "applyUrl"):
        url = job.get(field)

        if not isinstance(url, str) or not url.startswith(
            ("https://", "http://")
        ):
            return "INVALID"

        parsed = urlparse(url)
        parts = parsed.path.strip("/").split("/")

        if (
            parsed.scheme not in ("http", "https")
            or parsed.hostname != "jobs.ashbyhq.com"
            or len(parts) < 2
        ):
            return "UNVERIFIED"

        if job_id and parts[1] != job_id:
            return "UNVERIFIED"

    return "VALID"


# -----------------------------
# Job description inspection
# -----------------------------
def check_description(job):
    reasons = set()
    preferred_section = False

    for line in description_lines(job):

        if matches([
            r"^(?:preferred|desired|additional)\s+qualifications?\s*:?\s*$",
            r"^(?:nice\s+to\s+have|preferred\s+skills)\s*:?\s*$"
        ], line):
            preferred_section = True
            continue

        if matches([
            r"^(?:required|minimum|basic)\s+qualifications?\s*:?\s*$",
            r"^requirements?\s*:?\s*$"
        ], line):
            preferred_section = False
            continue

        eeo = matches([
            r"\bwithout\s+regard\s+to\b",
            r"\bregardless\s+of\b"
        ], line)

        optional = (
            preferred_section
            or matches(OPTIONAL, line)
        )

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
                required_now = matches(CLEARANCE_AT_HIRE, line)

                if required_now or not can_obtain:
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
    title = str(job.get("title") or "")

    if job.get("isListed") is False:
        return "Job not listed"

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

    if not job.get("id"):
        review_reasons.add("Missing job ID")

    if not job.get("title") or not job.get("descriptionPlain"):
        review_reasons.add("Missing title or description")

    if check_employer(job) == "UNVERIFIED":
        review_reasons.add("Employer source unverified")

    location = check_location(job)

    if location == "OUTSIDE_US":
        reject_reasons.add("Outside US")

    elif location == "UNKNOWN":
        review_reasons.add("US location unverified")

    application = check_application(job)

    if application == "INVALID":
        reject_reasons.add("Missing or invalid application URL")

    elif application == "UNVERIFIED":
        review_reasons.add("Application URL unverified")

    posting_issue = check_posting(job)

    if posting_issue:
        reject_reasons.add(posting_issue)

    reject_reasons.update(check_description(job))

    # REJECT takes priority over REVIEW
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

        if isinstance(data, dict) and isinstance(
            data.get("jobs"), list
        ):
            batch = data["jobs"]

        elif isinstance(data, list):
            batch = data

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
                "title": job.get("title"),
                "job_id": job.get("id"),
                "location": job.get("location"),
                "reasons": sorted(reasons)
            })

        else:
            rejection_reasons.update(reasons)

    print("\nASHBY EXTRACTION DATA")
    print("=" * 60)

    for company, counts in sorted(employers.items()):
        print(f"{company}: {sum(counts.values())} jobs")

    print("\nASHBY INSPECTION RESULTS")
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
            print(f"   Location: {job['location']}")
            print(f"   Reasons: {', '.join(job['reasons'])}")

    print("\nINSPECTION COMPLETED")
    print("=" * 60)

    return accepted_jobs, review_jobs


if __name__ == "__main__":
    inspect()
