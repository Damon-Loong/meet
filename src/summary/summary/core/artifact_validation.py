"""2026-10-20，wyy 新增：验证会后 Agent 产物后才能按用户邮件交付.

负责路径边界、大小、扩展名和 Office 包结构校验；不替代业务事实审核。
"""

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

MIME = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ),
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
}


def _xml(data):
    """Parse bounded Office XML after rejecting DTD and entity declarations."""
    # DTD/ENTITY are unnecessary in OOXML. UTF-16 could obscure the declaration scan.
    if b"\x00" in data or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("XML declarations rejected")
    return ET.fromstring(data)  # noqa: S314 - DTD/entity declarations rejected above.


def validate_artifacts(folder, entries, limit=18 * 1024 * 1024):  # noqa: PLR0912
    """Validate bounded, non-macro deliverables inside the finished stage workspace."""
    root = Path(folder).resolve(strict=True)
    accepted, used, seen = [], 0, set()
    if not isinstance(entries, list) or len(entries) > 10:
        raise ValueError("Invalid artifact list")
    for entry in entries:
        relative = entry.get("path", "") if isinstance(entry, dict) else ""
        path = root / relative
        # Reject every symlink component, not only an escaping final target.
        if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("Unsafe artifact path")
        if any(p.is_symlink() for p in [path, *path.parents] if p != root.parent):
            raise ValueError("Symlink artifact rejected")
        actual = path.resolve(strict=True)
        if not actual.is_relative_to(root) or not actual.is_file() or actual in seen:
            raise ValueError("Artifact must be a unique file inside this job")
        seen.add(actual)
        size = actual.stat().st_size
        used += size
        ext = actual.suffix.lower()
        if size < 1 or used > limit or ext not in MIME:
            raise ValueError("Artifact type or size rejected")
        if ext in (".xlsx", ".pptx"):
            with zipfile.ZipFile(actual) as archive:
                names = archive.namelist()
                if (
                    len(names) > 10000
                    or sum(i.file_size for i in archive.infolist()) > 100 * 1024 * 1024
                    or len(names) != len(set(names))
                    or any("vbaproject" in n.lower() for n in names)
                ):
                    raise ValueError("Unsafe or oversized Office package")
                _xml(
                    archive.read(
                        "xl/workbook.xml" if ext == ".xlsx" else "ppt/presentation.xml"
                    )
                )
                content_types = _xml(archive.read("[Content_Types].xml"))
                if any(
                    term in entry.get("ContentType", "").lower()
                    for entry in content_types
                    for term in ("macroenabled", "vbaproject", "oleobject")
                ):
                    raise ValueError("Active Office content rejected")
                binary_type = next(
                    (
                        entry.get("ContentType", "")
                        for entry in content_types
                        if entry.get("Extension", "").lower() == "bin"
                    ),
                    "",
                )
                for part in archive.infolist():
                    if not part.filename.lower().endswith(".bin"):
                        continue
                    # python-pptx and LibreOffice include DEVMODE printer settings.
                    # Permit only this bounded inert part, never macros or OLE objects.
                    if (
                        not re.fullmatch(
                            r"(?:xl|ppt)/printerSettings/printerSettings\d+\.bin",
                            part.filename,
                        )
                        or binary_type
                        not in (
                            "application/vnd.openxmlformats-officedocument.presentationml.printerSettings",
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.printerSettings",
                        )
                        or part.file_size > 1024 * 1024
                    ):
                        raise ValueError("Embedded Office binary rejected")
                prefix = "xl/worksheets/sheet" if ext == ".xlsx" else "ppt/slides/slide"
                pages = [
                    n for n in names if n.startswith(prefix) and n.endswith(".xml")
                ]
                if not pages:
                    raise ValueError("Empty Office document")
                for name in pages:
                    _xml(archive.read(name))
                for name in names:
                    if name.endswith(".rels"):
                        relationships = _xml(archive.read(name))
                        if any(
                            r.get("TargetMode", "").lower() == "external"
                            for r in relationships
                        ):
                            raise ValueError("External Office relationships rejected")
        elif ext == ".pdf":
            with actual.open("rb") as stream:
                if stream.read(5) != b"%PDF-":
                    raise ValueError("Invalid PDF")
        elif ext in (".txt", ".md", ".csv"):
            actual.read_text(encoding="utf-8")
        accepted.append(
            {"path": str(actual), "filename": actual.name, "mime": MIME[ext]}
        )
    return accepted
