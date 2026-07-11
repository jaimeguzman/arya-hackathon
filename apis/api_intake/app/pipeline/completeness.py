"""Layer 6 — Completeness Check and Gap Identification.

Checks the assembled referral packet against the intake requirements
checklist from the spec: demographics complete, signed physician orders,
face-to-face documentation, insurance info, diagnosis + ICD codes,
homebound status, medication list.

Each missing item becomes a specific ``CompletenessGap`` row — the shape
of the ``gap_list`` table (missing item, follow-up action, status,
attempts) — with a concrete follow-up task for the Voice Agent. All
checks are deterministic code, never LLM-decided.

Spec: app_spec.txt <document_pipeline><layer number="6">.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


class ChecklistItem(str, Enum):
    DEMOGRAPHICS = "demographics"
    SIGNED_PHYSICIAN_ORDERS = "signed_physician_orders"
    FACE_TO_FACE_DOCUMENTATION = "face_to_face_documentation"
    INSURANCE_INFO = "insurance_info"
    DIAGNOSIS_WITH_ICD = "diagnosis_with_icd"
    HOMEBOUND_STATUS = "homebound_status"
    MEDICATION_LIST = "medication_list"


class GapStatus(str, Enum):
    OPEN = "open"


@dataclass(frozen=True)
class PacketSummary:
    """The completeness-checkable view of the whole referral packet,
    assembled from the Layer 4/5 outputs across all documents."""

    patient_name: str | None = None
    date_of_birth: date | None = None
    address: str | None = None
    phone: str | None = None
    physician_orders_present: bool = False
    physician_orders_signed: bool = False
    face_to_face_note_present: bool = False
    insurance_payer: str | None = None
    insurance_member_id: str | None = None
    diagnosis_texts: tuple[str, ...] = ()
    icd_codes: tuple[str, ...] = ()
    homebound_status_documented: bool = False
    medications: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompletenessGap:
    """One gap_list row: a specific missing item plus the follow-up task
    the Voice Agent must perform to close it."""

    checklist_item: ChecklistItem
    missing_item: str
    follow_up_action: str
    status: GapStatus = GapStatus.OPEN
    attempts: int = 0


@dataclass(frozen=True)
class CompletenessReport:
    checklist: tuple[ChecklistItem, ...]
    gap_list: tuple[CompletenessGap, ...]

    @property
    def is_complete(self) -> bool:
        return not self.gap_list


REQUIREMENTS_CHECKLIST: tuple[ChecklistItem, ...] = tuple(ChecklistItem)

# The demographic fields that must all be present for the demographics
# checklist item to pass, with the Voice Agent follow-up for each.
_DEMOGRAPHIC_FIELDS: tuple[tuple[str, str], ...] = (
    ("patient_name", "confirm the patient's full name"),
    ("date_of_birth", "confirm the patient's date of birth"),
    ("address", "confirm the patient's home address"),
    ("phone", "confirm a contact phone number"),
)


def _demographics_gaps(packet: PacketSummary) -> list[CompletenessGap]:
    gaps: list[CompletenessGap] = []
    for field_name, task in _DEMOGRAPHIC_FIELDS:
        if not getattr(packet, field_name):
            gaps.append(
                CompletenessGap(
                    checklist_item=ChecklistItem.DEMOGRAPHICS,
                    missing_item=field_name,
                    follow_up_action=(
                        f"Call the patient/family to {task}."
                    ),
                )
            )
    return gaps


def check_completeness(packet: PacketSummary) -> CompletenessReport:
    """Check the packet against the full requirements checklist and turn
    every missing item into a gap_list row for the Voice Agent."""
    gaps: list[CompletenessGap] = []

    gaps.extend(_demographics_gaps(packet))

    if not packet.physician_orders_present:
        gaps.append(
            CompletenessGap(
                checklist_item=ChecklistItem.SIGNED_PHYSICIAN_ORDERS,
                missing_item="physician orders",
                follow_up_action=(
                    "Call the referring provider to request the physician "
                    "orders and send a document upload link."
                ),
            )
        )
    elif not packet.physician_orders_signed:
        gaps.append(
            CompletenessGap(
                checklist_item=ChecklistItem.SIGNED_PHYSICIAN_ORDERS,
                missing_item="physician signature on orders",
                follow_up_action=(
                    "Call the referring provider to obtain the signed "
                    "physician orders."
                ),
            )
        )

    if not packet.face_to_face_note_present:
        gaps.append(
            CompletenessGap(
                checklist_item=ChecklistItem.FACE_TO_FACE_DOCUMENTATION,
                missing_item="face-to-face encounter documentation",
                follow_up_action=(
                    "Call the referring provider to request the face-to-face "
                    "encounter note and send a document upload link."
                ),
            )
        )

    if not packet.insurance_payer:
        gaps.append(
            CompletenessGap(
                checklist_item=ChecklistItem.INSURANCE_INFO,
                missing_item="insurance payer",
                follow_up_action=(
                    "Call the patient/family to confirm the insurance payer."
                ),
            )
        )
    if not packet.insurance_member_id:
        gaps.append(
            CompletenessGap(
                checklist_item=ChecklistItem.INSURANCE_INFO,
                missing_item="insurance member ID",
                follow_up_action=(
                    "Call the patient/family (or provider) to verify the "
                    "insurance member ID."
                ),
            )
        )

    if not packet.diagnosis_texts and not packet.icd_codes:
        gaps.append(
            CompletenessGap(
                checklist_item=ChecklistItem.DIAGNOSIS_WITH_ICD,
                missing_item="diagnosis and ICD-10 codes",
                follow_up_action=(
                    "Call the referring provider to obtain the diagnosis "
                    "and ICD-10 codes."
                ),
            )
        )
    elif not packet.icd_codes:
        gaps.append(
            CompletenessGap(
                checklist_item=ChecklistItem.DIAGNOSIS_WITH_ICD,
                missing_item="ICD-10 codes for the documented diagnosis",
                follow_up_action=(
                    "Call the referring provider to confirm the ICD-10 "
                    "codes for the documented diagnosis."
                ),
            )
        )
    elif not packet.diagnosis_texts:
        gaps.append(
            CompletenessGap(
                checklist_item=ChecklistItem.DIAGNOSIS_WITH_ICD,
                missing_item="diagnosis description for the ICD-10 codes",
                follow_up_action=(
                    "Call the referring provider to confirm the diagnosis "
                    "behind the submitted ICD-10 codes."
                ),
            )
        )

    if not packet.homebound_status_documented:
        gaps.append(
            CompletenessGap(
                checklist_item=ChecklistItem.HOMEBOUND_STATUS,
                missing_item="homebound status documentation",
                follow_up_action=(
                    "Call the referring provider to obtain homebound status "
                    "documentation."
                ),
            )
        )

    if not packet.medications:
        gaps.append(
            CompletenessGap(
                checklist_item=ChecklistItem.MEDICATION_LIST,
                missing_item="medication list",
                follow_up_action=(
                    "Call the referring provider to request the current "
                    "medication list."
                ),
            )
        )

    return CompletenessReport(
        checklist=REQUIREMENTS_CHECKLIST,
        gap_list=tuple(gaps),
    )
