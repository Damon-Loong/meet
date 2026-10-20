"""Preview delivered-mail imports on an isolated database copy; never write live data.

Usage: python -m summary.core.preview_mail_reminders --database state.sqlite3
       --tenant meet --bundle delivered-mail.json
Bundle: list of {source, summary, transcript, participants} from stored deliveries.
No model calls, email sends or production writes occur.
"""

import argparse
import json
import sqlite3
import tempfile
from pathlib import Path

from summary.core.personal_memory import PersonalMemory


def main():
    """Preview the full bundle without mutating the source database."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--bundle", required=True)
    args = parser.parse_args()
    documents = json.loads(Path(args.bundle).read_text())
    if not isinstance(documents, list):
        raise ValueError("Expected a list of delivered meeting documents")
    with tempfile.TemporaryDirectory(prefix="mail-reminders-preview-") as folder:
        target = Path(folder) / "preview.sqlite3"
        with sqlite3.connect(
            Path(args.database).resolve().as_uri() + "?mode=ro", uri=True
        ) as source:
            with sqlite3.connect(target) as dest:
                source.backup(dest)
        memory = PersonalMemory(target, args.tenant)
        results = []
        for document in documents:
            result = memory.ingest_summary(
                document["summary"],
                document["transcript"],
                document["source"],
                document["participants"],
            )
            results.append({"source": document["source"], **result})
        people = [
            {
                "name": person["name"],
                "email": email,
                "items": memory.task_items_by_email(email),
            }
            for person in memory.people()
            for email in person["emails"]
        ]
        print(  # noqa: T201
            json.dumps(
                {"preview_only": True, "imports": results, "people": people},
                ensure_ascii=False,
                indent=2,
            )
        )
        if any(r["status"] == "needs_review" for r in results):
            raise SystemExit(2)


if __name__ == "__main__":
    main()
