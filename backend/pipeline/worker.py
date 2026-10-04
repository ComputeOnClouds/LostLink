"""MatchWorker — orchestrates the pipeline stages for one match job.

Depends only on the stage interfaces (obtained from the factory). The full
orchestration is filled in across Tasks 7-10; the skeleton here fixes the shape and
the wiring so those tasks slot in without changing the worker's dependencies.

See docs/ARCHITECTURE.md section 2.1 for the orchestration sequence.
"""

from __future__ import annotations

from .interfaces import (
    DescriptionSource,
    Embedder,
    CandidateRetriever,
    Scorer,
    ProfileSelector,
    Notifier,
    ItemRepository,
)
from .models import (
    OrgScope,
    Item,
    ItemType,
    STATUS_MATCHED,
    STATUS_NO_MATCH,
    INACTIVE_STATUSES,
)
from . import factory
from .impl.ddb_mapping import now_iso


class MatchWorker:
    def __init__(
        self,
        repository: ItemRepository,
        description_source: DescriptionSource,
        embedder: Embedder,
        retriever: CandidateRetriever,
        profile_selector: ProfileSelector,
        scorer: Scorer,
        notifier: Notifier,
    ) -> None:
        self.repository = repository
        self.description_source = description_source
        self.embedder = embedder
        self.retriever = retriever
        self.profile_selector = profile_selector
        self.scorer = scorer
        self.notifier = notifier

    @classmethod
    def from_env(cls) -> "MatchWorker":
        """Build a worker with implementations selected by environment variables."""
        repository = factory.make_repository()
        return cls(
            repository=repository,
            description_source=factory.make_description_source(),
            embedder=factory.make_embedder(),
            retriever=factory.make_retriever(repository),
            profile_selector=factory.make_profile_selector(),
            scorer=factory.make_scorer(),
            notifier=factory.make_notifier(),
        )

    def handle(self, job: dict) -> None:
        """Process one match job: {"itemId": ..., "type": "lost"|"found"}.

        1. Load the item.
        2. Ensure it has a description (generate from photo if needed) and embeddings.
        3. Retrieve opposing-type candidates across authorised organisations.
        4. Score each pair; persist matches at/above the profile threshold.
        5. Notify the report owner for new above-threshold matches (Task 10 dedup).

        Withdrawn/closed items are skipped. See docs/ARCHITECTURE.md section 2.1.
        """
        item_id = job.get("itemId")
        if not item_id:
            print("job missing itemId; skipping")
            return

        # The referenced item may have been deleted between enqueue and processing (e.g.
        # withdrawn + purged). Treat as nothing-to-do rather than failing the message.
        try:
            item = self.repository.get(item_id)
        except KeyError:
            print(f"{item_id} no longer exists; skipping")
            return

        if item.status in INACTIVE_STATUSES:
            print(f"{item_id} is {item.status}; skipping match")
            return

        item = self._ensure_enriched(item)

        # Skip if we still have no text vector to compare (e.g. no description/photo).
        if not item.vectors.has_text():
            print(f"{item_id} has no text vector after enrichment; skipping")
            return

        # Cross-organisation matching: search every authorised org's opposing inventory.
        candidates = self.retriever.retrieve(item, OrgScope(all_authorised=True))

        # Mark the previous result set stale before rebuilding it. Rows remain in place
        # so notification dedup survives edits and future rescoring.
        if item.item_type is ItemType.LOST and hasattr(self.repository, "deactivate_matches_for_query"):
            self.repository.deactivate_matches_for_query(item.item_id)

        match_count = 0
        for candidate in candidates:
            if item.item_type is ItemType.FOUND and hasattr(self.repository, "deactivate_match"):
                self.repository.deactivate_match(candidate.item_id, item.item_id)
            if candidate.status in INACTIVE_STATUSES:
                continue
            if not candidate.vectors.has_text():
                # Candidate not yet enriched; it will match when its own job runs.
                continue

            profile = self.profile_selector.select(item, candidate)
            result = self.scorer.score(item, candidate, profile.weights)
            result.profile_name = profile.name

            if result.score >= profile.threshold:
                match_count += 1
                # Orient the match so the query is always the lost report and the
                # candidate the found item, regardless of which side triggered the job.
                oriented = self._orient(item, candidate, result)
                self.repository.save_match(oriented)
                self._maybe_notify(oriented)
                # Mark the LOST side of the pair as matched. When a LOST report triggered
                # the job this is itself; when a FOUND item triggered, this flips the
                # affected lost report(s) so their owners see the match too.
                self._mark_report_matched(oriented.query_item_id, item)

        # Set the triggering LOST report's final status (matched / no_match). Found items
        # keep their own staff/claims-driven status (available/reserved/closed).
        if item.item_type is ItemType.LOST:
            new_status = STATUS_MATCHED if match_count > 0 else STATUS_NO_MATCH
            if item.status != new_status:
                item.status = new_status
                self._save_derived(item)
            print(f"{item_id}: {match_count} match(es) -> status {new_status}")

    # ---- helpers -------------------------------------------------------------------

    def _mark_report_matched(self, lost_item_id: str, triggering_item: Item) -> None:
        """Flip a lost report's status to 'matched'.

        If the lost report is the item that triggered this job, it's updated by the
        caller afterwards. If a FOUND item triggered the job, load the affected lost
        report and set it to matched so its owner sees the result immediately.
        """
        if triggering_item.item_type is ItemType.LOST and lost_item_id == triggering_item.item_id:
            return  # handled by the caller's final status update
        try:
            lost = self.repository.get(lost_item_id)
        except KeyError:
            return
        if lost.status not in INACTIVE_STATUSES and lost.status != STATUS_MATCHED:
            lost.status = STATUS_MATCHED
            self._save_derived(lost)

    def _ensure_enriched(self, item: Item) -> Item:
        """Generate a description from a photo if needed, and cache embeddings."""
        changed = False

        if not item.description:
            generated = self.description_source.describe(item)
            if generated:
                item.description = generated
                item.description_source = "ai"
                item.description_photo_key = item.photo_key
                item.description_generated_at = now_iso()
                changed = True

        if not item.vectors.has_text() and item.description:
            item.vectors = self.embedder.embed(item)
            changed = True

        if changed:
            if not self._save_derived(item):
                # A newer edit won while this job was doing model work. Continue only
                # with the new row; never write the stale enrichment over it.
                return self.repository.get(item.item_id)
        return item

    def _save_derived(self, item: Item) -> bool:
        if hasattr(self.repository, "save_if_revision"):
            return self.repository.save_if_revision(item, item.revision)
        self.repository.save(item)
        return True

    @staticmethod
    def _orient(query: Item, candidate: Item, result):
        """Ensure MatchResult always reads query=lost report, candidate=found item."""
        from .models import ItemType, MatchResult

        if query.item_type is ItemType.LOST:
            lost, found = query, candidate
        else:
            lost, found = candidate, query
        return MatchResult(
            query_item_id=lost.item_id,
            candidate_item_id=found.item_id,
            organisation_id=found.organisation_id,
            score=result.score,
            profile_name=result.profile_name,
            breakdown=result.breakdown,
        )

    def _maybe_notify(self, match) -> None:
        """Notify the lost-report owner. Per-pair dedup + delivery live in the Notifier."""
        try:
            lost = self.repository.get(match.query_item_id)
        except Exception as e:  # noqa: BLE001
            print(f"could not load report {match.query_item_id} for notify: {e!r}")
            return
        # Prefer the owner's email (set at creation); fall back to the id.
        recipient = lost.owner_email or lost.owner_id
        self.notifier.notify(recipient, match)
