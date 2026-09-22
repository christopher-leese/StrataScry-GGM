# SPDX-License-Identifier: Apache-2.0
"""Small persistent package registry. Removing an entry never removes its data."""
import json
from pathlib import Path
import uuid

from .model import PackageError, read_json, validate_bounds


class Catalog:
    def __init__(self, path):
        self.path = Path(path)
        self.entries = []
        self.active_id = None
        self.error = None
        if self.path.exists():
            try:
                data = read_json(self.path)
                if data.get("version") != 1 or len(data["entries"]) > 128:
                    raise PackageError("Unsupported or oversized map catalog")
                for entry in data["entries"]:
                    if not all(isinstance(entry.get(k), str) for k in ("id", "name", "path")):
                        raise PackageError("Invalid map catalog entry")
                    validate_bounds(entry["bounds"])
                self.entries = data["entries"]
                self.active_id = data.get("active_id")
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                self.error = f"Map catalog could not be read: {error}"

    def save(self):
        if self.error:
            raise PackageError(self.error + ". Repair or move this file before saving: " + str(self.path))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + f".{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps({"version": 1, "entries": self.entries,
                                             "active_id": self.active_id}, indent=2), encoding="utf-8")
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def add(self, package):
        if len(self.entries) >= 128 and not any(entry["id"] == package.id for entry in self.entries):
            raise PackageError("The map catalog supports up to 128 packages; remove an entry first")
        self.entries = [entry for entry in self.entries if entry["id"] != package.id]
        self.entries.append({"id": package.id, "name": package.name,
                             "path": str(package.root), "bounds": list(package.bounds)})

    def remove(self, package_id):
        self.entries = [entry for entry in self.entries if entry["id"] != package_id]
        if self.active_id == package_id:
            self.active_id = None
