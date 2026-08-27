from __future__ import annotations

from pathlib import Path
from typing import Any

from sofia_registry import RegistryLoadResult, load_control_center_registry


def apply_manifest_registry(
    legacy_registry: dict[str, dict[str, Any]],
    home: str | Path,
    providers_dir: str | Path,
) -> RegistryLoadResult:
    return load_control_center_registry(
        legacy_registry=legacy_registry,
        providers_dir=providers_dir,
        home=home,
    )
