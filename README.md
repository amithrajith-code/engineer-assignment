# HRIS Import Preview

## Project overview

A small Django application for previewing an HRIS CSV before employee or reporting data is written anywhere. It parses an upload in memory, validates employee identities and manager references, and displays hierarchy issues and reporting cycles.

## What it shows

- Total source rows and accepted employees
- Row-level validation errors with source row numbers
- Root employees
- Managers with direct-report counts
- Employees that are members of reporting cycles

The application does not persist employee data.

## Setup and installation

Prerequisite: Python 3.12 (the version used to develop and test this project).

```powershell
cd C:\Users\hp\Documents\Assignment\engineer-assignment
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## How to run the Django application

```powershell
python manage.py runserver
```

Open `http://127.0.0.1:8000/` in a browser and upload `sample_data/sample_hris.csv`.

## How to run tests

```powershell
python manage.py test -v 2
```

The test suite covers CSV parsing and normalization, identity validation, manager resolution, roots, direct-report counts, cycle detection, the combined analysis service, and the upload view.

## Assumptions

- CSV headers use the required names, although their order may vary.
- Values are trimmed; only `email` and `manager_email` are lowercased.
- Employee IDs remain case-sensitive.
- Additional CSV columns are ignored after required headers have been validated.
- Completely blank CSV lines are ignored.
- A root employee has both manager fields blank. An unresolved manager reference is an error, not a root.

## Known limitations

- Upload analysis is in memory; there is no streaming parser or upload-size limit.
- The application accepts CSV files only, not Excel workbooks.
- There is no authentication, database persistence, production deployment configuration, or JavaScript frontend framework.
- The interface is intentionally plain and focused on import-preview output.

## Approximate implementation/testing time

Approximately 90 minutes, excluding video recording. This reflects the exercise implementation timebox; update it if the actual time differs.

## AI tools used

OpenAI Codex was used for design discussion, implementation assistance, test creation, and review. The application behavior was reviewed and tested locally, including the supplied sample CSV.
