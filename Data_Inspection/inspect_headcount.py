
import json
import re
from pathlib import Path
from collections import Counter, defaultdict


# -----------------------------
# File paths
# -----------------------------
ROOT = Path(__file__).resolve().parents[1]
RAW_FOLDER = ROOT / "data" / "raw" / "headcount"


# -----------------------------
# Restriction patterns
# -----------------------------
US = r"(?:u\.?\s*s\.?|united states|american)"
CITIZEN = rf"{US}\s+citizen(?:ship)?"

CITIZEN_PATTERNS = [
    rf"\b(?:must|need|require[ds]?)\s+(?:to\s+)?be\s+(?:(?:a|an|current)\s+)*{CITIZEN}\b",
    rf"\b{US}\s+citizenship\s+(?:is\s+)?(?:required|mandatory)\b",
    rf"\b(?:requires?|requiring)\b.{{0,50}}\b{US}\s+citizenship\b",
    rf"\b{US}\s+citizens?\s+only\b",
    rf"\bonly\s+{US}\s+citizens\b",
    rf"\b{CITIZEN}\s+(?:with|and)\s+(?:an?\s+)?(?:ability|eligibility|active)\b",
    rf"\b(?:applicants|candidates)\s+must\s+be\s+{US}\s+citizens\b",
    rf"^\s*(?:[-+•]\s*)?(?:current\s+)?{CITIZEN}\s*(?:$|[;,.])",
]

US_PERSON = [
    r"\bmust\s+be\s+(?:a\s+)?u\.?s\.?\s+person\b",
    r"\bu\.?s\.?\s+persons?\s+only\b",
    r"\bu\.?s\.?\s+person\s+status\s+(?:is\s+)?required\b",
    r"\b(?:requires?|required|mandatory)\b.{0,45}\bu\.?s\.?\s+person\b",
]

GREEN_CARD = [
    r"\b(?:must|required|requires?|need)\b.{0,90}\b(?:green\s*card|permanent\s+residen(?:t|cy))\b",
    r"\b(?:green\s*card|permanent\s+residen(?:t|cy))\b.{0,60}\b(?:required|mandatory|only)\b",
    r"\b(?:green\s*card|permanent\s+residen(?:t|cy))\s+or\s+u\.?\s*s\.?\s+citizenship\b",
    r"\b(?:citizens?|permanent\s+residents?|green\s*card\s+holders?)\s+only\b",
]

CLEARANCE = r"(?:ts\s*/\s*sci|top\s+secret|secret|sci)"

CLEARANCE_PATTERNS = [
    rf"\b(?:active|current|existing)\b.{{0,65}}\b{CLEARANCE}\b.{{0,35}}\bclearance\b",
    rf"\b(?:active|current|existing)\b.{{0,50}}\bclearance\b.{{0,35}}\b{CLEARANCE}\b",
    rf"\b(?:required|mandatory|must\s+(?:have|hold|possess))\b.{{0,90}}\b{CLEARANCE}\b.{{0,45}}\bclearance\b",
    rf"\b{CLEARANCE}\b.{{0,40}}\bclearance\b.{{0,35}}\b(?:required|mandatory)\b",
    rf"\brequired\s+(?:security\s+)?clearance\s*:\s*{CLEARANCE}\b",
    rf"\bclearance\s*(?:required|level|type)\s*:\s*{CLEARANCE}\b",
    rf"\bactive\s+{CLEARANCE}\b",
    rf"\b{CLEARANCE}\s+(?:with\s+)?(?:poly|polygraph)\b",
    r"\bmust\s+(?:have|hold|possess)\b.{0,80}\bsecurity\s+clearance\b",
]

ELIGIBLE_TO_OBTAIN = [
    r"\b(?:ability|eligible|eligibility|able|willing)\s+to\s+obtain\b",
    r"\bcan\s+obtain\b",
    r"\bcapable\s+of\s+obtaining\b",
]

CLEARANCE_AT_HIRE = [
    r"\bmust\s+(?:currently|already)\s+(?:have|hold|possess)\b",
    r"\bcurrently\s+(?:hold|possess)\b",
    r"\b(?:active|current|existing)\b.{0,65}\bclearance\s+(?:is\s+)?required\b",
    r"\bclearance\b.{0,50}\b(?:at\s+time\s+of\s+hire|prior\s+to\s+start)\b",
]

