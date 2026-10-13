"""Reads and updates the Agent work board through GitHub's GraphQL API."""

import json
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from board_dispatcher.board import Card, last_worker_start
from board_dispatcher.sync import Label, Signals

GRAPHQL_URL = "https://api.github.com/graphql"
PAGE_SIZE = 100
MAX_PAGES = 10
TIMEOUT_SECONDS = 30

FIELDS_QUERY = """
query($owner: String!, $number: Int!) {
  organization(login: $owner) {
    projectV2(number: $number) {
      id
      status: field(name: "Status") {
        ... on ProjectV2SingleSelectField { id options { id name } }
      }
      notBefore: field(name: "Not before") { ... on ProjectV2Field { id } }
      proposal: field(name: "Proposal") { ... on ProjectV2Field { id } }
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
          proposal: fieldValueByName(name: "Proposal") {
            ... on ProjectV2ItemFieldTextValue { text }
          }
          content {
            ... on Issue {
              id
              number
              state
              body
              repository { nameWithOwner }
              labels(first: 30) { nodes { id name } }
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

SET_FIELD_MUTATION = """
mutation($project: ID!, $item: ID!, $field: ID!, $value: ProjectV2FieldValue!) {
  updateProjectV2ItemFieldValue(input: {
    projectId: $project, itemId: $item, fieldId: $field, value: $value
  }) { projectV2Item { id } }
}
"""

REMOVE_LABELS_MUTATION = """
mutation($subject: ID!, $labels: [ID!]!) {
  removeLabelsFromLabelable(input: { labelableId: $subject, labelIds: $labels }) {
    clientMutationId
  }
}
"""

ADD_COMMENT_MUTATION = """
mutation($subject: ID!, $body: String!) {
  addComment(input: { subjectId: $subject, body: $body }) { clientMutationId }
}
"""


@dataclass(frozen=True)
class BoardFields:
    project_id: str
    status_field_id: str
    status_option_ids: dict[str, str]
    not_before_field_id: str
    proposal_field_id: str


@dataclass(frozen=True)
class BoardItem:
    card: Card
    signals: Signals


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

    def fields(self, owner: str, number: int) -> BoardFields:
        data = self.graphql(FIELDS_QUERY, {"owner": owner, "number": number})
        project = data["organization"]["projectV2"]
        for name in ("status", "notBefore", "proposal"):
            if not project.get(name):
                raise GitHubError(f"The project is missing its {name} field")
        return BoardFields(
            project_id=project["id"],
            status_field_id=project["status"]["id"],
            status_option_ids={o["name"]: o["id"] for o in project["status"]["options"]},
            not_before_field_id=project["notBefore"]["id"],
            proposal_field_id=project["proposal"]["id"],
        )

    def items(self, owner: str, number: int, repo: str) -> list[BoardItem]:
        items: list[BoardItem] = []
        cursor: str | None = None
        for _ in range(MAX_PAGES):
            data = self.graphql(ITEMS_QUERY, {"owner": owner, "number": number, "cursor": cursor})
            page = data["organization"]["projectV2"]["items"]
            items.extend(item for node in page["nodes"] if (item := _to_item(node, repo)))
            if not page["pageInfo"]["hasNextPage"]:
                return items
            cursor = page["pageInfo"]["endCursor"]
        raise GitHubError(f"The board has more than {MAX_PAGES * PAGE_SIZE} items")

    def set_status(self, fields: BoardFields, item_id: str, status: str) -> None:
        option = fields.status_option_ids.get(status)
        if option is None:
            raise GitHubError(f"The Status field has no option named {status!r}")
        self._set_field(fields, item_id, fields.status_field_id, {"singleSelectOptionId": option})

    def set_not_before(self, fields: BoardFields, item_id: str, value: date) -> None:
        self._set_field(fields, item_id, fields.not_before_field_id, {"date": value.isoformat()})

    def set_proposal(self, fields: BoardFields, item_id: str, value: str) -> None:
        self._set_field(fields, item_id, fields.proposal_field_id, {"text": value})

    def remove_labels(self, issue_id: str, labels: tuple[Label, ...]) -> None:
        ids = [label.label_id for label in labels]
        self.graphql(REMOVE_LABELS_MUTATION, {"subject": issue_id, "labels": ids})

    def comment(self, issue_id: str, body: str) -> None:
        self.graphql(ADD_COMMENT_MUTATION, {"subject": issue_id, "body": body})

    def _set_field(
        self, fields: BoardFields, item_id: str, field_id: str, value: dict[str, str]
    ) -> None:
        variables = {
            "project": fields.project_id,
            "item": item_id,
            "field": field_id,
            "value": value,
        }
        self.graphql(SET_FIELD_MUTATION, variables)


def _single_select(value: dict[str, Any] | None) -> str | None:
    return value.get("name") if value else None


def _to_item(node: dict[str, Any], repo: str) -> BoardItem | None:
    """A BoardItem for an issue in `repo`, or None for drafts, pull requests and other repos."""
    issue = node.get("content") or {}
    if issue.get("repository", {}).get("nameWithOwner") != repo:
        return None
    not_before_value = node.get("notBefore")
    not_before = date.fromisoformat(not_before_value["date"]) if not_before_value else None
    proposal_value = node.get("proposal")
    comments = [
        (c["body"], datetime.fromisoformat(c["createdAt"])) for c in issue["comments"]["nodes"]
    ]
    card = Card(
        item_id=node["id"],
        issue_id=issue["id"],
        issue_ref=f"{repo}#{issue['number']}",
        issue_open=issue["state"] == "OPEN",
        status=_single_select(node.get("status")),
        agent=_single_select(node.get("agent")),
        not_before=not_before,
        open_blockers=issue["issueDependenciesSummary"]["blockedBy"],
        last_worker_start=last_worker_start(comments),
    )
    signals = Signals(
        labels=tuple(Label(n["id"], n["name"]) for n in issue["labels"]["nodes"]),
        body=issue.get("body") or "",
        not_before=not_before,
        proposal=proposal_value.get("text") if proposal_value else None,
    )
    return BoardItem(card=card, signals=signals)
