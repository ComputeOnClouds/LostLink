"""Demo regressions: real low-level transaction shape and claim availability guards."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError
from api import claims_handler as ch
from api import claim_state as cs
from api.auth import Principal


def test_approval_atomically_reserves_and_preserves_revision(monkeypatch):
    claim = dict(claimId='c', candidateItemId='f', state='submitted', revision=3, messages=[])
    monkeypatch.setattr(ch, '_load_org_claim', lambda *args: claim)
    transaction = Mock()
    monkeypatch.setattr(ch, '_transact_claim_and_item', transaction)
    monkeypatch.setattr(ch, '_notify_claimant', Mock())
    result = ch._staff_transition(Principal('s', 's@x', ['Staff'], 'org'), 'c', 'approve', {'revision': 3, 'collectionInstructions': 'Collect at desk 1'})
    assert json.loads(result['body'])['state'] == cs.STATE_RESERVED
    assert transaction.call_args.kwargs['expected_revision'] == 3
    assert transaction.call_args.kwargs['new_state'] == cs.STATE_RESERVED


def test_transaction_binds_reservation_to_claim_with_low_level_types(monkeypatch):
    client = Mock()
    monkeypatch.setattr(ch, '_ddb_client', client)
    ch._transact_claim_and_item(claim_id='c', candidate_item_id='f', expected_state='submitted',
        new_state='reserved', messages=[], expected_revision=3, next_revision=4, updated_at='now')
    updates = client.transact_write_items.call_args.kwargs['TransactItems']
    assert len(updates) == 2
    item = updates[1]['Update']
    assert item['ExpressionAttributeValues'][':claim'] == {'S': 'c'}
    assert 'reservedForClaim = :claim' in item['ConditionExpression']
    assert updates[0]['Update']['ExpressionAttributeValues'][':er'] == {'N': '3'}


def test_competing_reservation_returns_actionable_conflict(monkeypatch):
    monkeypatch.setattr(ch, '_load_org_claim', lambda *args: dict(candidateItemId='f', state='submitted', messages=[]))
    def conflict(**kwargs):
        raise ClientError({'Error': {'Code': 'TransactionCanceledException'}}, 'TransactWriteItems')
    monkeypatch.setattr(ch, '_transact_claim_and_item', conflict)
    result = ch._staff_transition(Principal('s', 's@x', ['Staff'], 'org'), 'c', 'approve', {'collectionInstructions': 'Collect at desk 1'})
    assert result['statusCode'] == 409
    assert 'reserved for another claim' in result['body']


@pytest.mark.parametrize('status,active', [('reserved', True), ('closed', True), ('available', False)])
def test_stale_match_cannot_create_claim(monkeypatch, status, active):
    items = Mock()
    items.get_item.side_effect = [dict(Item=dict(ownerId='u', itemType='lost')), dict(Item=dict(status=status))]
    monkeypatch.setattr(ch, '_items', lambda: items)
    matches = Mock()
    matches.get_item.return_value = dict(Item=dict(active=active, organisationId='org'))
    monkeypatch.setattr(ch, '_matches', lambda: matches)
    from api.auth import AuthError
    try:
        result = ch._create_claim(Principal('u', 'u@x', ['Individual'], None),
            dict(queryItemId='l', candidateItemId='f', evidenceText='proof'))
        assert result['statusCode'] == 409
    except AuthError as exc:
        assert exc.status == 404


def test_duplicate_legacy_claim_is_rejected(monkeypatch):
    items = Mock()
    items.get_item.side_effect = [dict(Item=dict(ownerId='u', itemType='lost')), dict(Item=dict(status='available'))]
    monkeypatch.setattr(ch, '_items', lambda: items)
    matches = Mock()
    matches.get_item.return_value = dict(Item=dict(organisationId='org'))
    monkeypatch.setattr(ch, '_matches', lambda: matches)
    claims = Mock()
    claims.query.return_value = dict(Items=[dict(queryItemId='l', candidateItemId='f', state='submitted')])
    monkeypatch.setattr(ch, '_claims', lambda: claims)
    result = ch._create_claim(Principal('u', 'u@x', ['Individual'], None), dict(queryItemId='l', candidateItemId='f', evidenceText='proof'))
    assert result['statusCode'] == 409
    claims.put_item.assert_not_called()
