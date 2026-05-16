When the user mentions project architecture, engineering decisions, workflows, conventions,
preferences, or reusable implementation patterns that are not already documented in `CLAUDE.md`,
update the file automatically. Before adding anything, check whether the information already exists
or needs revision. Keep updates concise, structured, and durable so they remain useful across future
sessions. Prioritize documenting system architecture, repository structure, naming conventions,
preferred libraries/frameworks, deployment and testing approaches, API and data model standards,
infrastructure decisions, coding style preferences, and recurring patterns that affect future
development work. Avoid duplicate entries and place new information in the most relevant section
while preserving existing formatting and organization. Do not store temporary debugging notes,
experimental ideas, conversational filler, or secrets such as credentials, API keys, or tokens.
Treat `CLAUDE.md` as the persistent source of truth for the project’s technical context and user
preferences. After updating it, continue working using the newly captured context automatically
without requiring the user to repeat the information later.

## Mandatory rules

1. Don’t assume. Don’t hide confusion. Surface tradeoffs.
2. Minimum code that solves the problem. Nothing speculative.
3. Touch only what you must. Clean up only your own mess.
4. Define success criteria. Loop until verified.
