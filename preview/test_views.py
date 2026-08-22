"""Browser-level tests for the thin HRIS upload view."""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from django.urls import reverse


class UploadPreviewViewTests(SimpleTestCase):
    def test_get_renders_upload_form(self) -> None:
        response = self.client.get(reverse("preview:upload"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "HRIS Import Preview")
        self.assertContains(response, "Analyze import")

    def test_post_without_file_shows_clear_error(self) -> None:
        response = self.client.post(reverse("preview:upload"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Choose a CSV file before analyzing.")

    def test_valid_upload_renders_analysis_results(self) -> None:
        csv_file = SimpleUploadedFile(
            "employees.csv",
            (
                "employee_id,employee_name,email,manager_id,manager_email,department\n"
                "DIV-1000,Avery,demo.avery@diversio.com,,,Executive\n"
                "DIV-1001,Blair,demo.blair@diversio.com,DIV-1000,,Engineering\n"
            ).encode("utf-8"),
            content_type="text/csv",
        )

        response = self.client.post(reverse("preview:upload"), {"hris_file": csv_file})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Total source rows")
        self.assertContains(response, "Accepted employees")
        self.assertContains(response, "Avery (DIV-1000)")
        self.assertContains(response, "Direct reports")

    def test_malformed_upload_shows_clear_error(self) -> None:
        csv_file = SimpleUploadedFile(
            "invalid.csv",
            b"employee_id,email\nDIV-1000,demo.avery@diversio.com\n",
            content_type="text/csv",
        )

        response = self.client.post(reverse("preview:upload"), {"hris_file": csv_file})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Missing required CSV header")
