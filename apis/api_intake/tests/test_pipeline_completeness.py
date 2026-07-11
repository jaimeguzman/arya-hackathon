"""Layer 6 — Completeness check tests (feature #36)."""

from datetime import date

from app.pipeline.completeness import (
    REQUIREMENTS_CHECKLIST,
    ChecklistItem,
    CompletenessGap,
    GapStatus,
    PacketSummary,
    check_completeness,
)


def _complete_packet() -> PacketSummary:
    return PacketSummary(
        patient_name="Margaret Chen",
        date_of_birth=date(1948, 3, 14),
        address="42 Oak Lane, Springfield, IL 62704",
        phone="217-555-0142",
        physician_orders_present=True,
        physician_orders_signed=True,
        face_to_face_note_present=True,
        insurance_payer="Medicare",
        insurance_member_id="1EG4-TE5-MK72",
        diagnosis_texts=("Osteoarthritis of right knee",),
        icd_codes=("M17.11",),
        homebound_status_documented=True,
        medications=("Lisinopril 20mg",),
    )


def test_checklist_covers_all_seven_required_items():
    assert set(REQUIREMENTS_CHECKLIST) == {
        ChecklistItem.DEMOGRAPHICS,
        ChecklistItem.SIGNED_PHYSICIAN_ORDERS,
        ChecklistItem.FACE_TO_FACE_DOCUMENTATION,
        ChecklistItem.INSURANCE_INFO,
        ChecklistItem.DIAGNOSIS_WITH_ICD,
        ChecklistItem.HOMEBOUND_STATUS,
        ChecklistItem.MEDICATION_LIST,
    }
    assert len(REQUIREMENTS_CHECKLIST) == 7


def test_complete_packet_yields_no_gaps():
    report = check_completeness(_complete_packet())
    assert report.is_complete
    assert report.gap_list == ()
    assert report.checklist == REQUIREMENTS_CHECKLIST


def test_missing_demographic_fields_each_become_a_gap():
    packet = PacketSummary(
        **{
            **_complete_packet().__dict__,
            "address": None,
            "phone": None,
        }
    )
    report = check_completeness(packet)
    demo_gaps = [
        g
        for g in report.gap_list
        if g.checklist_item is ChecklistItem.DEMOGRAPHICS
    ]
    assert {g.missing_item for g in demo_gaps} == {"address", "phone"}
    for gap in demo_gaps:
        assert gap.status is GapStatus.OPEN
        assert gap.attempts == 0
        assert gap.follow_up_action.startswith("Call the patient/family")


def test_unsigned_orders_flag_signature_not_orders():
    packet = PacketSummary(
        **{**_complete_packet().__dict__, "physician_orders_signed": False}
    )
    report = check_completeness(packet)
    (gap,) = [
        g
        for g in report.gap_list
        if g.checklist_item is ChecklistItem.SIGNED_PHYSICIAN_ORDERS
    ]
    assert gap.missing_item == "physician signature on orders"
    assert "signed" in gap.follow_up_action


def test_missing_orders_entirely_requests_orders_with_upload_link():
    packet = PacketSummary(
        **{
            **_complete_packet().__dict__,
            "physician_orders_present": False,
            "physician_orders_signed": False,
        }
    )
    report = check_completeness(packet)
    (gap,) = [
        g
        for g in report.gap_list
        if g.checklist_item is ChecklistItem.SIGNED_PHYSICIAN_ORDERS
    ]
    assert gap.missing_item == "physician orders"
    assert "upload link" in gap.follow_up_action


def test_diagnosis_without_icd_codes_asks_for_codes():
    packet = PacketSummary(
        **{**_complete_packet().__dict__, "icd_codes": ()}
    )
    report = check_completeness(packet)
    (gap,) = [
        g
        for g in report.gap_list
        if g.checklist_item is ChecklistItem.DIAGNOSIS_WITH_ICD
    ]
    assert "ICD-10" in gap.missing_item


def test_incomplete_packet_asserts_expected_gaps():
    """Feature step 3: incomplete packet — no F2F note, no insurance,
    no homebound documentation, no medications."""
    packet = PacketSummary(
        patient_name="Margaret Chen",
        date_of_birth=date(1948, 3, 14),
        address="42 Oak Lane, Springfield, IL 62704",
        phone="217-555-0142",
        physician_orders_present=True,
        physician_orders_signed=True,
        face_to_face_note_present=False,
        diagnosis_texts=("Osteoarthritis of right knee",),
        icd_codes=("M17.11",),
    )
    report = check_completeness(packet)
    assert not report.is_complete
    assert {(g.checklist_item, g.missing_item) for g in report.gap_list} == {
        (
            ChecklistItem.FACE_TO_FACE_DOCUMENTATION,
            "face-to-face encounter documentation",
        ),
        (ChecklistItem.INSURANCE_INFO, "insurance payer"),
        (ChecklistItem.INSURANCE_INFO, "insurance member ID"),
        (ChecklistItem.HOMEBOUND_STATUS, "homebound status documentation"),
        (ChecklistItem.MEDICATION_LIST, "medication list"),
    }
    # Every gap is an actionable Voice Agent task in gap_list row shape.
    for gap in report.gap_list:
        assert isinstance(gap, CompletenessGap)
        assert gap.follow_up_action.startswith("Call the ")
        assert gap.status is GapStatus.OPEN
        assert gap.attempts == 0


def test_empty_packet_flags_every_checklist_item():
    report = check_completeness(PacketSummary())
    flagged_items = {g.checklist_item for g in report.gap_list}
    assert flagged_items == set(REQUIREMENTS_CHECKLIST)
