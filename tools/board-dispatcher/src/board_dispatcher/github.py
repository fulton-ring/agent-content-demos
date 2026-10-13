"""Reads and updates the Agent work board through GitHub's GraphQL API."""

import json
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from board_dispatcher.board import Card, last_worker_start

GRAPHQL_URL = "https://api.github.com/graphql"
PAGE_SIZE = 100
MAX_PAGES = 10
TIMEOUT_SECONDS = 30

FIELDS_QUERY = """
query($owner: String!, $number: Int!) {
  organization(login: $owner) {
    projectV2(number: $number) {
      id
      field(name: "Status") {
        ... on ProjectV2SingleSelectField { id options { id name } }
      }
    }
  }
}
"""

ITEMS_QUERY = """
query($owner: String!, $number: Int!, $cursor: String) {
  organization(login: $owner) {
    projectV2(number: $number) {
      items(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          status: fieldValueByName(name: "Status") {
            ... on ProjectV2ItemFieldSingleSelectValue { name }
          }
          agent: fieldValueByName(name: "Agent") {
            ... on ProjectV2ItemFieldSingleSelectValue { name }
          }
          notBefore: fieldValueByName(name: "Not before") {
            ... on ProjectV2ItemFieldDateValue { date }
          }
          content {
            ... on Issue {
              id
              number
              state
              repository { nameWithOwner }
              issueDependenciesSummary { blockedBy }
              comments(last: 30) { nodes { body createdAt } }
            }
          }
        }
      }
    }
  }
}
"""

SET_STATUS_MUTATION = """
mutation($project: ID!, $item: ID!, $field: ID!, $option: String!) {
  updateProjectV2ItemFieldValue(input: {
    projectId: $project, itemId: $item, fieldId: $field,
    value: { singleSelectOptionId: $option }
  }) { projectV2Item { id } }
}
"""

ADD_COMMENT_MUTATION = """
mutation($subject: ID!, $body: String!) {
  addComment(input: { subjectId: $subject, body: $body }) { clientMutationId }
}
"""


@dataclass(frozen=True)
class StatusField:
    project_id: str
    field_id: str
    option_ids: dict[str, str]


class GitHubError(RuntimeError):
    pass


class GitHub:
    def __init__(self, token: str) -> None:
        assert token, "GitHub token is empty"
        self._token = token

    def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({"query": query, "variables": variables}).encode()
        request = urllib.request.Request(  # noqa: S310 - fixed https URL
            GRAPHQL_URL,
            data=body,
            headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            if response.status != 200:  # noqa: PLR2004
                raise GitHubError(f"GraphQL returned HTTP {response.status}")
            payload = json.load(response)
        if payload.get("errors"):
            raise GitHubError(f"GraphQL errors: {payload['errors']}")
        return payload["data"]

    def status_field(self, owner: str, number: int) -> StatusField:
        data = self.graphql(FIELDS_QUERY, {"owner": owner, "number": number})
        project = data["organization"]["projectV2"]
        field = project["field"]
        if not field:
            raise GitHubError("The project has no Status field")
        options = {option["name"]: option["id"] for option in field["options"]}
        return StatusField(project_id=project["id"], field_id=field["id"], option_ids=options)

    def cards(self, owner: str, number: int, repo: str) -> list[Card]:
        cards: list[Card] = []
        cursor: str | None = None
        for _ in range(MAX_PAGES):
            data = self.graphql(ITEMS_QUERY, {"owner": owner, "number": number, "cursor": cursor})
            items = data["organization"]["projectV2"]["items"]
            cards.extend(card for node in items["nodes"] if (card := _to_card(node, repo)))
            if not items["pageInfo"]["hasNextPage"]:
                return cards
            cursor = items["pageInfo"]["endCursor"]
        raise GitHubError(f"The board has more than {MAX_PAGES * PAGE_SIZE} items")

    def set_status(self, field: StatusField, item_id: str, status: str) -> None:
        option = field.option_ids.get(status)
        if option is None:
            raise GitHubError(f"The Status field has no option named {status!r}")
        variables = {
            "project": field.project_id,
            "item": item_id,
            "field": field.field_id,
            "option": option,
        }
        self.graphql(SET_STATUS_MUTATION, variables)

    def comment(self, issue_id: str, body: str) -> None:
        self.graphql(ADD_COMMENT_MUTATION, {"subject": issue_id, "body": body})


def _single_select(value: dict[str, Any] | None) -> str | None:
    return value.get("name") if value else None


def _to_card(node: dict[str, Any], repo: str) -> Card | None:
    """A Card for an issue in `repo`, or None for drafts, pull requests and other repos."""
    issue = node.get("content") or {}
    if issue.get("repository", {}).get("nameWithOwner") != repo:
        return None
    not_before = node.get("notBefore")
    comments = [
        (c["body"], datetime.fromisoformat(c["createdAt"])) for c in issue["comments"]["nodes"]
    ]
    return Card(
        item_id=node["id"],
        issue_id=issue["id"],
        issue_ref=f"{repo}#{issue['number']}",
        issue_open=issue["state"] == "OPEN",
        status=_single_select(node.get("status")),
        agent=_single_select(node.get("agent")),
        not_before=date.fromisoformat(not_before["date"]) if not_before else None,
        open_blockers=issue["issueDependenciesSummary"]["blockedBy"],
        last_worker_start=last_worker_start(comments),
    )
