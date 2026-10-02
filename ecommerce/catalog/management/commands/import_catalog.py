"""
Usage:
    python manage.py import_catalog path/to/catalog.xlsx
    python manage.py import_catalog path/to/catalog.xlsx --dry-run
"""
import json

from django.core.management.base import BaseCommand, CommandError

from catalog.services.importer import CatalogImporter


class Command(BaseCommand):
    help = "Bulk import categories, products, variants and images from an Excel file."

    def add_arguments(self, parser):
        parser.add_argument("file", help="Path to the .xlsx file")
        parser.add_argument("--dry-run", action="store_true", help="Validate only; save nothing")

    def handle(self, *args, **opts):
        try:
            with open(opts["file"], "rb") as fh:
                result = CatalogImporter(fh, dry_run=opts["dry_run"]).run()
        except FileNotFoundError:
            raise CommandError(f"File not found: {opts['file']}")

        if not result.ok:
            for err in result.errors:
                self.stderr.write(self.style.ERROR(err))
            raise CommandError(f"Import failed with {len(result.errors)} error(s). Nothing was saved.")

        label = "DRY RUN (nothing saved)" if result.dry_run else "Import complete"
        self.stdout.write(self.style.SUCCESS(label))
        self.stdout.write(json.dumps(result.as_dict(), indent=2))