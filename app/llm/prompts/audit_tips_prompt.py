"""Prompt format for LLM-generated /pms audit tips."""

AUDIT_TIPS_FORMAT = """
{{
    "milestonesTip": "One or two sentences about the project's milestones, framed around business value/impact rather than a flat restatement of counts -- e.g. tie an overdue or undated milestone to a concrete next action or consequence (delayed delivery, unclear client commitment, invoice/reporting risk). Base this ONLY on the milestones actually present in audit_data. If there are no milestones, or none of them need attention, output null instead of inventing a tip.",
    "todosTip": "Same style as milestonesTip, but for todos: call out what's overdue or missing a deadline and why it matters (e.g. reporting will look stale, work may be forgotten), not just a restated count. Base this ONLY on the todos in audit_data. Output null if there's nothing worth flagging.",
    "risksTip": "Same style, for risks: prioritize by risk level and blocked status (risks have no due date in this system, so don't invent one) -- name the specific risk(s) that most need escalation or a mitigation plan and why. Base this ONLY on the risks in audit_data. Output null if there's nothing worth flagging.",
    "githubTip": "Same style, for GitHub issues: call out blocked issues or issues past their target date and the concrete risk of leaving them as-is (e.g. board is stale, engineering work silently slipping). Base this ONLY on the github_issues in audit_data. Output null if there are no GitHub issues connected or nothing worth flagging."
}}
"""  # noqa: E501 -- JSON schema that defines the expected structure of the output.

AUDIT_TIPS_INSTRUCTION = """
You are reviewing a single project's audit data (milestones, todos, risks, and
GitHub issues) for a project manager. Your job is to write short, specific,
business-value-framed tips -- not a generic restatement of what's missing.
Only reference items that actually appear in audit_data; never invent titles,
dates, or statuses that aren't there. Prefer naming the most urgent 1-2 items
by title over describing the whole list.
"""
