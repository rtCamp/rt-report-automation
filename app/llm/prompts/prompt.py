"""Prompt definitions for LLM interactions."""

FORMAT = """
{{
    "summary": "A concise narrative summary of the project's current state, key accomplishments, and overall progress. This should be 2 to 3 short paragraphs with no more than 350 words. Focus only on the most important deliverables, milestones, and current priorities.\\n\\nUse proper paragraph breaks between sections for readability.",
    "riskBlockerActionNeeded": "Detailed description of any risks, blockers, or critical actions that need immediate attention. If there are no explicit blockers mentioned, state 'No explicit blockers reported.' Include only the most relevant action items, dependencies, or issues that could impact project timeline or success.\\n\\nUse line breaks between different risk categories or action items.",
    "taskDetails": {{
        "completed": "Format as: Main Issue Title: Brief description of the completed work.\\n\\t Specific action item completed\\n\\t Another specific action item completed\\n\\t Additional completed task details\\n\\nLimit to 4–5 main issue titles total, each with 2–4 bullet points.\\n\\nExample format:\\nFeature Development: Core functionality implementation\\n\\t API endpoints created and tested\\n\\t Database schema updated\\n\\t Unit tests added",
        "inProgress": "Include only those that are inProgress and strictly avoid things that are completed Format as: Main Issue Title: Brief description of ongoing work.\\n\\t Current task being worked on\\n\\t Another ongoing task\\n\\t Status of current work\\n\\nLimit to 4–5 main issue titles total, each with 2–4 bullet points.\\n\\nExample format:\\nUI Development: User interface improvements\\n\\t Dashboard components in development\\n\\t User authentication flow being refined\\n\\t Responsive design adjustments ongoing",
        "inReview": "Format as: Main Issue Title: Brief description of work under review.\\n\\t Pull request or deliverable under review\\n\\t Code review or approval process\\n\\t Documentation or design review status\\n\\nLimit to 4–5 main issue titles total, each with 2–4 bullet points. If there are no explicit in-review tasks, state 'Nothing is in review.'\\n\\nExample format:\\nCode Review: Backend improvements under review\\n\\t PR #123 awaiting senior developer review\\n\\t Security audit documentation pending approval\\n\\t Performance optimization changes being tested"
    }}
}}
"""  # noqa: E501 -- JSON schema that defines the expected structure of the output.
