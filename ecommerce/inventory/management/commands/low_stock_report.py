"""python manage.py low_stock_report [--out-only] [--csv]"""

import csv
import sys

from django.core.management.base import BaseCommand

from inventory import selectors


class Command(BaseCommand):
    help = "Print items that are low on or out of stock (cron-friendly)."

    def add_arguments(self, parser):
        parser.add_argument("--out-only", action="store_true", help="Only items at zero.")
        parser.add_argument("--csv", action="store_true", help="CSV output instead of a table.")

    def handle(self, *args, **opts):
        rows = selectors.stock_rows(status="out" if opts["out_only"] else "attention")
        if opts["csv"]:
            w = csv.writer(sys.stdout)
            w.writerow(["sku", "name", "on_hand", "threshold", "suggested_reorder", "status"])
            for r in rows:
                w.writerow([r["sku"], r["name"], r["stock_quantity"], r["low_stock_threshold"],
                            r["reorder_quantity"], r["status"]])
            return
        if not rows:
            self.stdout.write(self.style.SUCCESS("Nothing needs restocking."))
            return
        for r in rows:
            self.stdout.write(f"{r['status'].upper():4} {r['sku']:<20} {r['stock_quantity']:>5} "
                              f"(threshold {r['low_stock_threshold']})  {r['name']}")
        self.stdout.write(f"\n{len(rows)} item(s) need attention.")
