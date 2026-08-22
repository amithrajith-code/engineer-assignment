"""Browser-facing upload view for the HRIS import preview."""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from .services import CsvParsingError, analyze_hris_csv


@require_http_methods(["GET", "POST"])
def upload_preview(request: HttpRequest) -> HttpResponse:
    """Render the upload form or a completed in-memory import preview."""

    context: dict[str, object] = {}

    if request.method == "POST":
        uploaded_file = request.FILES.get("hris_file")

        if uploaded_file is None:
            context["upload_error"] = "Choose a CSV file before analyzing."
        elif uploaded_file.size == 0:
            context["upload_error"] = "The uploaded file is empty."
        else:
            try:
                context["analysis"] = analyze_hris_csv(uploaded_file.read())
            except CsvParsingError as error:
                context["upload_error"] = str(error)

    return render(request, "preview/upload.html", context)
