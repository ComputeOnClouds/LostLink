"""ItemRepository implementation backed by DynamoDB (Task 3).

Table names and GSI names come from environment variables so the same code runs in any
Lambda that sets them. See RATIONALE ADR-012 for the key design.
"""

from __future__ import annotations

import os

from ..interfaces import ItemRepository
from ..models import Item, MatchResult, OrgScope
from .ddb_mapping import item_to_ddb, ddb_to_item, match_to_ddb

# GSI names — must match DataStack constants.
GSI_BY_OWNER = "by-owner"
GSI_BY_ORG_TYPE = "by-org-type"
GSI_BY_TYPE = "by-type"


class DynamoItemRepository(ItemRepository):
    """DynamoDB-backed persistence for items and matches.

    Env vars:
        ITEMS_TABLE    - name of the Items table (required for item ops)
        MATCHES_TABLE  - name of the Matches table (required for save_match)
    """

    def __init__(self, dynamodb_resource=None) -> None:
        # Lazy import so the pure pipeline package can be imported without boto3.
        if dynamodb_resource is None:
            import boto3

            dynamodb_resource = boto3.resource("dynamodb")
        self._ddb = dynamodb_resource
        self._items_table_name = os.environ.get("ITEMS_TABLE")
        self._matches_table_name = os.environ.get("MATCHES_TABLE")

    @property
    def _items(self):
        if not self._items_table_name:
            raise RuntimeError("ITEMS_TABLE env var is not set")
        return self._ddb.Table(self._items_table_name)

    @property
    def _matches(self):
        if not self._matches_table_name:
            raise RuntimeError("MATCHES_TABLE env var is not set")
        return self._ddb.Table(self._matches_table_name)

    def get(self, item_id: str) -> Item:
        resp = self._items.get_item(Key={"itemId": item_id})
        if "Item" not in resp:
            raise KeyError(f"Item not found: {item_id}")
        return ddb_to_item(resp["Item"])

    def save(self, item: Item) -> None:
        # Preserve the original createdAt if the item already exists (keeps GSI sort
        # stable across reprocessing); otherwise a fresh timestamp is generated.
        existing = self._items.get_item(Key={"itemId": item.item_id}).get("Item")
        created_at = existing.get("createdAt") if existing else None
        self._items.put_item(Item=item_to_ddb(item, created_at=created_at))

    def list_candidates(self, query_item: Item, org_scope: OrgScope) -> list[Item]:
        """Return opposing-type items within the authorised org scope.

        Cross-org (all_authorised): query the by-type GSI for every opposing-type item.
        Scoped: query the by-org-type GSI once per authorised org id.
        """
        opposing = query_item.item_type.opposing
        results: list[Item] = []

        if org_scope.all_authorised:
            resp = self._items.query(
                IndexName=GSI_BY_TYPE,
                KeyConditionExpression="itemType = :t",
                ExpressionAttributeValues={":t": opposing.value},
            )
            results.extend(ddb_to_item(i) for i in resp.get("Items", []))
            # Paginate defensively (prototype volumes are small but be correct).
            while "LastEvaluatedKey" in resp:
                resp = self._items.query(
                    IndexName=GSI_BY_TYPE,
                    KeyConditionExpression="itemType = :t",
                    ExpressionAttributeValues={":t": opposing.value},
                    ExclusiveStartKey=resp["LastEvaluatedKey"],
                )
                results.extend(ddb_to_item(i) for i in resp.get("Items", []))
        else:
            for org_id in org_scope.org_ids or []:
                org_type = f"{org_id}#{opposing.value}"
                resp = self._items.query(
                    IndexName=GSI_BY_ORG_TYPE,
                    KeyConditionExpression="orgType = :ot",
                    ExpressionAttributeValues={":ot": org_type},
                )
                results.extend(ddb_to_item(i) for i in resp.get("Items", []))

        # Never compare an item against itself.
        return [i for i in results if i.item_id != query_item.item_id]

    def save_match(self, match: MatchResult) -> None:
        self._matches.put_item(Item=match_to_ddb(match))
