"""Focused unit tests for CSV parsing and normalization."""

import unittest

if __package__:
    from .services import (
        analyze_hris_csv,
        analyze_hierarchy,
        CsvParsingError,
        detect_reporting_cycles,
        parse_hris_csv,
        resolve_managers,
        validate_employee_identities,
    )
else:
    from services import (
        analyze_hris_csv,
        analyze_hierarchy,
        CsvParsingError,
        detect_reporting_cycles,
        parse_hris_csv,
        resolve_managers,
        validate_employee_identities,
    )


class ParseHrisCsvTests(unittest.TestCase):
    def test_headers_can_be_reordered_and_values_are_normalized(self) -> None:
        csv_text = """ email ,department,manager_email,employee_name,employee_id,manager_id
 DEMO.AVERY@DIVERSIO.COM , Executive , DEMO.MANAGER@DIVERSIO.COM , Avery Morgan , DIV-1001 , DIV-0001
"""

        rows = parse_hris_csv(csv_text.encode("utf-8"))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].source_row_number, 2)
        self.assertEqual(rows[0].employee_id, "DIV-1001")
        self.assertEqual(rows[0].email, "demo.avery@diversio.com")
        self.assertEqual(rows[0].manager_id, "DIV-0001")
        self.assertEqual(rows[0].manager_email, "demo.manager@diversio.com")
        self.assertEqual(rows[0].employee_name, "Avery Morgan")
        self.assertEqual(rows[0].department, "Executive")

    def test_utf8_bom_and_quoted_comma_are_supported(self) -> None:
        csv_text = """employee_id,employee_name,email,manager_id,manager_email,department
DIV-1412,"Alvarez, Renée",DEMO.RENEE@DIVERSIO.COM,,,Operations
"""

        rows = parse_hris_csv(csv_text.encode("utf-8-sig"))

        self.assertEqual(rows[0].source_row_number, 2)
        self.assertEqual(rows[0].employee_name, "Alvarez, Renée")
        self.assertEqual(rows[0].email, "demo.renee@diversio.com")
        self.assertEqual(rows[0].employee_id, "DIV-1412")

    def test_missing_required_header_has_a_clear_error(self) -> None:
        csv_text = "employee_id,employee_name,email,manager_id,manager_email\n"

        with self.assertRaisesRegex(CsvParsingError, "department"):
            parse_hris_csv(csv_text.encode("utf-8"))

    def test_malformed_csv_has_a_clear_error(self) -> None:
        csv_text = (
            "employee_id,employee_name,email,manager_id,manager_email,department\n"
            "DIV-1412,\"Alvarez, Renée,demo.renee@diversio.com,,,Operations\n"
        )

        with self.assertRaisesRegex(CsvParsingError, "Malformed CSV"):
            parse_hris_csv(csv_text.encode("utf-8"))


class IdentityValidationTests(unittest.TestCase):
    def test_all_rows_in_a_duplicate_employee_id_group_are_invalid(self) -> None:
        rows = parse_hris_csv(
            (
                "employee_id,employee_name,email,manager_id,manager_email,department\n"
                "DIV-1001,Avery,demo.avery@diversio.com,,,Executive\n"
                "DIV-1001,Avery Duplicate,demo.other@diversio.com,,,Executive\n"
                "DIV-1002,Valid,demo.valid@diversio.com,,,Engineering\n"
            ).encode("utf-8")
        )

        result = validate_employee_identities(rows)

        self.assertEqual([row.employee_id for row in result.valid_employees], ["DIV-1002"])
        self.assertEqual([error.source_row_number for error in result.errors], [2, 3])
        self.assertTrue(
            all("Duplicate employee_id: DIV-1001." == error.message for error in result.errors)
        )

    def test_all_rows_in_a_duplicate_normalized_email_group_are_invalid(self) -> None:
        rows = parse_hris_csv(
            (
                "employee_id,employee_name,email,manager_id,manager_email,department\n"
                "DIV-1001,Avery,DEMO.SHARED@DIVERSIO.COM,,,Executive\n"
                "DIV-1002,Blair,demo.shared@diversio.com,,,Engineering\n"
                "DIV-1003,Casey,demo.casey@diversio.com,,,People\n"
            ).encode("utf-8")
        )

        result = validate_employee_identities(rows)

        self.assertEqual([row.employee_id for row in result.valid_employees], ["DIV-1003"])
        self.assertEqual([error.source_row_number for error in result.errors], [2, 3])
        self.assertTrue(
            all("Duplicate email: demo.shared@diversio.com." == error.message for error in result.errors)
        )

    def test_missing_identity_values_produce_source_row_errors(self) -> None:
        rows = parse_hris_csv(
            (
                "employee_id,employee_name,email,manager_id,manager_email,department\n"
                ",Missing Both,,,,People\n"
                "DIV-1002,Valid,demo.valid@diversio.com,,,Engineering\n"
            ).encode("utf-8")
        )

        result = validate_employee_identities(rows)

        self.assertEqual([row.employee_id for row in result.valid_employees], ["DIV-1002"])
        self.assertEqual(
            [(error.source_row_number, error.message) for error in result.errors],
            [(2, "employee_id is required."), (2, "email is required.")],
        )

    def test_employee_ids_remain_case_sensitive_during_duplicate_detection(self) -> None:
        rows = parse_hris_csv(
            (
                "employee_id,employee_name,email,manager_id,manager_email,department\n"
                "DIV-1001,Upper,demo.upper@diversio.com,,,Executive\n"
                "div-1001,Lower,demo.lower@diversio.com,,,Engineering\n"
            ).encode("utf-8")
        )

        result = validate_employee_identities(rows)

        self.assertEqual(len(result.valid_employees), 2)
        self.assertEqual(result.errors, [])


