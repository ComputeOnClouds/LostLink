"""Regression coverage for the UI-workflow backend contracts."""

from api import s3urls
from pipeline.impl.ddb_mapping import ddb_to_item, item_to_ddb
from pipeline.models import Item, ItemType, VectorMap, INACTIVE_STATUSES


def test_item_round_trip_preserves_description_provenance_and_revision():
    item = Item(
        item_id="lost-1",
        item_type=ItemType.LOST,
        organisation_id="individual",
        owner_id="user-1",
        description="black wallet",
        photo_key="uploads/user-1/lost-1/photo.jpg",
        vectors=VectorMap(text=[0.1, 0.2]),
        description_source="ai_edited",
        description_photo_key="uploads/user-1/lost-1/photo.jpg",
        description_generated_at="2026-10-04T12:00:00+00:00",
        revision=7,
    )

    restored = ddb_to_item(item_to_ddb(item))

    assert restored.description_source == "ai_edited"
    assert restored.description_photo_key == item.photo_key
    assert restored.description_generated_at == "2026-10-04T12:00:00+00:00"
    assert restored.revision == 7
    assert restored.vectors.text == [0.1, 0.2]


def test_legacy_item_defaults_to_unknown_provenance_and_zero_revision():
    restored = ddb_to_item({
        "itemId": "lost-legacy",
        "itemType": "lost",
        "organisationId": "individual",
        "ownerId": "user-1",
        "status": "matched",
    })
    assert restored.description_source == "unknown"
    assert restored.revision == 0


def test_pdf_evidence_keys_keep_the_pdf_extension():
    key = s3urls.new_photo_key("evidence/user-1", "upload", "application/pdf")
    assert key.endswith(".pdf")


def test_reserved_found_items_are_excluded_from_matching():
    assert "reserved" in INACTIVE_STATUSES
