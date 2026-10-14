"""Device family libraries for ShipMBLang.

Device families describe the resource surface available for a currently
selected target device. The registry is intentionally data-only so the compiler,
runtime, and MCP server can all expose the same resource catalog.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class DeviceResource:
    name: str
    kind: str
    description: str
    capabilities: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "description": self.description,
            "capabilities": list(self.capabilities),
        }


@dataclass(frozen=True)
class DeviceFamily:
    name: str
    display_name: str
    description: str
    aliases: tuple[str, ...]
    resources: tuple[DeviceResource, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "aliases": list(self.aliases),
            "resources": [resource.to_dict() for resource in self.resources],
        }


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _contains_slug_token(text: str, token: str) -> bool:
    return re.search(rf"(?:^|-){re.escape(token)}(?:-|$)", text) is not None


DEVICE_FAMILIES: dict[str, DeviceFamily] = {
    "host": DeviceFamily(
        name="host",
        display_name="Local host",
        description="The local machine running ShipMBLang.",
        aliases=("local", "computer", "workstation", "desktop", "server"),
        resources=(
            DeviceResource("filesystem", "storage", "Project files and safe workspace-relative paths.", ("read", "write")),
            DeviceResource("process", "runtime", "Recorded process/run intents for local execution backends.", ("plan",)),
            DeviceResource("environment", "runtime", "Environment variables and runtime configuration.", ("read",)),
            DeviceResource("clock", "system", "Local time and timing information.", ("read",)),
        ),
    ),
    "cuda": DeviceFamily(
        name="cuda",
        display_name="CUDA GPU",
        description="NVIDIA CUDA-capable GPU resources for model and tensor work.",
        aliases=("gpu", "nvidia", "nvidia-gpu"),
        resources=(
            DeviceResource("tensors", "compute", "Tensor allocations placed on the CUDA device.", ("allocate", "read", "write")),
            DeviceResource("gpu-memory", "memory", "Dedicated GPU memory available to CUDA workloads.", ("read", "allocate")),
            DeviceResource("kernels", "compute", "CUDA kernel dispatch surface.", ("dispatch",)),
            DeviceResource("streams", "compute", "CUDA stream scheduling resources.", ("schedule",)),
        ),
    ),
    "mps": DeviceFamily(
        name="mps",
        display_name="Apple MPS GPU",
        description="Apple Metal Performance Shaders GPU resources.",
        aliases=("apple-gpu", "metal", "metal-gpu"),
        resources=(
            DeviceResource("tensors", "compute", "Tensor allocations placed on the MPS device.", ("allocate", "read", "write")),
            DeviceResource("unified-memory", "memory", "Shared CPU/GPU memory available to Metal workloads.", ("read", "allocate")),
            DeviceResource("metal-kernels", "compute", "Metal kernel dispatch surface.", ("dispatch",)),
        ),
    ),
    "browser": DeviceFamily(
        name="browser",
        display_name="Browser runtime",
        description="A browser page or webview runtime controlled by ShipMBLang integrations.",
        aliases=("web", "webview", "page"),
        resources=(
            DeviceResource("dom", "document", "The current document tree.", ("read", "query", "mutate")),
            DeviceResource("viewport", "display", "Visible page size, screenshots, and layout bounds.", ("read", "capture")),
            DeviceResource("storage", "storage", "Browser-local storage scopes.", ("read", "write")),
            DeviceResource("network", "network", "Page network requests and responses.", ("observe",)),
        ),
    ),
    "embedded": DeviceFamily(
        name="embedded",
        display_name="Embedded board",
        description="Microcontroller or single-board computer resources.",
        aliases=("board", "microcontroller", "raspberry-pi", "arduino"),
        resources=(
            DeviceResource("gpio", "io", "General-purpose digital input/output pins.", ("read", "write")),
            DeviceResource("serial", "io", "Serial console or UART transport.", ("read", "write")),
            DeviceResource("i2c", "bus", "I2C device bus.", ("read", "write", "scan")),
            DeviceResource("spi", "bus", "SPI device bus.", ("read", "write")),
            DeviceResource("flash", "storage", "On-device persistent storage.", ("read", "write")),
        ),
    ),
}


_ALIASES: dict[str, str] = {}
for _family in DEVICE_FAMILIES.values():
    _ALIASES[_family.name] = _family.name
    _ALIASES[_slug(_family.display_name)] = _family.name
    for _alias in _family.aliases:
        _ALIASES[_slug(_alias)] = _family.name


def list_device_families() -> list[dict[str, Any]]:
    """Return all known device family libraries."""
    return [family.to_dict() for family in DEVICE_FAMILIES.values()]


def normalize_device_family(value: str | None) -> str | None:
    """Normalize a user-facing family name or alias to a registry key."""
    if not value:
        return None
    return _ALIASES.get(_slug(value))


def get_device_family(value: str | None) -> dict[str, Any] | None:
    """Return a device family by name or alias."""
    key = normalize_device_family(value)
    if key is None:
        return None
    return DEVICE_FAMILIES[key].to_dict()


def find_device_family_keyword(text: str) -> str | None:
    """Return the first device family keyword found in free-form text."""
    normalized = _slug(text)
    for keyword, family in sorted(_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if _contains_slug_token(normalized, keyword):
            return family
    return None


def require_device_family(value: str | None) -> dict[str, Any]:
    """Return a device family or raise a clear error."""
    family = get_device_family(value)
    if family is None:
        known = ", ".join(sorted(DEVICE_FAMILIES))
        raise ValueError(f"Unknown device family: {value!r}. Known families: {known}")
    return family


def list_device_resources(family: str | None) -> list[dict[str, Any]]:
    """Return resources for a device family by name or alias."""
    return require_device_family(family)["resources"]


def get_device_resource(family: str | None, resource: str | None) -> dict[str, Any] | None:
    """Return a named resource from a device family."""
    if not resource:
        return None
    normalized = _slug(resource)
    for item in list_device_resources(family):
        if _slug(str(item.get("name"))) == normalized:
            return item
    return None


def find_device_resource_keyword(text: str, family: str | None = None) -> str | None:
    """Return the first resource keyword found in free-form text."""
    normalized = _slug(text)
    if family:
        resources = list_device_resources(family)
    else:
        resources = [
            resource
            for device_family in DEVICE_FAMILIES
            for resource in list_device_resources(device_family)
        ]
    for resource in sorted(resources, key=lambda item: len(str(item.get("name"))), reverse=True):
        name = str(resource.get("name") or "")
        if _contains_slug_token(normalized, _slug(name)):
            return name
    return None


def require_device_resource(family: str | None, resource: str | None) -> dict[str, Any]:
    """Return a resource or raise a clear error."""
    item = get_device_resource(family, resource)
    if item is not None:
        return item
    family_info = require_device_family(family)
    known = ", ".join(resource["name"] for resource in family_info["resources"])
    raise ValueError(f"Unknown resource {resource!r} for device family {family_info['name']}. Known resources: {known}")


def format_device_family_library(family: str | None = None) -> str:
    """Render the full library or one family for MCP resource reads."""
    families = [require_device_family(family)] if family else list_device_families()
    chunks: list[str] = []
    for item in families:
        chunks.append(f"DEVICE FAMILY: {item['display_name']} ({item['name']})")
        chunks.append(f"DESCRIPTION: {item['description']}")
        chunks.append("RESOURCES:")
        for resource in item["resources"]:
            capabilities = ", ".join(resource.get("capabilities") or [])
            suffix = f" [{capabilities}]" if capabilities else ""
            chunks.append(f"- {resource['name']} ({resource['kind']}): {resource['description']}{suffix}")
        chunks.append("")
    return "\n".join(chunks).strip()


def format_device_resource(family: str | None, resource: str | None) -> str:
    """Render one resource for MCP resource reads."""
    family_info = require_device_family(family)
    item = require_device_resource(family_info["name"], resource)
    capabilities = ", ".join(item.get("capabilities") or []) or "none"
    return "\n".join(
        [
            f"DEVICE FAMILY: {family_info['display_name']} ({family_info['name']})",
            f"RESOURCE: {item['name']}",
            f"KIND: {item['kind']}",
            f"CAPABILITIES: {capabilities}",
            f"DESCRIPTION: {item['description']}",
        ]
    )


__all__ = [
    "DEVICE_FAMILIES",
    "DeviceFamily",
    "DeviceResource",
    "find_device_family_keyword",
    "find_device_resource_keyword",
    "format_device_family_library",
    "format_device_resource",
    "get_device_family",
    "get_device_resource",
    "list_device_families",
    "list_device_resources",
    "normalize_device_family",
    "require_device_family",
    "require_device_resource",
]
