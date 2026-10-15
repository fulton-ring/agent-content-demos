"""The filled policy, one field per section of template/policy-template.md."""

from pydantic import BaseModel, Field

Bullet = str


class ApprovedTool(BaseModel):
    name: str = Field(description="Tool name as the organization uses it, e.g. 'Microsoft Copilot'.")
    approved_for: str = Field(
        description="What it's approved for, and whether it may hold any protected information. One short sentence."
    )


class ApprovalRule(BaseModel):
    use: str = Field(description="The use that needs a yes first. A few words.")
    approver: str = Field(description="The named person or role who approves it, as said on the call.")


class Policy(BaseModel):
    organization: str
    owner: str = Field(description="Person or role who owns the policy, as said on the call.")
    next_review: str = Field(description="When it is next reviewed, e.g. 'in 12 months' or 'after the pilot ends'.")
    why: str = Field(description="Why we have this policy. One or two sentences.")
    who_it_covers: str = Field(description="Who it covers. One sentence.")
    tools: list[ApprovedTool] = Field(min_length=1, max_length=5)
    new_tools: str = Field(
        description=(
            "Who approves a new tool, add-on, plugin, agent or AI feature in existing software,"
            " and what they check. One or two sentences."
        )
    )
    allowed_uses: list[Bullet] = Field(min_length=3, max_length=6)
    needs_approval: list[ApprovalRule] = Field(min_length=2, max_length=5)
    protected_information: str = Field(
        description=(
            "The named kinds of donor, client, student, patient, staff and volunteer information"
            " that never go into an AI tool unless that tool is approved for it above."
        )
    )
    off_limits: list[Bullet] = Field(min_length=2, max_length=4)
    check_before_it_goes_out: list[Bullet] = Field(min_length=1, max_length=3)
    decisions_about_people: list[Bullet] = Field(min_length=1, max_length=2)
    being_open: list[Bullet] = Field(min_length=1, max_length=3)
    if_something_goes_wrong: list[Bullet] = Field(min_length=1, max_length=2)
    who_owns_this: list[Bullet] = Field(min_length=1, max_length=3)
    open_questions: list[Bullet] = Field(
        max_length=4, description="Decisions the call left open, phrased as questions for the board."
    )


SECTIONS: dict[str, list[str]] = {
    "Header": ["organization", "owner", "next_review"],
    "Why we have this policy": ["why"],
    "Who it covers": ["who_it_covers"],
    "Tools we use": ["tools", "new_tools"],
    "What you can use AI for": ["allowed_uses"],
    "Needs approval first": ["needs_approval"],
    "Off limits": ["protected_information", "off_limits"],
    "Check everything before it goes out": ["check_before_it_goes_out"],
    "Decisions about people": ["decisions_about_people"],
    "Being open about AI": ["being_open"],
    "If something goes wrong": ["if_something_goes_wrong"],
    "Who owns this policy": ["who_owns_this"],
}
"""Template sections and the fields that fill them. Open questions are optional, so they aren't a section to fill."""
