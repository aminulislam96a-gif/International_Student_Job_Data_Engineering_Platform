
import json
import re
from collections import Counter, defaultdict
from html import unescape
from pathlib import Path
from urllib.parse import urlparse


# -----------------------------
# File paths
# -----------------------------
ROOT = Path(__file__).resolve().parents[1]
RAW_FOLDER = ROOT / "data" / "raw" / "greenhouse"


# -----------------------------
# US location reference
# -----------------------------
US_STATES = (
    "Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|"
    "Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|"
    "Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|"
    "Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|"
    "New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|"
    "Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|"
    "Virginia|Washington|West Virginia|Wisconsin|Wyoming"
)

US_CODES = (
    "AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|"
    "MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|"
    "SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC"
)

US_CITIES = {
    "atlanta", "austin", "baltimore", "bangor", "beaumont", "boise",
    "boston", "buffalo", "charlotte", "chicago", "cleveland",
    "colorado springs", "columbus", "corpus christi", "dallas",
    "davenport", "denver", "des moines", "detroit", "el segundo",
    "fayetteville", "fond du lac", "grand rapids", "greensboro",
    "harrisburg", "hartford", "houston", "huntsville",
    "indianapolis", "jacksonville", "knoxville", "lakeville",
    "little rock", "los angeles", "louisville", "macon",
    "mankato", "memphis", "midland-odessa", "minneapolis",
    "new orleans", "new york", "norfolk", "phoenix", "portland",
    "rensselaer", "richmond", "rockville", "sacramento",
    "san angelo", "san antonio", "san diego", "san francisco",
    "saint louis", "seattle", "silver spring", "spokane",
    "sun prairie", "tampa", "temple", "toledo", "tyler",
    "tysons", "washington dc", "wilkes barre", "wilmington",
    "albuquerque", "bethesda", "washington"
}


# -----------------------------
# Restriction patterns
# -----------------------------
CITIZEN = [
    r"\b(?:US|U\.S\.|United States)\s+citizenship\s+(?:is\s+)?(?:required|mandatory)\b",
    r"\b(?:must|need|required)\s+(?:to\s+)?be\s+(?:an?\s+)?(?:US|U\.S\.|United States)\s+citizen\b",
    r"\b(?:US|U\.S\.|United States)\s+citizens?\s+only\b",
    r"\bonly\s+(?:US|U\.S\.|United States)\s+citizens\b",
    r"\b(?:requires?|requiring)\b.{0,40}\b(?:US|U\.S\.|United States)\s+citizenship\b",
]

US_PERSON = [
    r"\bmust\s+be\s+(?:a\s+)?(?:US|U\.S\.)\s+person\b",
    r"\b(?:US|U\.S\.)\s+persons?\s+only\b",
    r"\b(?:US|U\.S\.)\s+person\s+status\s+(?:is\s+)?required\b",
]

GREEN_CARD = [
    r"\b(?:must|required|requires?|need)\b.{0,100}\b(?:green\s*card|permanent\s+residen(?:t|cy))\b",
    r"\b(?:green\s*card|permanent\s+residen(?:t|cy))\b.{0,65}\b(?:required|mandatory|only)\b",
    r"\b(?:green\s*card|permanent\s+residen(?:t|cy))\s+or\s+(?:US|U\.S\.|United States)\s+citizenship\b",
    r"\b(?:US|U\.S\.|United States)\s+citizenship\s+or\s+(?:a\s+)?(?:green\s*card|permanent\s+residen(?:t|cy))\b",
    r"\b(?:citizens?|permanent\s+residents?|green\s*card\s+holders?)\s+only\b",
]

CLEARANCE = [
    r"\b(?:active|current|existing)\b.{0,55}\b(?:security\s+)?clearance\b",
    r"\b(?:must|shall)\s+(?:already\s+)?(?:have|hold|possess)\b.{0,85}\b(?:security\s+)?clearance\b",
    r"\b(?:secret|top[ -]?secret|ts\s*/\s*sci)\b.{0,35}\bclearance\b.{0,40}\b(?:required|mandatory|at\s+time\s+of\s+hire)\b",
    r"\brequired\s+(?:security\s+)?clearance\s*:\s*(?:secret|top[ -]?secret|ts\s*/\s*sci)\b",
    r"\b(?:security\s+)?clearance\s+required\s+(?:at\s+time\s+of\s+hire|prior\s+to\s+start)\b",
]

