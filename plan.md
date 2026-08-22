# Diversio HRIS Import Preview — Working Plan

## Purpose and working agreement

Build a small, reliable Django web application that lets a Client Success user upload an HRIS CSV and inspect the result **before** any data is stored.

This document is the single source of truth for implementation decisions, scope, validation rules, and delivery checks. Update it if a later requirement changes a decision.


### Scope boundary

The application is an in-memory import preview, not an HR system. No database persistence, authentication, API, JavaScript framework, Docker, or production deployment is required.

## Technology choices

| Concern | Choice | Reason |
| --- | --- | --- |
| Language | Python 3.12 | Installed locally; required by the exercise. |
| Web framework | Django 5.1 | Installed locally and preferred by Diversio. |
| CSV handling | Python standard-library `csv` module | Correctly handles columns in any order and quoted commas. |
| UI | Django templates, HTML, minimal CSS | Clear and sufficient for the exercise. |
| Tests | Django `TestCase` / `manage.py test` | Already available; no external test package needed. |
| Persistence | None | The exercise explicitly does not require it. |

## Planned project structure

```text
engineer-assignment/
├── manage.py
├── requirements.txt
├── README.md
├── .gitignore
├── plan.md
├── config/
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
└── preview/
    ├── apps.py
    ├── urls.py
    ├── views.py
    ├── services.py
    ├── tests.py
    ├── test_views.py
    └── templates/
        └── preview/
            └── upload.html
```

### Responsibilities

- `preview/views.py`: receives the browser upload, calls the service, and renders a result or a friendly upload error. It contains no validation or graph logic.
- `preview/services.py`: CSV parsing, normalization, identity validation, manager resolution, roots, direct-report counts, cycle detection, and result assembly. It must be usable directly from tests without a browser.
- `preview/tests.py`: focused tests for the rules in `services.py`, plus a small upload view test if useful.
- `upload.html`: presents the form and analysis results only.

## Required output

After upload, show:

1. Total source rows.
2. Employees accepted for analysis.
3. Row-level validation errors, including source row numbers.
4. Root employees (employees with no manager fields supplied).
5. Managers and their direct-report counts.
6. Employees who are members of a reporting cycle.

## Processing pipeline

```text
Browser upload
  -> parse CSV
  -> normalize all values
  -> validate employee identity
  -> build ID/email lookup maps from valid identities only
  -> resolve managers
  -> build valid reporting relationships
  -> calculate roots and direct-report counts
  -> detect cycle members
  -> render import preview
```

All processing occurs in memory during the upload request.

## CSV and normalization rules

Required headers, in any order:

```text
employee_id, employee_name, email, manager_id, manager_email, department
```

- Use normal CSV parsing (`csv.DictReader`), never manual string splitting.
- Support UTF-8 with or without a byte-order mark by decoding as `utf-8-sig`.
- Trim surrounding whitespace from every cell.
- Lowercase only `email` and `manager_email` after trimming.
- Keep `employee_id` and `manager_id` case-sensitive. Never call `.lower()` on an ID before duplicate detection or dictionary lookup.
- Preserve the supplied capitalization of all other fields, including employee names and departments; email normalization does not mean lowercasing every CSV value.
- Reject malformed CSV, invalid UTF-8, empty files, and missing required headers with a clear user-facing message rather than a traceback.

## Identity validation rules

`employee_id` and `email` are both required and unique after normalization.

- A missing ID or email makes the row identity-invalid.
- Every row sharing a duplicate normalized ID or normalized email is identity-invalid.
- Identity-invalid rows appear in validation errors only. They must not participate in lookup maps, manager resolution, roots, direct-report counts, or cycle analysis.

### Meaning of “accepted employee”

An employee is accepted for analysis when identity validation succeeds. A manager-reference error does **not** remove that employee from the accepted count.

| Identity | Manager relationship | Result |
| --- | --- | --- |
| Invalid | Any | Not accepted; errors only. |
| Valid | Valid | Accepted; valid hierarchy relationship or root. |
| Valid | Invalid | Accepted; error; no relationship; not a root. |

## Manager resolution rules

Resolve manager references only after all valid-identity employees have been indexed by both ID and normalized email. This supports managers occurring before or after their reports.

### Lookup-map key rule (critical)

| Map | Key | Reason |
| --- | --- | --- |
| `employee_by_id` | Trimmed, original `employee_id` | IDs are case-sensitive: `DIV-1001` and `div-1001` must remain distinct. |
| `employee_by_email` | Trimmed, lowercased `email` | Emails are case-insensitive: casing variants must resolve to the same identity. |

