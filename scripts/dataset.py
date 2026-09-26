import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

SCOPES = (
    ("category", "categories", "slug"),
    ("merchant", "merchants", "merchant_id"),
    ("customer", "customers", "customer_id"),
    ("trigger", "triggers", "id"),
)


def iter_contexts(root: Path) -> Iterator[tuple[str, str, dict[str, Any]]]:
    """Yields (scope, context_id, payload) from an expanded dataset or the raw seed files."""
    for scope, folder, key in SCOPES:
        directory = root / folder
        if directory.is_dir():
            payloads = [json.loads(f.read_text()) for f in sorted(directory.glob("*.json"))]
        else:
            seed = root / f"{folder}_seed.json"
            payloads = json.loads(seed.read_text())[folder] if seed.exists() else []
        for payload in payloads:
            yield scope, payload[key], payload
