# Competition Review Brief

## Evaluation Narrative

This project turns a Windows/Python offline wheel folder into a small, reviewable package-governance workflow. Its differentiator is not automatic legal approval or a claim of perfect dependency inference. It joins local artifact evidence, environment-specific offline resolution, agent-readable MCP tools, and an explicit operator-controlled admission/release path.

## Suggested Live Demonstration

1. Open the Dash dashboard and show artifact counts, license evidence and application-domain statistics. Select an unknown-license artifact and export its evidence.
2. Choose a project with `pyproject.toml` or `requirements.txt`; show direct requirements, resolved transitives, and a deliberately unavailable requirement in a temporary fixture project.
3. Search the catalog through MCP, inspect a package and preview a temporary candidate wheel. Emphasize that preview does not execute the wheel.
4. Show the MCP admission tool is absent by default. Explain how an authorized operator can explicitly enable it, approve an exact SHA-256, test a temporary copy offline, and commit without overwrite.
5. Run `run_lint.bat` and `run_tests.bat`. Present the separate installer and immutable-release gates as deployment evidence rather than implying unit tests cover them.

Never stage or install an untrusted sample in the live demo. Use a disposable VM for execution-risk demonstrations; venv is not a security boundary.

## Measurable Review Points

- Offline-only package resolution and installation flags.
- Percentage/statistics denominators and multi-domain counting are explicitly documented.
- Unknown or conflicting license metadata remains reviewable rather than silently approved.
- Dependency completeness and project behavior are kept separate from the resolver result.
- MCP operations are annotated, bounded, directory-scoped and read-only by default.
- Admission has preview, exact digest approval, isolated-environment testing, rollback-on-failure, and no-overwrite behavior.
- Release bundles are immutable and have file-level plus archive-level checksums.

## Limitations to State Clearly

The tool does not authenticate publishers, perform malware analysis, prove that a license is legally sufficient, or guarantee that a package is suitable for a domain. Static import discovery can miss dynamic/plugin/optional behavior. `pip check` validates installed dependency metadata, not application-level correctness. A venv executes install hooks with the current user's OS privileges. State these limits as part of the evaluation, not as footnotes hidden after a claim of full automation.
