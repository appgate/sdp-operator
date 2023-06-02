from unittest.mock import patch
from unittest import TestCase

from attr import attrib, attrs
import tempfile
from pathlib import Path
from appgate.syncer.git import (
    github_checkout_branch,
    PullRequestLike,
    BranchOp,
    gitlab_checkout_branch,
    clone_repo_url,
)
from appgate.types import (
    APISpec,
    GitOperatorContext,
)


@attrs
class TestPR(PullRequestLike):
    __test__ = False
    _number: int = attrib()
    _title: str = attrib()
    _source: str = attrib()

    @property
    def number(self) -> int:
        return self._number

    @property
    def title(self) -> str:
        return self._title

    @property
    def source(self) -> str:
        return self._source


def test_github_checkout_branch() -> None:
    with patch("appgate.syncer.git.generate_branch_name") as generate_branch_name:
        generate_branch_name.return_value = "my-new-branch"
        previous_pr = TestPR(333, "previous-pr", "branch-in-previous-pr")
        open_pr = TestPR(666, "already-open-pr", "branch-in-pr")
        assert github_checkout_branch(None, None, None) == (
            "my-new-branch",
            BranchOp.CREATE_AND_CHECKOUT,
        )
        assert github_checkout_branch("already-created-branch", None, None) == (
            "already-created-branch",
            BranchOp.NOP,
        )
        assert github_checkout_branch("already-created-branch", previous_pr, None) == (
            "my-new-branch",
            BranchOp.CREATE_AND_CHECKOUT,
        )
        assert github_checkout_branch(None, None, open_pr) == (
            "branch-in-pr",
            BranchOp.CHECKOUT,
        )
        # If we have an open pr always use it
        assert github_checkout_branch("some-other-pr", None, open_pr) == (
            "branch-in-pr",
            BranchOp.CHECKOUT,
        )
        assert github_checkout_branch("some-other-pr", None, open_pr) == (
            "branch-in-pr",
            BranchOp.CHECKOUT,
        )
        assert github_checkout_branch(None, None, open_pr) == (
            "branch-in-pr",
            BranchOp.CHECKOUT,
        )
        # Create a new branch if we don't have a current one
        assert github_checkout_branch(None, None, None) == (
            "my-new-branch",
            BranchOp.CREATE_AND_CHECKOUT,
        )


def test_gitlab_checkout_branch() -> None:
    with patch("appgate.syncer.git.generate_branch_name") as generate_branch_name:
        generate_branch_name.return_value = "my-new-branch"
        previous_pr = TestPR(333, "previous-pr", "branch-in-previous-pr")
        open_pr = TestPR(666, "already-open-pr", "branch-in-pr")
        assert gitlab_checkout_branch(None, None, None) == (
            "my-new-branch",
            BranchOp.CREATE_AND_CHECKOUT,
        )
        assert gitlab_checkout_branch("already-created-branch", None, None) == (
            "already-created-branch",
            BranchOp.NOP,
        )
        assert gitlab_checkout_branch("already-created-branch", previous_pr, None) == (
            "my-new-branch",
            BranchOp.CREATE_AND_CHECKOUT,
        )
        assert gitlab_checkout_branch(None, None, open_pr) == (
            "branch-in-pr",
            BranchOp.CHECKOUT,
        )
        # If we have an open pr always use it
        assert gitlab_checkout_branch("some-other-pr", None, open_pr) == (
            "branch-in-pr",
            BranchOp.CHECKOUT,
        )
        assert gitlab_checkout_branch("some-other-pr", None, open_pr) == (
            "branch-in-pr",
            BranchOp.CHECKOUT,
        )
        assert gitlab_checkout_branch(None, None, open_pr) == (
            "branch-in-pr",
            BranchOp.CHECKOUT,
        )
        # Create a new branch if we don't have a current one
        assert gitlab_checkout_branch(None, None, None) == (
            "my-new-branch",
            BranchOp.CREATE_AND_CHECKOUT,
        )


