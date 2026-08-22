"""Pure analysis services for the HRIS import preview.

This module deliberately has no Django imports. A Django view can pass uploaded
file bytes to ``parse_hris_csv`` while unit tests can call it directly.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass


REQUIRED_HEADERS = frozenset(
    {
        "employee_id",
        "employee_name",
        "email",
        "manager_id",
        "manager_email",
        "department",
    }
)


class CsvParsingError(ValueError):
    """Raised when an uploaded file cannot be read as a valid HRIS CSV."""


@dataclass(slots=True)
class ParsedEmployeeRow:
    """One normalized CSV row, before identity or hierarchy validation."""

    source_row_number: int
    employee_id: str
    employee_name: str
    email: str
    manager_id: str
    manager_email: str
    department: str


@dataclass(slots=True)
class ValidationError:
    """A user-facing validation problem attached to one source row."""

    source_row_number: int
    message: str


@dataclass(slots=True)
class IdentityValidationResult:
    """The valid employee pool and row errors from identity validation."""

    valid_employees: list[ParsedEmployeeRow]
    errors: list[ValidationError]


@dataclass(slots=True)
class ManagerResolutionResult:
    """Accepted employees, roots, valid relationships, and manager errors."""

    accepted_employees: list[ParsedEmployeeRow]
    root_employees: list[ParsedEmployeeRow]
    employee_to_manager: dict[str, str]
    errors: list[ValidationError]


@dataclass(slots=True)
class HierarchyAnalysisResult:
    """Roots and direct-report counts derived from valid relationships only."""

    root_employees: list[ParsedEmployeeRow]
    direct_report_counts: dict[str, int]


@dataclass(slots=True)
class CycleAnalysisResult:
    """The identity-valid employees proven to be members of a reporting cycle."""

    cyclic_employee_ids: set[str]


@dataclass(slots=True)
class ManagerSummary:
    """A manager and the number of valid employees reporting directly to them."""

    manager: ParsedEmployeeRow
    direct_report_count: int


@dataclass(slots=True)
class ImportAnalysisResult:
    """The complete in-memory import preview returned to a Django view."""

    total_source_rows: int
    accepted_employees: list[ParsedEmployeeRow]
    validation_errors: list[ValidationError]
    root_employees: list[ParsedEmployeeRow]
    manager_summaries: list[ManagerSummary]
    cyclic_employees: list[ParsedEmployeeRow]


def parse_hris_csv(file_bytes: bytes) -> list[ParsedEmployeeRow]:
    """Parse and normalize an uploaded HRIS CSV file.

    The function only parses and normalizes. It intentionally does not decide
    whether an employee identity or manager relationship is valid.

    Args:
        file_bytes: Raw bytes from an uploaded CSV file.

    Returns:
        Normalized rows with their original one-based source line numbers.

    Raises:
        CsvParsingError: If the file is empty, not UTF-8, malformed, has
            duplicate headers, misses required headers, or has uneven columns.
    """

    text = _decode_utf8(file_bytes)
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)

    try:
        raw_headers = next(reader)
    except StopIteration as error:
        raise CsvParsingError("The uploaded file is empty.") from error
    except csv.Error as error:
        raise CsvParsingError(f"Malformed CSV near source row 1: {error}") from error

    headers = [header.strip() for header in raw_headers]
    _validate_headers(headers)
    header_positions = {header: index for index, header in enumerate(headers)}

    rows: list[ParsedEmployeeRow] = []
    while True:
        # Capture the physical line before reading so a multi-line quoted value
        # still retains the line on which its CSV record began.
        source_row_number = reader.line_num + 1
        try:
            raw_values = next(reader)
        except StopIteration:
            break
        except csv.Error as error:
            raise CsvParsingError(
                f"Malformed CSV near source row {source_row_number}: {error}"
            ) from error

        # Ignore completely blank lines; they are not employee source rows.
        if not raw_values or all(value.strip() == "" for value in raw_values):
            continue

        if len(raw_values) != len(headers):
            raise CsvParsingError(
                f"Source row {source_row_number} has {len(raw_values)} columns; "
                f"expected {len(headers)}."
            )

        values = {
            header: raw_values[position].strip()
            for header, position in header_positions.items()
        }

        rows.append(
            ParsedEmployeeRow(
                source_row_number=source_row_number,
                employee_id=values["employee_id"],
                employee_name=values["employee_name"],
                email=values["email"].lower(),
                manager_id=values["manager_id"],
                manager_email=values["manager_email"].lower(),
                department=values["department"],
            )
        )

    return rows


def validate_employee_identities(
    rows: list[ParsedEmployeeRow],
) -> IdentityValidationResult:
    """Validate required and unique employee identities.

    ``employee_id`` values are already trimmed but deliberately remain
    case-sensitive. ``email`` values are already trimmed and lowercased by the
    parsing layer. Any row with a missing identity value or an identity value
    shared by another row is excluded from ``valid_employees``.

    This function intentionally does not resolve managers or build a hierarchy.
    Later stages must use only ``valid_employees`` to create lookup maps.
    """

    employees_by_id: dict[str, list[ParsedEmployeeRow]] = {}
    employees_by_email: dict[str, list[ParsedEmployeeRow]] = {}

    for row in rows:
        if row.employee_id:
            employees_by_id.setdefault(row.employee_id, []).append(row)
        if row.email:
            employees_by_email.setdefault(row.email, []).append(row)

    duplicate_ids = {
        employee_id
        for employee_id, matching_rows in employees_by_id.items()
        if len(matching_rows) > 1
    }
    duplicate_emails = {
        email
        for email, matching_rows in employees_by_email.items()
        if len(matching_rows) > 1
    }

    valid_employees: list[ParsedEmployeeRow] = []
    errors: list[ValidationError] = []

    for row in rows:
        row_errors: list[str] = []

        if not row.employee_id:
            row_errors.append("employee_id is required.")
        elif row.employee_id in duplicate_ids:
            row_errors.append(f"Duplicate employee_id: {row.employee_id}.")

        if not row.email:
            row_errors.append("email is required.")
        elif row.email in duplicate_emails:
            row_errors.append(f"Duplicate email: {row.email}.")

        if row_errors:
            errors.extend(
                ValidationError(
                    source_row_number=row.source_row_number,
                    message=message,
                )
                for message in row_errors
            )
        else:
            valid_employees.append(row)

    return IdentityValidationResult(
        valid_employees=valid_employees,
        errors=errors,
    )


def resolve_managers(
    identity_result: IdentityValidationResult,
) -> ManagerResolutionResult:
    """Resolve manager references for identity-valid employees only.

    The input type makes the identity-validation boundary explicit: invalid
    identity rows cannot be added to manager lookup maps. Manager errors do not
    remove an employee from the accepted pool, but they do prevent that employee
    from becoming a root or creating a reporting relationship.
    """

    accepted_employees = identity_result.valid_employees
    employee_by_id = {
        employee.employee_id: employee for employee in accepted_employees
    }
    employee_by_email = {
        employee.email: employee for employee in accepted_employees
    }

    root_employees: list[ParsedEmployeeRow] = []
    employee_to_manager: dict[str, str] = {}
    errors: list[ValidationError] = []

    for employee in accepted_employees:
        if not employee.manager_id and not employee.manager_email:
            root_employees.append(employee)
            continue

        manager, error_message = _resolve_manager_reference(
            employee,
            employee_by_id,
            employee_by_email,
        )
        if error_message:
            errors.append(
                ValidationError(
                    source_row_number=employee.source_row_number,
                    message=error_message,
                )
            )
            continue

        if manager is employee:
            errors.append(
                ValidationError(
                    source_row_number=employee.source_row_number,
                    message="An employee cannot be their own manager.",
                )
            )
            continue

        # A manager is guaranteed here because a missing manager returns an error.
        employee_to_manager[employee.employee_id] = manager.employee_id

    return ManagerResolutionResult(
        accepted_employees=accepted_employees,
        root_employees=root_employees,
        employee_to_manager=employee_to_manager,
        errors=errors,
    )


def _resolve_manager_reference(
    employee: ParsedEmployeeRow,
    employee_by_id: dict[str, ParsedEmployeeRow],
    employee_by_email: dict[str, ParsedEmployeeRow],
) -> tuple[ParsedEmployeeRow | None, str | None]:
    """Resolve one employee's manager fields, without deciding self-management."""

    if employee.manager_id and not employee.manager_email:
        manager = employee_by_id.get(employee.manager_id)
        if manager is None:
            return None, f"Manager not found for manager_id: {employee.manager_id}."
        return manager, None

    if employee.manager_email and not employee.manager_id:
        manager = employee_by_email.get(employee.manager_email)
        if manager is None:
            return (
                None,
                f"Manager not found for manager_email: {employee.manager_email}.",
            )
        return manager, None

    manager_from_id = employee_by_id.get(employee.manager_id)
    manager_from_email = employee_by_email.get(employee.manager_email)

    if manager_from_id is None:
        return None, f"Manager not found for manager_id: {employee.manager_id}."
    if manager_from_email is None:
        return None, f"Manager not found for manager_email: {employee.manager_email}."
    if manager_from_id is not manager_from_email:
        return (
            None,
            "manager_id and manager_email point to different employees.",
        )

    return manager_from_id, None


