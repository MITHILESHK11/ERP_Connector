"""
field_mapper.py
================
Generic, ERP-agnostic mapping engine.

Purpose
-------
Historically each adapter (Xero, QBO) hand-wrote a Python dict literal for
every resource (invoice, bill, contact, account) mapping the ERP's raw field
names onto our common schema. That meant "adding a new ERP" meant copying and
rewriting ~150 lines of normalization code per resource.

This module lets that mapping live in a YAML config file instead
(config/mappings/<erp>.yaml). Each field in our common schema is described by:

    target_field:
      source: "Dotted.Path.To.Value"      # where to read it from the raw ERP payload
      transform: "money_to_cents"         # (optional) named transform to apply
      default: null                       # (optional) fallback if source is missing

For the genuinely ERP-specific business logic that can't be expressed as a
plain field rename (e.g. QBO deriving "status" from Balance/TotalAmt since QBO
has no single status field, or building the line_items list), the config
points to a small named function registered in utils/transforms.py. That is
the ONLY code a new ERP integration should need to write — everything else
(which field goes where) is config.

Adding a brand new ERP therefore means:
  1. Write config/mappings/<new_erp>.yaml describing field names.
  2. Write (only if truly needed) 1-2 small transform functions for logic
     that has no config equivalent (e.g. deriving a status).
  3. Implement the thin HTTP calls (auth headers, endpoints) in a new adapter
     class — this part can never be pure config, since it involves real
     network requests, but normalization itself no longer needs to be.
"""

from __future__ import annotations
import os
import functools
from typing import Any, Callable

import yaml

MAPPINGS_DIR = os.path.join(os.path.dirname(__file__), "..", "config", "mappings")


def _get_path(data: dict, dotted_path: str) -> Any:
    """Resolve 'Contact.ContactID' style dotted paths against a nested dict."""
    if not dotted_path:
        return None
    current: Any = data
    for part in dotted_path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
        if current is None:
            return None
    return current


@functools.lru_cache(maxsize=None)
def load_mapping(erp_name: str, resource: str) -> dict:
    """
    Load and cache the field mapping for a given ERP + resource
    (e.g. load_mapping("xero", "invoice")).
    """
    path = os.path.join(MAPPINGS_DIR, f"{erp_name}.yaml")
    with open(path, "r", encoding="utf-8") as f:
        full_config = yaml.safe_load(f) or {}
    resource_config = full_config.get(resource)
    if resource_config is None:
        raise KeyError(
            f"No mapping found for resource '{resource}' in {path}. "
            f"Available resources: {list(full_config.keys())}"
        )
    return resource_config


def map_record(raw: dict, mapping: dict, transforms: dict[str, Callable]) -> dict:
    """
    Apply a field mapping (loaded from YAML) to a single raw ERP record.

    mapping shape:
        {
          "id": {"source": "InvoiceID"},
          "amount": {"source": "Total", "transform": "money_to_cents"},
          "status": {"transform": "xero_status"},   # transform-only, no source needed
          "currency": {"source": "CurrencyCode", "default": "USD"},
        }
    """
    result: dict[str, Any] = {}
    for target_field, spec in mapping.items():
        spec = spec or {}
        source_path = spec.get("source")
        transform_name = spec.get("transform")
        default = spec.get("default")

        value = _get_path(raw, source_path) if source_path else None

        if transform_name:
            transform_fn = transforms.get(transform_name)
            if transform_fn is None:
                raise KeyError(f"Unknown transform '{transform_name}' referenced in mapping")
            # Transform-only fields (no `source`) get the whole raw record instead,
            # since deriving them needs more than one field (e.g. status logic).
            value = transform_fn(raw if source_path is None else value)

        if value is None and default is not None:
            value = default

        result[target_field] = value

    return result
