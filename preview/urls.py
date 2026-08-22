from django.urls import path

from . import views


app_name = "preview"

urlpatterns = [
    path("", views.upload_preview, name="upload"),
]
