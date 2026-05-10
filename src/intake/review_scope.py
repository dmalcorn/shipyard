"""ReviewScope — identity for an epic-end or batch-mid review.

A small dataclass that captures both the epic and (optional) batch
identity of a review, plus formatting helpers used to derive
filenames, prose labels, and artifact paths.

The same set of pipeline nodes (review, sieve, architect, fix, CI,
commit) is reused for both epic-end reviews and mid-epic batch
reviews; ``ReviewScope`` is what lets a single helper render
``epic-6-...`` vs ``epic-6-batch-2-...`` artifacts off a shared
template constant.

This module has no graph dependencies — it is safe to import from
any layer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

EPIC_REVIEWS_DIR = "epic-reviews"


def reviews_path(filename: str, working_dir: str | None = None) -> str:
    """Resolve a filename to a full path under the epic-reviews directory.

    Used by both :class:`ReviewScope.artifact_path` and the epic-graph
    nodes that write review artifacts. Lives here so review-scope
    consumers don't have to import from the graph module.
    """
    reviews_dir = os.path.join(working_dir, EPIC_REVIEWS_DIR) if working_dir else EPIC_REVIEWS_DIR
    return os.path.join(reviews_dir, filename)


@dataclass(frozen=True)
class ReviewScope:
    """Identity for one review pass (epic-end or mid-epic batch).

    ``batch_num=None`` means the scope is the epic-end review (the
    legacy behavior). ``batch_num >= 1`` means the N-th mid-epic
    batch review of the current epic.
    """

    epic_num: str
    batch_num: int | None = None

    @property
    def is_batch(self) -> bool:
        """True when this scope refers to a mid-epic batch review."""
        return self.batch_num is not None

    @property
    def label(self) -> str:
        """Filename-safe label, e.g. ``epic-6`` or ``epic-6-batch-2``."""
        if self.batch_num is None:
            return f"epic-{self.epic_num}"
        return f"epic-{self.epic_num}-batch-{self.batch_num}"

    @property
    def prose_label(self) -> str:
        """Human-readable label for prompts, e.g. ``Epic 6`` or ``Epic 6 batch 2``."""
        if self.batch_num is None:
            return f"Epic {self.epic_num}"
        return f"Epic {self.epic_num} batch {self.batch_num}"

    def artifact_path(self, template: str, working_dir: str | None = None) -> str:
        """Resolve a per-scope artifact path under ``epic-reviews/``.

        Args:
            template: Filename template with a ``{scope}`` placeholder,
                e.g. ``"{scope}-fix-plan.md"``.
            working_dir: Optional target working directory; when given,
                the returned path is rooted there. When None, the path
                is relative.

        Returns:
            Full path string suitable for ``open()``.
        """
        filename = template.format(scope=self.label)
        return reviews_path(filename, working_dir=working_dir)
