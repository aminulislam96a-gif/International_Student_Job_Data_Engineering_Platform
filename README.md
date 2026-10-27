
# International Student Job Data Engineering Platform

## About the Project

I am building a data engineering pipeline that collects job postings from different sources and prepares the data for international students looking for jobs in the United States.

The pipeline collects job postings, inspects the data, removes confirmed duplicates, and checks whether jobs are still available.

## Data Sources

- Headcount
- Greenhouse
- Lever
- Ashby

## Pipeline

1. **Extraction:** Collect job postings from APIs and save original responses as JSON.
2. **Inspection:** Check job information related to international student work authorization.
3. **Deduplication:** Identify matching jobs and separate possible duplicates for review.
4. **Availability:** Check whether job postings are still available.
5. **Schema Inspection:** Examine fields, data types, missing values, and nested data before transformation.

## Current Progress

Extraction, inspection, deduplication, and availability checking are implemented.

The latest availability check processed 5,043 jobs:

- Active: 4,901
- No longer publicly listed or not current: 142
- Unknown: 0

These numbers reflect one run and will change as job postings change.

## Technologies

Python, REST APIs, JSON, Git, and GitHub.

## Next Steps

- Complete schema inspection.
- Transform the job data into a common structure.
- Load the transformed data into PostgreSQL.

## Note

An active job does not automatically mean it accepts OPT, CPT, STEM OPT, or visa sponsorship.