CAN_OBTAIN = [
    r"\b(?:ability|eligibility|eligible|able|willing)\s+to\s+obtain\b",
    r"\bcan\s+obtain\b",
    r"\bcapable\s+of\s+obtaining\b",
    r"\b(?:ability|able)\s+to\s+possess\b",
]

REQUIRED_NOW = [
    r"\b(?:must\s+currently\s+hold|must\s+already\s+possess)\b",
    r"\b(?:active|current|existing)\b.{0,60}\bclearance\b.{0,50}\b(?:required|mandatory)\b",
    r"\bclearance\b.{0,45}\b(?:required\s+at\s+time\s+of\s+hire|prior\s+to\s+start)\b",
]

F1 = [
    r"\b(?:cannot|can\s*not|will\s*not|do\s*not|does\s*not|not\s+able\s+to)\b.{0,110}\b(?:hire|employ|accept|consider|support)\b.{0,120}\b(?:f\s*-?\s*1|stem\s*opt|opt|cpt)\b",
    r"\b(?:f\s*-?\s*1|stem\s*opt|opt|cpt)\b.{0,90}\b(?:not\s+eligible|not\s+accepted|not\s+supported|not\s+considered|ineligible|not\s+permitted)\b",
    r"\b(?:no|not\s+accepting)\s+(?:f\s*-?\s*1|opt|cpt)\b",
]

POSITIVE = [
    r"\b(?:cpt|pre[ -]?opt|opt)\b.{0,55}\b(?:welcome|accepted|eligible|invited|encouraged|may\s+apply)\b"
]

OPTIONAL = [
    r"\bpreferred\b",
    r"\bdesired\b",
    r"\bnice\s+to\s+have\b",
    r"\ba\s+plus\b",
]


# -----------------------------
# Helper functions
# -----------------------------
def matches(patterns, text):
    return any(
        re.search(pattern, str(text or ""), re.IGNORECASE)
        for pattern in patterns
    )


def clean_text(value):
    text = unescape(str(value or ""))

    text = re.sub(
        r"<\s*(?:br|/p|/li|/div|/h[1-6]|/ul)\b[^>]*>",
        "\n",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text).replace("\xa0", " ")

    return "\n".join(
        " ".join(line.split())
        for line in text.splitlines()
        if line.strip()
    )


# -----------------------------
# Employer verification
# -----------------------------
def employer_slug(job):
    parsed = urlparse(str(job.get("absolute_url") or ""))
    parts = parsed.path.strip("/").split("/")

    if (
        parsed.scheme == "https"
        and parsed.hostname in (
            "boards.greenhouse.io",
            "job-boards.greenhouse.io"
        )
        and len(parts) == 3
        and parts[1] == "jobs"
    ):
        return parts[0].lower()

    return "UNKNOWN"


def check_employer(job):
    company = employer_slug(job)

    if company == "UNKNOWN":
        return "UNVERIFIED"

    if not job.get("company_name"):
        return "UNVERIFIED"

    return "MATCH"


# -----------------------------
# Read Greenhouse locations
# -----------------------------
def get_locations(job):
    locations = []

    location = job.get("location") or {}

    if isinstance(location, dict):
        locations.append(location.get("name") or "")

    elif isinstance(location, str):
        locations.append(location)

    for item in job.get("metadata") or []:
        if not isinstance(item, dict):
            continue

        name = str(item.get("name") or "").lower()

        if "location" not in name and "work country" not in name:
            continue

        value = item.get("value")

        if isinstance(value, list):
            locations.extend(str(v) for v in value if v)

        elif value:
            locations.append(str(value))

    return locations


