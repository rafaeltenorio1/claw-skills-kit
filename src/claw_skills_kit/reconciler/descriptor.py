from __future__ import annotations

import json
from dataclasses import dataclass


class DescriptorError(ValueError):
    """The host descriptor is malformed."""


class TenantConflictError(DescriptorError):
    """The descriptor would put more than one tenant in a single gateway."""


@dataclass(frozen=True)
class SmokeSpec:
    commands: tuple[tuple[str, ...], ...] = ()
    timeout_seconds: float = 30.0


@dataclass(frozen=True)
class HostDescriptor:
    host_id: str
    skills_dir: str
    clients: tuple[str, ...]
    skills: tuple[str, ...]
    smoke: SmokeSpec = SmokeSpec()


def _string(data: dict, key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DescriptorError(f"'{key}' must be a non-empty string.")
    return value.strip()


def _string_list(data: dict, key: str) -> tuple[str, ...]:
    value = data.get(key)
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise DescriptorError(f"'{key}' must be a list of non-empty strings.")
    if len(set(value)) != len(value):
        raise DescriptorError(f"'{key}' has duplicate entries.")
    return tuple(v.strip() for v in value)


def _parse_smoke(raw: object) -> SmokeSpec:
    if raw is None:
        return SmokeSpec()
    if not isinstance(raw, dict):
        raise DescriptorError("'smoke' must be an object.")
    commands = raw.get("commands", [])
    if not isinstance(commands, list) or not all(
        isinstance(c, list) and c and all(isinstance(a, str) for a in c) for c in commands
    ):
        raise DescriptorError("'smoke.commands' must be a list of non-empty argv lists.")
    timeout = raw.get("timeout_seconds", 30)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise DescriptorError("'smoke.timeout_seconds' must be a positive number.")
    return SmokeSpec(tuple(tuple(c) for c in commands), float(timeout))


def load_descriptor(text: str) -> HostDescriptor:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DescriptorError(f"Host descriptor is not valid JSON (line {exc.lineno}): {exc.msg}.") from exc
    if not isinstance(data, dict):
        raise DescriptorError("Host descriptor must be a JSON object.")
    return HostDescriptor(
        host_id=_string(data, "host_id"),
        skills_dir=_string(data, "skills_dir"),
        clients=_string_list(data, "clients"),
        skills=_string_list(data, "skills"),
        smoke=_parse_smoke(data.get("smoke")),
    )


def check_single_tenant(descriptor: HostDescriptor) -> None:

    if not descriptor.clients:
        raise DescriptorError("The host has no client; a gateway needs exactly one.")
    if len(descriptor.clients) > 1:
        names = ", ".join(descriptor.clients)
        raise TenantConflictError(
            f"Refusing to place {len(descriptor.clients)} tenants in one gateway ({names}); "
            "use one gateway per client."
        )