def test_clone_repo() -> None:
    # assert public HTTPS git clone
    url, env = clone_repo_url(GitOperatorContext(
        namespace="test",
        api_spec=APISpec(entities={}, api_version=18),
        timeout=5,
        target_tags=frozenset("master"),
        dry_run=False,
        git_vendor="github",
        git_repository="sdp-operator-1",
        git_base_branch="master",
        git_repository_fork="fork",
        main_branch="main",
        git_hostname=None,
        git_ssh_port=None,
        git_username=None,
        git_token=None,
        log_level="info",
    ))
    assert url == 'https://git@github.com'
    TestCase().assertDictEqual({
        'GIT_ASKPASS': '/bin/echo',
    }, env)

    # assert private HTTPS git clone
    url, _ = clone_repo_url(GitOperatorContext(
        namespace="test",
        api_spec=APISpec(entities={}, api_version=18),
        timeout=5,
        target_tags=frozenset("master"),
        dry_run=False,
        git_vendor="github",
        git_repository="sdp-operator-2",
        git_base_branch="master",
        git_repository_fork="fork",
        main_branch="main",
        git_hostname=None,
        git_ssh_port=None,
        git_username="bob",
        git_token="hunter2",
        log_level="info",
    ))
    assert url == 'https://bob:hunter2@github.com'

    # assert private ssh git clone
    with tempfile.TemporaryDirectory() as tmp:
        url, env = clone_repo_url(GitOperatorContext(
            namespace="test",
            api_spec=APISpec(entities={}, api_version=18),
            timeout=5,
            target_tags=frozenset("master"),
            dry_run=False,
            git_vendor="gitlab",
            git_repository="sdp-operator-3",
            git_base_branch="master",
            git_repository_fork="fork",
            main_branch="main",
            git_hostname=None,
            git_ssh_port="21",
            git_username=None,
            git_token=None,
            log_level="info",
        ), Path(tmp))
        TestCase().assertDictEqual({
            'GIT_ASKPASS': '/bin/echo',
            'GIT_SSH_COMMAND': f"ssh -i {tmp} -o IdentitiesOnly=yes -p 21"
        }, env)
        assert url == 'ssh://git@gitlab.com'

    # assert private ssh git clone
    with tempfile.TemporaryDirectory() as tmp:
        url, env = clone_repo_url(GitOperatorContext(
            namespace="test",
            api_spec=APISpec(entities={}, api_version=18),
            timeout=5,
            target_tags=frozenset("master"),
            dry_run=False,
            git_vendor="gitlab",
            git_repository="sdp-operator-4",
            git_base_branch="master",
            git_repository_fork="fork",
            main_branch="main",
            git_hostname=None,
            git_ssh_port=None,
            git_username=None,
            git_token=None,
            log_level="info",
        ), Path(tmp))
        TestCase().assertDictEqual({
            'GIT_ASKPASS': '/bin/echo',
            'GIT_SSH_COMMAND': f"ssh -i {tmp} -o IdentitiesOnly=yes"
        }, env)
        assert url == 'ssh://git@gitlab.com'

    # assert private ssh git clone strict checking disabled
    with tempfile.TemporaryDirectory() as tmp:
        url, env = clone_repo_url(GitOperatorContext(
            namespace="test",
            api_spec=APISpec(entities={}, api_version=18),
            timeout=5,
            target_tags=frozenset("master"),
            dry_run=False,
            git_vendor="gitlab",
            git_repository="sdp-operator-5",
            git_base_branch="master",
            git_repository_fork="fork",
            main_branch="main",
            git_hostname=None,
            git_ssh_port=None,
            git_username=None,
            git_token=None,
            log_level="info",
            git_strict_host_key_checking=False
        ), Path(tmp))
        TestCase().assertDictEqual({
            'GIT_ASKPASS': '/bin/echo',
            'GIT_SSH_COMMAND': f"ssh -i {tmp} -o IdentitiesOnly=yes -o StrictHostKeyChecking=no"
        }, env)
        assert url == 'ssh://git@gitlab.com'


