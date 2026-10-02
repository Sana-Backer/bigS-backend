"""
catalog/views_import.py  –  staff-only upload endpoint.

urls.py:
    from catalog.views_import import CatalogImportView
    path("api/catalog/import/", CatalogImportView.as_view()),

POST multipart/form-data  file=<xlsx>   [?dry_run=true]
"""
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog.services.importer import CatalogImporter


class CatalogImportView(APIView):
    permission_classes = [IsAdminUser]
    parser_classes = [MultiPartParser]

    def post(self, request):
        upload = request.FILES.get("file")
        if not upload:
            return Response({"detail": "Upload an .xlsx file in the 'file' field."},
                            status=status.HTTP_400_BAD_REQUEST)
        if not upload.name.lower().endswith(".xlsx"):
            return Response({"detail": "Only .xlsx files are supported."},
                            status=status.HTTP_400_BAD_REQUEST)

        dry_run = request.query_params.get("dry_run", "").lower() in ("1", "true", "yes")
        result = CatalogImporter(upload, dry_run=dry_run).run()
        return Response(result.as_dict(),
                        status=status.HTTP_200_OK if result.ok else status.HTTP_400_BAD_REQUEST)