F1_PATTERNS = [
    r"\b(?:will\s+not|do\s+not|does\s+not|cannot|can't)\s+(?:accept|hire|consider|employ)\b.{0,120}\b(?:f\s*-?\s*1|opt|cpt)\b",
    r"\b(?:f\s*-?\s*1|opt|cpt|stem\s+opt)\s+(?:students?|candidates?|applicants?)\s+(?:are\s+)?not\s+(?:eligible|accepted|considered)\b",
    r"\b(?:will\s+not|does\s+not|cannot|not\s+able\s+to)\b.{0,180}\b(?:sponsor|immigration[- ]related\s+support)\b.{0,250}\bf\s*-?\s*1\s*(?:stem\s*)?(?:opt|cpt)\b",
    r"\b(?:must\s+not|cannot)\b.{0,100}\bwork\s+authorization\s+based\s+on\s+(?:opt|cpt)\b",
    r"\b(?:opt|cpt)\b.{0,90}\b(?:not\s+permitted|not\s+accepted|not\s+eligible)\b",
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
def get_value(item):
    if isinstance(item, dict) and "state" in item:
        return item.get("value")

    return item


def clean_text(text):
    if not isinstance(text, str):
        return ""

    text = text.replace("\u00a0", " ")
    text = re.sub(r"[*_`#]", "", text)

    return "\n".join(
        " ".join(line.split())
        for line in text.splitlines()
    )


def matches(patterns, text):
    return any(
        re.search(pattern, text, re.IGNORECASE)
        for pattern in patterns
    )


# -----------------------------
# Employer identity
# -----------------------------
def clean_company(name):
    name = str(name or "").casefold()
    name = name.replace("_united states", "")
    name = re.sub(r"[^a-z0-9]+", " ", name)

    name = re.sub(
        r"\b(?:incorporated|inc|corporation|corp|llc|ltd)\b",
        "",
        name
    )

    return " ".join(name.split())


# Known employer relationships from our current inspection.
# New employers do not need to be added here if their names match.
# Unfamiliar relationships automatically go to REVIEW.

VERIFIED_RELATED = {
    "leidos": {
        "leidos qtc health services",
    },
    "mars": {
        "mars veterinary health",
        "mars wrigley conf mcna",
        "mars food us",
    },
}

VERIFIED_UNRELATED = {
    "hilton": {
        "hilton grand vacations",
        "bayshore on hilton head",
    },
    "mars": {
        "mars energy solutions",
        "glicksman mars dental",
    },
}


def check_employer(company, employer):
    if not employer:
        return "UNVERIFIED"

    expected = clean_company(company)
    actual = clean_company(employer)

    if expected and expected == actual:
        return "MATCH"

    if actual in VERIFIED_RELATED.get(expected, set()):
        return "MATCH"

    if actual in VERIFIED_UNRELATED.get(expected, set()):
        return "UNRELATED"

    return "UNVERIFIED"


# -----------------------------
# Job description inspection
# -----------------------------
def check_description(description):
    reasons = set()
    section = ""

    for line in clean_text(description).splitlines():
        if not line:
            continue

        if matches([
            r"^(?:preferred|desired|additional)\s+qualifications?\s*:?\s*$",
            r"^(?:nice\s+to\s+have|preferred\s+skills)\s*:?\s*$"
        ], line):
            section = "preferred"
            continue

        if matches([
            r"^(?:required|minimum|basic)\s+qualifications?\s*:?\s*$",
            r"^requirements?\s*:?\s*$"
        ], line):
            section = "required"
            continue

        eeo = matches([
            r"\bwithout\s+regard\s+to\b",
            r"\bregardless\s+of\b",
            r"\bequal\s+opportunity\s+employer\b"
        ], line)

        optional = (
            section == "preferred"
            or matches(OPTIONAL, line)
        )

        if not eeo and not optional:
            if matches(CITIZEN_PATTERNS, line):
                reasons.add("US citizenship required")

            if matches(US_PERSON, line):
                reasons.add("US-person status required")

            if matches(GREEN_CARD, line):
                reasons.add(
                    "Permanent residency or citizenship required"
                )

            if matches(CLEARANCE_PATTERNS, line):
                can_obtain = matches(ELIGIBLE_TO_OBTAIN, line)
                required_now = matches(CLEARANCE_AT_HIRE, line)

                if not can_obtain or required_now:
                    reasons.add(
                        "Existing security clearance required"
                    )

        if matches(F1_PATTERNS, line):
            reasons.add("Explicit OPT/CPT/F-1 restriction")

        if matches([
            r"\b(?:contingent\s+(?:on|upon)|subject\s+to)\s+(?:a\s+)?contract\s+award\b(?!\s*:\s*no\b)"
        ], line):
            reasons.add("Contract award contingent")

    return reasons


# -----------------------------
# Check actual job opening
# -----------------------------
def check_posting(title, description):
    if matches([
        r"\bconfidential\s+requisition\b",
        r"\bgeneral\s+application\b",
        r"\btalent\s+(?:network|pool|community)\b"
    ], str(title)):
        return "Not a specific job opening"

    if matches([
        r"\bnot\s+an\s+actual\s+job\s+opening\b",
        r"\bfor\s+administrative\s+purposes\s+only\b",
        r"\binternal\s+(?:applicants|candidates)\s+only\b",
        r"\bopen\s+only\s+to\s+current\s+employees\b"
    ], clean_text(description)):
        return "Internal or administrative posting"

    return None


# -----------------------------
# Check application URL
# -----------------------------
def check_application(job):
    for posting in job.get("postings") or []:
        if not isinstance(posting, dict):
            continue

        if posting.get("posting_status") != "listed":
            continue

        url = (
            get_value(posting.get("application_url"))
            or get_value(posting.get("posting_url"))
        )

        if isinstance(url, str) and url.startswith(
            ("https://", "http://")
        ):
            return True

    return False


# -----------------------------
# Check US location
# -----------------------------
def check_location(job):
    has_location = False
    has_unknown = False

    for item in job.get("locations") or []:
        location = get_value(item)

        if not isinstance(location, dict):
            has_unknown = True
            continue

        country = str(
            get_value(location.get("country")) or ""
        ).strip().upper()

        if not country:
            has_unknown = True
            continue

        has_location = True

        if country in (
            "US",
            "USA",
            "UNITED STATES",
            "UNITED STATES OF AMERICA"
        ):
            return "US"

    if has_unknown or not has_location:
        return "UNKNOWN"

    return "OUTSIDE_US"


# -----------------------------
# Inspect one job
# -----------------------------
def inspect_job(job, company):
    reject_reasons = set()
    review_reasons = set()

    job_id = get_value(job.get("job_id"))
    title = get_value(job.get("title"))
    employer = get_value(job.get("employer_name"))
    description = get_value(job.get("description"))

    if not job_id:
        review_reasons.add("Missing job ID")

    if not title or not employer or not description:
        review_reasons.add("Missing required information")

    # Location
    location = check_location(job)

    if location == "OUTSIDE_US":
        reject_reasons.add("Outside US")

    elif location == "UNKNOWN":
        review_reasons.add("US location unverified")

    # Application
    if not check_application(job):
        reject_reasons.add("No listed application URL")

    # Current posting
    if (
        get_value(job.get("stale")) is True
        or get_value(job.get("currentness")) not in (None, "current")
    ):
        reject_reasons.add("Stale or non-current job")

    # Employer identity
    identity = check_employer(company, employer)

    if identity == "UNRELATED":
        reject_reasons.add("Unrelated employer")

    elif identity == "UNVERIFIED":
        review_reasons.add("Employer identity unverified")

    # Real job opening
    posting_issue = check_posting(title, description)

    if posting_issue:
        reject_reasons.add(posting_issue)

    # Work authorization and other restrictions
    reject_reasons.update(check_description(description))

    # Decision priority: REJECT > REVIEW > KEEP
    if reject_reasons:
        decision = "REJECT"

    elif review_reasons:
        decision = "REVIEW"

    else:
        decision = "KEEP"

    reasons = reject_reasons | review_reasons

    return decision, reasons


# -----------------------------
# Load latest snapshots
# -----------------------------
def load_snapshots():
    snapshots = {}
    errors = []

    for path in sorted(RAW_FOLDER.glob("*/*.json")):
        try:
            with open(path, "r", encoding="utf-8") as file:
                data = json.load(file)

            if not isinstance(data, dict):
                errors.append(
                    f"{path.name}: Invalid JSON structure"
                )
                continue

            company = data.get("company_query")
            pages = data.get("pages")

            if not company or not isinstance(pages, list):
                errors.append(
                    f"{path.name}: Missing company or pages"
                )
                continue

            previous = snapshots.get(company)

            if (
                previous is None
                or str(data.get("extracted_at") or "")
                > str(previous.get("extracted_at") or "")
            ):
                snapshots[company] = data

        except (OSError, ValueError) as error:
            errors.append(f"{path.name}: {error}")

    return snapshots, errors


# -----------------------------
# Main inspection
# -----------------------------
def inspect():
    snapshots, errors = load_snapshots()

    totals = Counter()
    employers = defaultdict(Counter)

    rejection_reasons = Counter()
    review_reasons = Counter()

    snapshot_counts = {}

    seen_ids = set()

    accepted_jobs = []
    review_jobs = []

    for company, snapshot in sorted(snapshots.items()):
        jobs = []

        for page in snapshot["pages"]:
            if not isinstance(page, dict):
                continue

            for job in page.get("data") or []:
                if isinstance(job, dict):
                    jobs.append(job)

        snapshot_counts[company] = {
            "jobs": len(jobs),
            "complete": snapshot.get("complete")
        }

        totals["employers"] += 1
        totals["jobs"] += len(jobs)

        if snapshot.get("complete") is True:
            totals["complete_snapshots"] += 1
        else:
            totals["partial_snapshots"] += 1

        for job in jobs:
            decision, reasons = inspect_job(job, company)

            job_id = get_value(job.get("job_id"))

            # Duplicate check
            if job_id:
                key = str(job_id)

                if key in seen_ids:
                    decision = "REJECT"
                    reasons.add("Duplicate job ID")

                else:
                    seen_ids.add(key)

            totals[decision] += 1
            employers[company][decision] += 1

            if decision == "KEEP":
                accepted_jobs.append(job)

            elif decision == "REVIEW":
                review_reasons.update(reasons)

                review_jobs.append({
                    "company": company,
                    "employer": get_value(
                        job.get("employer_name")
                    ),
                    "title": get_value(job.get("title")),
                    "job_id": job_id,
                    "reasons": sorted(reasons)
                })

            else:
                rejection_reasons.update(reasons)

    # -----------------------------
    # Terminal results
    # -----------------------------
    print("\nHEADCOUNT EXTRACTION DATA")
    print("=" * 60)

    for company, details in sorted(snapshot_counts.items()):
        print(
            f"{company}: {details['jobs']} jobs; "
            f"complete={details['complete']}"
        )

    print("\nHEADCOUNT INSPECTION RESULTS")
    print("=" * 60)

    print(f"Employers inspected: {totals['employers']}")
    print(f"Jobs inspected: {totals['jobs']}")
    print(
        f"Complete snapshots: "
        f"{totals['complete_snapshots']}"
    )
    print(
        f"Partial snapshots: "
        f"{totals['partial_snapshots']}"
    )

    print("\nFINAL DECISIONS")
    print("-" * 60)

    print(
        f"KEEPING FOR TRANSFORMATION: {totals['KEEP']}"
    )
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
            f"{company:<22}"
            f"Total: {total:<7}"
            f"Keeping: {counts['KEEP']:<7}"
            f"Rejected: {counts['REJECT']:<7}"
            f"Review: {counts['REVIEW']}"
        )

    print("\nDATA VALIDATION")
    print("-" * 60)

    all_classified = (
        totals["KEEP"]
        + totals["REJECT"]
        + totals["REVIEW"]
        == totals["jobs"]
    )

    print(
        f"All jobs classified: "
        f"{'YES' if all_classified else 'NO'}"
    )

    print(f"Jobs needing review: {len(review_jobs)}")
    print(f"Files with errors: {len(errors)}")

    if errors:
        print("\nFILE ERRORS")
        print("-" * 60)

        for error in errors:
            print(error)

    # Only display jobs that genuinely need review
    if review_jobs:
        print("\nJOBS NEEDING REVIEW")
        print("-" * 60)

        for number, job in enumerate(review_jobs, start=1):
            print(
                f"{number}. Company searched: "
                f"{job['company']}"
            )
            print(
                f"   Actual employer: {job['employer']}"
            )
            print(f"   Job title: {job['title']}")
            print(f"   Job ID: {job['job_id']}")
            print(
                f"   Reasons: {', '.join(job['reasons'])}"
            )

    print("\nINSPECTION COMPLETED")
    print("=" * 60)

    # Only accepted_jobs should enter transformation.
    # review_jobs remain separate for future investigation.
    return accepted_jobs, review_jobs


if __name__ == "__main__":
    inspect()