class ManagerResolutionTests(unittest.TestCase):
    def _resolve(self, csv_text: str):
        rows = parse_hris_csv(csv_text.encode("utf-8"))
        return resolve_managers(validate_employee_identities(rows))

    def test_manager_can_appear_after_their_report(self) -> None:
        result = self._resolve(
            (
                "employee_id,employee_name,email,manager_id,manager_email,department\n"
                "DIV-2000,Report,demo.report@diversio.com,DIV-1000,,Engineering\n"
                "DIV-1000,Manager,demo.manager@diversio.com,,,Executive\n"
            )
        )

        self.assertEqual(result.employee_to_manager, {"DIV-2000": "DIV-1000"})
        self.assertEqual([row.employee_id for row in result.root_employees], ["DIV-1000"])
        self.assertEqual(result.errors, [])

    def test_both_matching_manager_references_create_one_relationship(self) -> None:
        result = self._resolve(
            (
                "employee_id,employee_name,email,manager_id,manager_email,department\n"
                "DIV-1000,Manager,demo.manager@diversio.com,,,Executive\n"
                "DIV-2000,Report,demo.report@diversio.com,DIV-1000,DEMO.MANAGER@DIVERSIO.COM,Engineering\n"
            )
        )

        self.assertEqual(result.employee_to_manager, {"DIV-2000": "DIV-1000"})
        self.assertEqual(result.errors, [])

    def test_missing_manager_keeps_employee_accepted_without_relationship(self) -> None:
        result = self._resolve(
            (
                "employee_id,employee_name,email,manager_id,manager_email,department\n"
                "DIV-2000,Report,demo.report@diversio.com,DIV-9999,,Engineering\n"
            )
        )

        self.assertEqual([row.employee_id for row in result.accepted_employees], ["DIV-2000"])
        self.assertEqual(result.employee_to_manager, {})
        self.assertEqual(result.root_employees, [])
        self.assertEqual(result.errors[0].source_row_number, 2)
        self.assertIn("Manager not found", result.errors[0].message)

    def test_conflicting_manager_references_create_an_error(self) -> None:
        result = self._resolve(
            (
                "employee_id,employee_name,email,manager_id,manager_email,department\n"
                "DIV-1000,First,demo.first@diversio.com,,,Executive\n"
                "DIV-1001,Second,demo.second@diversio.com,,,Executive\n"
                "DIV-2000,Report,demo.report@diversio.com,DIV-1000,demo.second@diversio.com,Engineering\n"
            )
        )

        self.assertEqual(result.employee_to_manager, {})
        self.assertIn("different employees", result.errors[0].message)

    def test_self_manager_creates_an_error(self) -> None:
        result = self._resolve(
            (
                "employee_id,employee_name,email,manager_id,manager_email,department\n"
                "DIV-1000,Self,demo.self@diversio.com,DIV-1000,,Executive\n"
            )
        )

        self.assertEqual(result.employee_to_manager, {})
        self.assertEqual(result.root_employees, [])
        self.assertIn("own manager", result.errors[0].message)

    def test_identity_invalid_rows_are_not_available_as_managers(self) -> None:
        result = self._resolve(
            (
                "employee_id,employee_name,email,manager_id,manager_email,department\n"
                "DIV-1000,Duplicate One,demo.one@diversio.com,,,Executive\n"
                "DIV-1000,Duplicate Two,demo.two@diversio.com,,,Executive\n"
                "DIV-2000,Report,demo.report@diversio.com,DIV-1000,,Engineering\n"
            )
        )

        self.assertEqual([row.employee_id for row in result.accepted_employees], ["DIV-2000"])
        self.assertEqual(result.employee_to_manager, {})
        self.assertIn("Manager not found", result.errors[0].message)


