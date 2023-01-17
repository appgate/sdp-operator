from unittest.mock import patch

from attr import attrib, attrs

from appgate.syncer.git import (
    github_checkout_branch,
    PullRequestLike,
    PullRequestHeadLike,
    BranchOp,
)


@attrs
class TestPRHead(PullRequestHeadLike):
    _ref: str = attrib()

    @property
    def ref(self) -> str:
        return self._ref


@attrs
class TestPR(PullRequestLike):
    _number: int = attrib()
    _title: str = attrib()
    _head: TestPRHead = attrib()

    @property
    def number(self) -> int:
        return self._number

    @property
    def title(self) -> str:
        return self._title

    @property
    def head(self) -> TestPRHead:
        return self._head


def test_checkout_branch() -> None:
    with patch("appgate.syncer.git.generate_branch_name") as generate_branch_name:
        generate_branch_name.return_value = "my-new-branch"
        open_pr = TestPR(666, "already-open-pr", TestPRHead(ref="branch-in-pr"))
        assert github_checkout_branch(None, None) == (
            "my-new-branch",
            BranchOp.CREATE_AND_CHECKOUT,
        )
        assert github_checkout_branch("already-created-branch", None) == (
            "already-created-branch",
            BranchOp.NOP,
        )
        assert github_checkout_branch(None, open_pr) == (
            "branch-in-pr",
            BranchOp.CHECKOUT,
        )
        # If we have an open pr always use it
        assert github_checkout_branch("some-other-pr", open_pr) == (
            "branch-in-pr",
            BranchOp.CHECKOUT,
        )
        assert github_checkout_branch("some-other-pr", open_pr) == (
            "branch-in-pr",
            BranchOp.CHECKOUT,
        )
        assert github_checkout_branch(None, open_pr) == (
            "branch-in-pr",
            BranchOp.CHECKOUT,
        )
        # Create a new branch if we don't have a current one
        assert github_checkout_branch(None, None) == (
            "my-new-branch",
            BranchOp.CREATE_AND_CHECKOUT,
        )
