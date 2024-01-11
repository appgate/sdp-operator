import dataclasses

from github.GithubObject import Opt, NotSet, is_optional, is_defined
from github.Issue import Issue
from github.PullRequest import PullRequest
from github.Repository import Repository


@dataclasses.dataclass
class SDPRepository:
    gh_repo: Repository

    def create_pull(
        self,
        base: str,
        head: str,
        *,
        title: Opt[str] = NotSet,
        body: Opt[str] = NotSet,
        maintainer_can_modify: Opt[bool] = NotSet,
        draft: Opt[bool] = NotSet,
        issue: Opt[Issue] = NotSet,
        head_repo: Opt[str] = NotSet,
    ) -> PullRequest:
        """
        :calls: `POST /repos/{owner}/{repo}/pulls <https://docs.github.com/en/free-pro-team@latest/rest/pulls/pulls?apiVersion=2022-11-28#create-a-pull-request>`_
        """
        assert isinstance(base, str), base
        assert isinstance(head, str), head
        assert is_optional(title, str), title
        assert is_optional(body, str), body
        assert is_optional(maintainer_can_modify, bool), maintainer_can_modify
        assert is_optional(draft, bool), draft
        assert is_optional(issue, Issue), issue
        assert is_optional(head_repo, str), head_repo

        post_parameters = NotSet.remove_unset_items(
            {
                "base": base,
                "head": head,
                "title": title,
                "body": body,
                "maintainer_can_modify": maintainer_can_modify,
                "draft": draft,
                "head_repo": head_repo,
            }
        )

        if is_defined(issue):
            post_parameters["issue"] = issue._identity

        headers, data = self.gh_repo._requester.requestJsonAndCheck(
            "POST", f"{self.gh_repo.url}/pulls", input=post_parameters
        )
        return PullRequest(self.gh_repo._requester, headers, data, completed=True)
