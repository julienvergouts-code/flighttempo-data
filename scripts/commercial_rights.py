"""Shared fail-closed commercial reuse rules for downloadable datasets."""
from __future__ import annotations

FIRST_PARTY_DATASET_IDS = {"airline_profiles", "route_rules", "route_policy"}
VERIFIED_LICENSE_STATUSES = {
    "public_domain",
    "cc0_structured_data",
    "owner_authored_profile",
    "verified_open_license_commercial_reuse",
    "verified_exact_eaip_product_linked_to_open_license",
    "commercial_use_permitted_subject_to_ofma_gul",
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


def redistribution_block_reason(dataset: dict) -> str | None:
    """Return a reason unless commercial redistribution is explicitly verified."""
    text = " ".join(
        str(dataset.get(key, ""))
        for key in ("license", "licenseStatus", "status", "redistribution")
    ).lower()
    for marker in BLOCKED_MARKERS:
        if marker in text:
            return marker

    if dataset.get("commercialUseAllowed") is True:
        return None
    license_status = str(dataset.get("licenseStatus", "")).strip().lower()
    if license_status in VERIFIED_LICENSE_STATUSES:
        return None
    if str(dataset.get("id", "")).strip() in FIRST_PARTY_DATASET_IDS:
        return None
    return "commercial_reuse_not_confirmed"