# -----------------------------
# US location evidence
# -----------------------------
def is_us_location(text):
    text = str(text or "").strip()

    if not text:
        return False

    for place in re.split(r";|\n", text):
        place = place.strip()

        if not place:
            continue

        # Explicit United States evidence
        if matches([
            r"\b(?:United States|USA|U\.S\.|US)\b",
            r"\bWashington\s*,?\s*D\.?C\.?\b"
        ], place):
            return True

        # Georgia is also a country, so don't accept
        # Georgia alone as proof of a US location.
        states = US_STATES.replace("Georgia|", "")

        if matches([rf"\b(?:{states})\b"], place):
            return True

        # Example: Dallas, TX
        if matches([rf",\s*(?:{US_CODES})\b"], place):
            return True

        # Example: WI-Sun Prairie
        if re.match(
            rf"^\s*(?:{US_CODES})\s*[-–]\s*[A-Za-z]+",
            place,
            re.IGNORECASE
        ):
            if not re.match(
                r"^In-Office\b",
                place,
                re.IGNORECASE
            ):
                return True

        # City-only evidence
        normalized = place.casefold().strip(" ,.")

        if normalized in US_CITIES:
            return True

        # Several US city choices
        cities = [
            city.strip().casefold()
            for city in place.split(",")
        ]

        if (
            len(cities) > 1
            and all(city in US_CITIES for city in cities)
        ):
            return True

        # TV station prefixes with a city
        city_part = re.sub(
            r"^(?:(?:[WK][A-Z]{2,4})(?:-[A-Z]{2,4})?\s*)+(?:-TV)?\s+",
            "",
            place,
            flags=re.IGNORECASE
        )

        city_part = re.sub(
            r"^(?:[WK][A-Z]{2,4}(?:-[A-Z]{2,4})?[- ]?)+TV\s+",
            "",
            city_part,
            flags=re.IGNORECASE
        )

        if city_part.casefold().strip(" ,.") in US_CITIES:
            return True

        match = re.search(
            r"\b[WK][A-Z]{2,4}-TV\s+(.+)$",
            place,
            re.IGNORECASE
        )

        if match:
            city = match.group(1).casefold().strip(" ,.")

            if city in US_CITIES:
                return True

    return False


# -----------------------------
# Location verification
# -----------------------------
def check_location(job):
    locations = get_locations(job)

    if any(is_us_location(location) for location in locations):
        return "US"

    # Greenhouse policy:
    # Only verified US jobs enter transformation.
    return "NOT_VERIFIED"


# -----------------------------
# Application URL verification
# -----------------------------
def check_application(job):
    url = job.get("absolute_url")

    if not isinstance(url, str) or not url.startswith(
        ("https://", "http://")
    ):
        return "INVALID"

    if employer_slug(job) == "UNKNOWN":
        return "UNVERIFIED"

    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")

    if not job.get("id") or str(job["id"]) != parts[2]:
        return "UNVERIFIED"

    return "VALID"


# -----------------------------
# Description inspection
# -----------------------------
def check_description(job):
    reasons = set()
    positive = False
    preferred = False

    for line in clean_text(job.get("content")).splitlines():

        if matches(POSITIVE, line):
            positive = True

        if matches([
            r"^(?:nice to have|preferred|bonus)(?: qualifications?| skills?)?:?$"
        ], line):
            preferred = True
            continue

        if matches([
            r"^(?:required|minimum|basic)(?: qualifications?| skills?)?:?$",
            r"^requirements?:?$"
        ], line):
            preferred = False
            continue

        optional = preferred or matches(OPTIONAL, line)

        eeo = matches([
            r"\bwithout\s+regard\s+to\b",
            r"\bregardless\s+of\b"
        ], line)

        if not optional and not eeo:
            if matches(CITIZEN, line):
                reasons.add("US citizenship required")

            if matches(US_PERSON, line):
                reasons.add("US-person status required")

            if matches(GREEN_CARD, line):
                reasons.add(
                    "Permanent residency or citizenship required"
                )

            if matches(CLEARANCE, line):
                can_obtain = matches(CAN_OBTAIN, line)
                required_now = matches(REQUIRED_NOW, line)

                if required_now or not can_obtain:
                    reasons.add(
                        "Existing security clearance required"
                    )

        if matches(F1, line):
            reasons.add("Explicit OPT/CPT/F-1 restriction")

        # "Contract Award: No" is not a restriction.
        if matches([
            r"\b(?:position|job|role)\s+contingent\s+upon\s+contract\s+award\s*:\s*yes\b",
            r"\bcontingent\s+(?:on|upon)\s+(?:a\s+)?contract\s+award\b(?!\s*:\s*no\b)",
            r"\bsubject\s+to\s+(?:a\s+)?contract\s+award\b(?!\s*:\s*no\b)"
        ], line):
            reasons.add("Contract award contingent")

    return reasons, positive


