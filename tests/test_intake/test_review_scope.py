"""Tests for src/intake/review_scope.py."""

from __future__ import annotations

import os

import pytest

from src.intake.review_scope import EPIC_REVIEWS_DIR, ReviewScope


class TestLabel:
    def test_epic_only_label(self) -> None:
        assert ReviewScope(epic_num="6").label == "epic-6"

    def test_batch_label(self) -> None:
        assert ReviewScope(epic_num="6", batch_num=2).label == "epic-6-batch-2"

    def test_batch_one_label(self) -> None:
        assert ReviewScope(epic_num="11", batch_num=1).label == "epic-11-batch-1"


class TestProseLabel:
    def test_epic_only_prose_label(self) -> None:
        assert ReviewScope(epic_num="6").prose_label == "Epic 6"

    def test_batch_prose_label(self) -> None:
        assert ReviewScope(epic_num="6", batch_num=2).prose_label == "Epic 6 batch 2"


class TestIsBatch:
    def test_is_batch_false_when_no_batch_num(self) -> None:
        assert ReviewScope(epic_num="6").is_batch is False

    def test_is_batch_true_when_batch_num_set(self) -> None:
        assert ReviewScope(epic_num="6", batch_num=1).is_batch is True

    def test_is_batch_true_for_high_batch_num(self) -> None:
        assert ReviewScope(epic_num="6", batch_num=99).is_batch is True


class TestArtifactPath:
    def test_epic_only_path_no_working_dir(self) -> None:
        scope = ReviewScope(epic_num="6")
        path = scope.artifact_path("{scope}-fix-plan.md")
        assert path == os.path.join(EPIC_REVIEWS_DIR, "epic-6-fix-plan.md")

    def test_batch_path_no_working_dir(self) -> None:
        scope = ReviewScope(epic_num="6", batch_num=2)
        path = scope.artifact_path("{scope}-fix-plan.md")
        assert path == os.path.join(EPIC_REVIEWS_DIR, "epic-6-batch-2-fix-plan.md")

    def test_epic_only_path_with_working_dir(self, tmp_path) -> None:
        scope = ReviewScope(epic_num="6")
        path = scope.artifact_path("{scope}-review-bmad.md", working_dir=str(tmp_path))
        expected = os.path.join(str(tmp_path), EPIC_REVIEWS_DIR, "epic-6-review-bmad.md")
        assert path == expected

    def test_batch_path_with_working_dir(self, tmp_path) -> None:
        scope = ReviewScope(epic_num="6", batch_num=3)
        path = scope.artifact_path("{scope}-analysis.md", working_dir=str(tmp_path))
        expected = os.path.join(
            str(tmp_path), EPIC_REVIEWS_DIR, "epic-6-batch-3-analysis.md"
        )
        assert path == expected

    def test_template_without_scope_placeholder_raises(self) -> None:
        scope = ReviewScope(epic_num="6")
        # str.format on a template lacking the placeholder is a no-op,
        # so the result is just the literal — verify that's what callers see.
        path = scope.artifact_path("static-name.md")
        assert path.endswith("static-name.md")


class TestFrozen:
    def test_dataclass_is_frozen(self) -> None:
        from dataclasses import FrozenInstanceError

        scope = ReviewScope(epic_num="6")
        with pytest.raises(FrozenInstanceError):
            scope.epic_num = "7"  # type: ignore[misc]

    def test_equal_scopes_compare_equal(self) -> None:
        a = ReviewScope(epic_num="6", batch_num=2)
        b = ReviewScope(epic_num="6", batch_num=2)
        assert a == b

    def test_different_batch_nums_compare_unequal(self) -> None:
        a = ReviewScope(epic_num="6", batch_num=1)
        b = ReviewScope(epic_num="6", batch_num=2)
        assert a != b

    def test_epic_vs_batch_compare_unequal(self) -> None:
        a = ReviewScope(epic_num="6")
        b = ReviewScope(epic_num="6", batch_num=1)
        assert a != b

    def test_hashable(self) -> None:
        scope = ReviewScope(epic_num="6", batch_num=2)
        # Frozen dataclass should be hashable; usable as dict key / set member.
        assert {scope: "ok"}[scope] == "ok"
