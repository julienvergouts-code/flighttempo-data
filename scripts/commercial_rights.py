"""Shared fail-closed commercial reuse rules for downloadable datasets."""
from __future__ import annotations

import json
from pathlib import Path

FIRST_PARTY_DATASET_IDS = {"airline_profiles", "route_rules", "route_policy"}
VERIFIED_LICENSE_STATUSES = {
    "public_domain",
    "cc0_structured_data",
    "owner_authored_profile",
    "verified_open_license_commercial_reuse",
    "verified_exact_eaip_product_linked_to_open_license",
    "commercial_use_permitted_subject_to_ofma_gul",
    # SIA France: the importer re-checks the free eAIP product price and the Licence Ouverte wording live on every run.
    "verified_commercial_open_licence",
}
BLOCKED_MARKERS = (
    "public_redistribution_not_confirmed",
    "redistribution_not_confirmed",
    "cc by-nc",
    "cc_by_nc",
    "non_commercial_only",
    "non-commercial-only",
    "personal_noncommercial_only",
    "personal_non-commercial-only",
    "permission_required",
    "permission_review_required",
    "mixed_source_review_required",
    "declared_redistributable_check_required",
    "scope_to_confirm",
    "scope_pending",
    "license_scope_unconfirmed",
    "rights_unconfirmed",
    "not-confirmed",
    "not_confirmed",
)


USAGE_SCOPE = Path(__file__).resolve().parents[1] / "data" / "usage_scope.json"


def personal_scope_active(path: Path = USAGE_SCOPE) -> bool:
    """True only while the owner's usage-scope file says 'personal' and names who decided."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return data.get("scope") == "personal" and bool(data.get("confirmedBy"))


# Non-commercial wording is acceptable only for datasets explicitly marked personalUseOnly
# while data/usage_scope.json says 'personal' (e.g. the openAIP test-phase layer).
NONCOMMERCIAL_MARKERS = ("cc by-nc", "cc_by_nc", "non_commercial_only", "non-commercial-only")


def redistribution_block_reason(dataset: dict, personal_scope: bool = False) -> str | None:
    """Return a reason unless commercial redistribution is explicitly verified.

    With ``personal_scope`` a dataset explicitly marked ``personalUseOnly`` (and never
    marked commercial) passes the rights check; blocked-marker wording still blocks it.
    """
    text = " ".join(
        str(dataset.get(key, ""))
        for key in ("license", "licenseStatus", "status", "redistribution")
    ).lower()
    personal_ok = (personal_scope and dataset.get("personalUseOnly") is True
                   and dataset.get("commercialUseAllowed") is False)
    for marker in BLOCKED_MARKERS:
        if marker in text:
            if personal_ok and marker in NONCOMMERCIAL_MARKERS:
                continue
            return marker

    if dataset.get("commercialUseAllowed") is True:
        return None
    if personal_scope and dataset.get("personalUseOnly") is True and dataset.get("commercialUseAllowed") is False:
        return None
    license_status = str(dataset.get("licenseStatus", "")).strip().lower()
    if license_status in VERIFIED_LICENSE_STATUSES:
        return None
    if str(dataset.get("id", "")).strip() in FIRST_PARTY_DATASET_IDS:
        return None
    return "commercial_reuse_not_confirmed"