# -----------------------------
# Check real job opening
# -----------------------------
def check_posting(job):
    title = str(job.get("title") or "")
    content = clean_text(job.get("content"))

    if matches([
        r"\btalent\s+(?:pool|pipeline|network|community)\b",
        r"\bgeneral\s+application\b",
        r"\bfuture\s+opportunities\b",
        r"\bconfidential\s+requisition\b"
    ], title):
        return "Not a specific job opening"

    if matches([
        r"\bnot\s+an\s+actual\s+(?:open\s+)?position\b",
        r"\bnot\s+an\s+actual\s+job\s+opening\b",
        r"\bnot\s+(?:a\s+)?current\s+job\s+opening\b",
        r"\bfor\s+administrative\s+purposes\s+only\b",
        r"\bopen\s+only\s+to\s+current\s+employees\b"
    ], content):
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

    if not job.get("company_name"):
        review_reasons.add("Missing employer name")

    if not job.get("title") or not clean_text(job.get("content")):
        review_reasons.add("Missing title or description")

    # Employer
    if check_employer(job) == "UNVERIFIED":
        review_reasons.add("Employer source unverified")

    # US location
    location = check_location(job)

    if location == "NOT_VERIFIED":
        reject_reasons.add("US location not verified")

    # Application
    application = check_application(job)

    if application == "INVALID":
        reject_reasons.add("Missing application URL")

    elif application == "UNVERIFIED":
        review_reasons.add("Application URL unverified")

    # Real job opening
    posting_issue = check_posting(job)

    if posting_issue:
        reject_reasons.add(posting_issue)

    # Work authorization and clearance
    description_reasons, positive = check_description(job)
    reject_reasons.update(description_reasons)

    # Same priority as other inspectors
    if reject_reasons:
        decision = "REJECT"

    elif review_reasons:
        decision = "REVIEW"

    else:
        decision = "KEEP"

    return decision, reject_reasons | review_reasons, positive


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

        if not isinstance(data, dict) or not isinstance(
            data.get("jobs"), list
        ):
            errors.append(
                f"{path.name}: Unexpected JSON structure"
            )
            continue

        files_read += 1

        for index, job in enumerate(data["jobs"]):
            if not isinstance(job, dict):
                continue

            company = employer_slug(job)

            if job.get("id"):
                key = (company, str(job["id"]))

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
    board_names = defaultdict(set)

    accepted_jobs = []
    review_jobs = []
    positive_count = 0

    for job in jobs:
        company = employer_slug(job)

        decision, reasons, positive = inspect_job(job)

        totals[decision] += 1
        employers[company][decision] += 1
        positive_count += int(positive)

        if job.get("company_name"):
            board_names[company].add(
                str(job["company_name"]).strip().casefold()
            )

        if decision == "KEEP":
            accepted_jobs.append(job)

        elif decision == "REVIEW":
            review_reasons.update(reasons)

            review_jobs.append({
                "company": company,
                "employer": job.get("company_name"),
                "title": job.get("title"),
                "job_id": job.get("id"),
                "location": get_locations(job),
                "reasons": sorted(reasons)
            })

        else:
            rejection_reasons.update(reasons)

    print("\nGREENHOUSE EXTRACTION DATA")
    print("=" * 60)

    for company, counts in sorted(employers.items()):
        print(f"{company}: {sum(counts.values())} jobs")

    print("\nGREENHOUSE INSPECTION RESULTS")
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
            f"{company:<20}"
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

    mismatched_boards = sum(
        len(names) > 1
        for names in board_names.values()
    )

    print(
        f"Boards with different company names: "
        f"{mismatched_boards}"
    )

    print(f"Positive OPT/CPT mentions: {positive_count}")
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
            print(f"   Actual employer: {job['employer']}")
            print(f"   Title: {job['title']}")
            print(f"   Job ID: {job['job_id']}")
            print(f"   Location: {job['location']}")
            print(f"   Reasons: {', '.join(job['reasons'])}")

    print("\nINSPECTION COMPLETED")
    print("=" * 60)

    return accepted_jobs, review_jobs


if __name__ == "__main__":
    inspect()
