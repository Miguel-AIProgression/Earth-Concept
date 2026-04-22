"""Tests voor dedup-logica in process_pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock

import process_pipeline


def _row(
    row_id: str,
    parse_status: str,
    customer_ref: str | None,
    account_id: str | None,
    exact_order_id: str | None = None,
):
    return {
        "id": row_id,
        "parse_status": parse_status,
        "exact_order_id": exact_order_id,
        "parsed_data": {
            "customer_reference": customer_ref,
            "matched_customer": {"id": account_id} if account_id else None,
        },
    }


def _mock_sb_with_created(existing_rows):
    sb = MagicMock()
    chain = (
        sb.table.return_value.select.return_value
        .eq.return_value
        .neq.return_value
        .execute.return_value
    )
    chain.data = existing_rows
    return sb


def test_duplicate_detectie_zelfde_po_zelfde_klant():
    existing = [_row("row-oud", "created", "PO-123", "acc-1", exact_order_id="ex-9688")]
    sb = _mock_sb_with_created(existing)

    current = _row("row-nieuw", "approved", "PO-123", "acc-1")
    dup = process_pipeline.find_duplicate_created_order(sb, current)

    assert dup is not None
    assert dup["exact_order_id"] == "ex-9688"


def test_duplicate_geen_match_bij_andere_klant():
    existing = [_row("row-oud", "created", "PO-123", "acc-2", exact_order_id="ex-1")]
    sb = _mock_sb_with_created(existing)

    current = _row("row-nieuw", "approved", "PO-123", "acc-1")
    assert process_pipeline.find_duplicate_created_order(sb, current) is None


def test_duplicate_geen_match_bij_andere_po():
    existing = [_row("row-oud", "created", "PO-999", "acc-1", exact_order_id="ex-1")]
    sb = _mock_sb_with_created(existing)

    current = _row("row-nieuw", "approved", "PO-123", "acc-1")
    assert process_pipeline.find_duplicate_created_order(sb, current) is None


def test_duplicate_zonder_po_skipt_check():
    """Zonder customer_reference geen dedup -- dan valt er ook niks te matchen."""
    sb = _mock_sb_with_created([_row("row-oud", "created", "PO-1", "acc-1")])
    current = _row("row-nieuw", "approved", None, "acc-1")
    assert process_pipeline.find_duplicate_created_order(sb, current) is None


def test_duplicate_case_insensitive_op_po():
    existing = [_row("row-oud", "created", "po-abc", "acc-1", exact_order_id="ex-1")]
    sb = _mock_sb_with_created(existing)

    current = _row("row-nieuw", "approved", "PO-ABC", "acc-1")
    assert process_pipeline.find_duplicate_created_order(sb, current) is not None