def analyze_hierarchy(
    manager_result: ManagerResolutionResult,
) -> HierarchyAnalysisResult:
    """Calculate hierarchy output from valid manager relationships.

    ``root_employees`` is passed through from manager resolution. It already
    contains only identity-valid employees with both manager fields blank.
    Every entry in ``employee_to_manager`` is a valid direct relationship, so
    incrementing by manager ID produces direct-report counts without including
    manager-error employees or indirect reports.
    """

    direct_report_counts: dict[str, int] = {}
    for manager_id in manager_result.employee_to_manager.values():
        direct_report_counts[manager_id] = direct_report_counts.get(manager_id, 0) + 1

    return HierarchyAnalysisResult(
        root_employees=manager_result.root_employees,
        direct_report_counts=direct_report_counts,
    )


def detect_reporting_cycles(
    manager_result: ManagerResolutionResult,
) -> CycleAnalysisResult:
    """Find cycle members among valid ``employee -> manager`` relationships.

    The traversal is an iterative depth-first search for a graph in which each
    employee has at most one outgoing edge. ``path_positions`` represents the
    current VISITING path; ``processed`` represents VISITED nodes. Reaching a
    node already in the current path identifies a cycle, and only the suffix
    from that repeated node onward is added to the final cycle set.
    """

    employee_to_manager = manager_result.employee_to_manager
    processed: set[str] = set()
    cyclic_employee_ids: set[str] = set()

    for start_employee_id in employee_to_manager:
        if start_employee_id in processed:
            continue

        path: list[str] = []
        path_positions: dict[str, int] = {}
        current_employee_id = start_employee_id

        while (
            current_employee_id in employee_to_manager
            and current_employee_id not in processed
            and current_employee_id not in path_positions
        ):
            path_positions[current_employee_id] = len(path)
            path.append(current_employee_id)
            current_employee_id = employee_to_manager[current_employee_id]

        if current_employee_id in path_positions:
            cycle_start = path_positions[current_employee_id]
            cyclic_employee_ids.update(path[cycle_start:])

        processed.update(path)

    return CycleAnalysisResult(cyclic_employee_ids=cyclic_employee_ids)