Apply the same rules when resolving `manager_id` and `manager_email`. Lowercasing an ID would create an invalid collision; not lowercasing an email would miss a valid match or duplicate.

| `manager_id` | `manager_email` | Expected result |
| --- | --- | --- |
| Blank | Blank | Employee is a root. |
| Present | Blank | Look up manager by case-sensitive ID. |
| Blank | Present | Look up manager by normalized email. |
| Present | Present | Both lookups must resolve to the same employee. |

Produce a useful row-level error if:

- a referenced manager cannot be found;
- both manager references resolve to different employees; or
- an employee references themselves as manager.

An employee with a manager error may still be the valid manager of other employees. Only their own invalid manager relationship is excluded.

## Hierarchy and cycle rules

- A root has *both* manager fields blank; a root may also be a manager.
- A manager is an employee with one or more valid direct reports.
- Only direct relationships count; indirect reports do not increase a manager’s count.
- Model each valid relationship as `employee -> manager`. Each employee has at most one outgoing edge.
- Detect actual cycle members with an iterative path/state traversal, not recursive DFS. This avoids recursion-depth failure around 100,000 employees.
- If `A -> B -> C -> A` and `D -> A`, only `A`, `B`, and `C` are cyclic. `D` is not cyclic.

## Complexity target

For `n` rows:

- Parsing, identity validation, indexing, manager resolution, report counting, and cycle analysis are each linear or amortized linear.
- Dictionary lookups are O(1) average.
- Because each employee has at most one manager relationship, `E <= V`.
- Overall time: O(n). Space: O(n).

## Focused test plan

Minimum required: two automated tests. Planned high-value coverage:

1. Manager appears after their report: manager lookup succeeds regardless of CSV order.
2. Cycle members only: `A -> B -> C -> A` marks A/B/C, while `D -> A` is not cyclic.
3. Duplicate normalized ID/email: every involved row is invalid and excluded from lookups.
4. Manager conflict: supplied ID and email resolving to different employees produces an error but leaves the employee accepted.
5. Malformed upload/header error: service returns a clear controlled error.

## Supplied sample expectations

The supplied sample should produce approximately:

- Source rows: 25
- Accepted employees: 25
- Manager errors: Casey Bell (unknown `DIV-9999`) and Riley Cooper (conflicting manager ID/email)
- Root employee: Avery Morgan
- Cycle members: Alex Romero, Taylor Brooks, and Morgan Ellis

The implementation will verify these results once the sample CSV is available locally in a proper UTF-8 CSV file.

## Implementation sequence

1. Create the Django skeleton and settings. **Completed:** a minimal project configuration, URL route, upload view, template, dependency file, and Git ignore rules now exist. The application has no models or import persistence.
2. Implement and test CSV parsing and normalization. **Completed:** framework-independent `preview/services.py` parses UTF-8/BOM CSV uploads, validates headers/shape, normalizes values, and preserves source row numbers; `preview/tests.py` covers reordered headers, normalization, BOM/quoted values, and controlled errors.
3. Implement and test identity validation plus lookup maps. **Completed (validation only):** `validate_employee_identities` rejects missing IDs/emails and every row in a duplicate ID or normalized-email group, while retaining source row numbers in errors. It returns an explicit valid-identity pool for the later lookup-map stage; manager lookup is not yet implemented.
4. Implement manager resolution, roots, and direct-report counts. **Completed:** `resolve_managers` uses lookup maps built only from valid identities, returns roots and valid `employee_id -> manager_id` relationships, and retains manager-error employees as accepted without a relationship. `analyze_hierarchy` derives direct-report counts exclusively from those valid relationships.
5. Implement iterative cycle detection. **Completed:** `detect_reporting_cycles` uses an iterative DFS-style traversal of valid `employee_id -> manager_id` relationships. It marks only the repeated-path suffix as cyclic, so employees reporting into a cycle are excluded.
6. Assemble a single analysis result object. **Completed:** `analyze_hris_csv` orchestrates parsing, identity validation, manager resolution, hierarchy analysis, and cycle detection, returning a view-ready `ImportAnalysisResult` without database persistence.
7. Add upload form and clear result sections. **Completed:** the thin Django view validates file presence, invokes `analyze_hris_csv`, displays controlled CSV errors, and renders all required import-preview sections in plain HTML.
8. Add/complete focused tests and test the supplied sample.
9. Write README: setup, run, tests, assumptions/limitations, complexity, approximate coding time, and AI usage. **Draft completed:** `README.md` documents the implementation and includes a clearly marked placeholder for the developer's real implementation/testing time before submission.
10. Prepare the narrated walkthrough and final manual Git/submission checklist.