class HierarchyAnalysisTests(unittest.TestCase):
    def _analyze(self, csv_text: str):
        rows = parse_hris_csv(csv_text.encode("utf-8"))
        identity_result = validate_employee_identities(rows)
        return analyze_hierarchy(resolve_managers(identity_result))

    def test_roots_and_direct_counts_use_only_valid_relationships(self) -> None:
        result = self._analyze(
            (
                "employee_id,employee_name,email,manager_id,manager_email,department\n"
                "DIV-1000,Root,demo.root@diversio.com,,,Executive\n"
                "DIV-1001,Middle,demo.middle@diversio.com,DIV-1000,,Engineering\n"
                "DIV-1002,Report,demo.report@diversio.com,DIV-1000,,Engineering\n"
                "DIV-1003,Bad Manager,demo.bad@diversio.com,DIV-9999,,People\n"
            )
        )

        self.assertEqual([row.employee_id for row in result.root_employees], ["DIV-1000"])
        self.assertEqual(result.direct_report_counts, {"DIV-1000": 2})

    def test_direct_report_counts_do_not_include_indirect_reports(self) -> None:
        result = self._analyze(
            (
                "employee_id,employee_name,email,manager_id,manager_email,department\n"
                "DIV-1000,Root,demo.root@diversio.com,,,Executive\n"
                "DIV-1001,Middle,demo.middle@diversio.com,DIV-1000,,Engineering\n"
                "DIV-1002,Leaf,demo.leaf@diversio.com,DIV-1001,,Engineering\n"
            )
        )

        self.assertEqual(
            result.direct_report_counts,
            {"DIV-1000": 1, "DIV-1001": 1},
        )


class ReportingCycleTests(unittest.TestCase):
    def _detect_cycles(self, csv_text: str):
        rows = parse_hris_csv(csv_text.encode("utf-8"))
        identity_result = validate_employee_identities(rows)
        return detect_reporting_cycles(resolve_managers(identity_result))

    def test_only_actual_members_of_a_cycle_are_marked(self) -> None:
        result = self._detect_cycles(
            (
                "employee_id,employee_name,email,manager_id,manager_email,department\n"
                "A,A,demo.a@diversio.com,B,,Engineering\n"
                "B,B,demo.b@diversio.com,C,,Engineering\n"
                "C,C,demo.c@diversio.com,A,,Engineering\n"
                "X,X,demo.x@diversio.com,A,,Engineering\n"
            )
        )

        self.assertEqual(result.cyclic_employee_ids, {"A", "B", "C"})
        self.assertNotIn("X", result.cyclic_employee_ids)

    def test_manager_error_employee_cannot_create_or_join_a_cycle(self) -> None:
        result = self._detect_cycles(
            (
                "employee_id,employee_name,email,manager_id,manager_email,department\n"
                "A,A,demo.a@diversio.com,B,,Engineering\n"
                "B,B,demo.b@diversio.com,A,,Engineering\n"
                "BAD,Bad,demo.bad@diversio.com,MISSING,,Engineering\n"
            )
        )

        self.assertEqual(result.cyclic_employee_ids, {"A", "B"})
        self.assertNotIn("BAD", result.cyclic_employee_ids)

    def test_identity_invalid_rows_do_not_participate_in_cycles(self) -> None:
        result = self._detect_cycles(
            (
                "employee_id,employee_name,email,manager_id,manager_email,department\n"
                "A,Duplicate One,demo.one@diversio.com,B,,Engineering\n"
                "A,Duplicate Two,demo.two@diversio.com,B,,Engineering\n"
                "B,B,demo.b@diversio.com,A,,Engineering\n"
            )
        )

        self.assertEqual(result.cyclic_employee_ids, set())


class ImportAnalysisTests(unittest.TestCase):
    def test_complete_analysis_returns_view_ready_sample_result(self) -> None:
        csv_bytes = (
            "employee_id,employee_name,email,manager_id,manager_email,department\n"
            "DIV-1112,Noa,demo.noa@diversio.com,,DEMO.SOFIA@DIVERSIO.COM,Engineering\n"
            "DIV-1001,Avery,demo.avery@diversio.com,,,Executive\n"
            "DIV-1110,Sofia,demo.sofia@diversio.com,DIV-1001,,Engineering\n"
            "DIV-1600,Casey,demo.casey@diversio.com,DIV-9999,,Operations\n"
            "DIV-1702,Alex,demo.alex@diversio.com,DIV-1703,,Research\n"
            "DIV-1703,Taylor,demo.taylor@diversio.com,DIV-1701,,Research\n"
            "DIV-1701,Morgan,demo.morgan@diversio.com,DIV-1702,,Research\n"
        ).encode("utf-8")

        result = analyze_hris_csv(csv_bytes)

        self.assertEqual(result.total_source_rows, 7)
        self.assertEqual(len(result.accepted_employees), 7)
        self.assertEqual(
            [(error.source_row_number, error.message) for error in result.validation_errors],
            [(5, "Manager not found for manager_id: DIV-9999.")],
        )
        self.assertEqual([employee.employee_id for employee in result.root_employees], ["DIV-1001"])
        self.assertEqual(
            [(summary.manager.employee_id, summary.direct_report_count) for summary in result.manager_summaries],
            [("DIV-1001", 1), ("DIV-1110", 1), ("DIV-1702", 1), ("DIV-1703", 1), ("DIV-1701", 1)],
        )
        self.assertEqual(
            [employee.employee_id for employee in result.cyclic_employees],
            ["DIV-1702", "DIV-1703", "DIV-1701"],
        )

    def test_malformed_upload_error_is_preserved_for_the_view(self) -> None:
        with self.assertRaisesRegex(CsvParsingError, "Missing required CSV header"):
            analyze_hris_csv(b"employee_id,email\nDIV-1001,demo@diversio.com\n")


if __name__ == "__main__":
    unittest.main()