def analyze_hris_csv(file_bytes: bytes) -> ImportAnalysisResult:
    """Run the complete HRIS import-preview analysis without persistence.

    A malformed upload raises ``CsvParsingError`` for the caller to present as
    a clear upload error. Row-level identity and manager issues are returned in
    ``validation_errors`` so the user can inspect the otherwise usable preview.
    """

    parsed_rows = parse_hris_csv(file_bytes)
    identity_result = validate_employee_identities(parsed_rows)
    manager_result = resolve_managers(identity_result)
    hierarchy_result = analyze_hierarchy(manager_result)
    cycle_result = detect_reporting_cycles(manager_result)

    validation_errors = sorted(
        [*identity_result.errors, *manager_result.errors],
        key=lambda error: error.source_row_number,
    )
    manager_summaries = [
        ManagerSummary(
            manager=employee,
            direct_report_count=hierarchy_result.direct_report_counts[
                employee.employee_id
            ],
        )
        for employee in manager_result.accepted_employees
        if employee.employee_id in hierarchy_result.direct_report_counts
    ]
    cyclic_employees = [
        employee
        for employee in manager_result.accepted_employees
        if employee.employee_id in cycle_result.cyclic_employee_ids
    ]

    return ImportAnalysisResult(
        total_source_rows=len(parsed_rows),
        accepted_employees=manager_result.accepted_employees,
        validation_errors=validation_errors,
        root_employees=hierarchy_result.root_employees,
        manager_summaries=manager_summaries,
        cyclic_employees=cyclic_employees,
    )


def _decode_utf8(file_bytes: bytes) -> str:
    """Decode UTF-8 data and remove a possible UTF-8 byte-order mark."""

    if not file_bytes:
        raise CsvParsingError("The uploaded file is empty.")

    try:
        return file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise CsvParsingError("The uploaded file must be valid UTF-8 text.") from error


def _validate_headers(headers: list[str]) -> None:
    """Ensure the required headers are present exactly once, in any order."""

    if not headers or all(header == "" for header in headers):
        raise CsvParsingError("The uploaded file is missing a header row.")

    duplicate_headers = sorted(
        {header for header in headers if headers.count(header) > 1}
    )
    if duplicate_headers:
        raise CsvParsingError(
            "Duplicate CSV header(s): " + ", ".join(duplicate_headers)
        )

    missing_headers = sorted(REQUIRED_HEADERS.difference(headers))
    if missing_headers:
        raise CsvParsingError(
            "Missing required CSV header(s): " + ", ".join(missing_headers)
        )
