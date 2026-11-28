# Instructions for agents

- The development cycle for an issue or PR is the `orchestrate` plugin from [aunger/dot-and-tilde](https://github.com/aunger/dot-and-tilde), which the user starts with `/orchestrate <issue-number>`.
  Asked to address an issue or PR without an assigned role, say so rather than taking a role yourself.
  Its settings for this repository are in `.claude/orchestrate.json`.
- `.claude/install-plugins.sh` installs the plugins `.claude/vcs-automation-tools` pins; the session-start hook runs it in cloud sessions.
  If a plugin skill is missing and your working directory is outside this repository, ask the user for a session with only this repository attached; otherwise run the script and ask the user to run `/reload-skills`.
  Without plugins, the skills' text is in dot-and-tilde's `plugins/agent-citizenship/skills/`.
- Use the `agent-citizenship` skills: `pr-creation` for PRs, `code-edit` for code, and `writing` for issues and comments.
  The tests are `run-python-tests/run_tests.sh`; there are no linters.
- Read check-runs with the orchestrate plugin's CI Monitor (`scripts/ci_monitor/ci_monitor.py --once --config .claude/orchestrate.json`), not by hand.

## Scratchpad files

Every agent in a session, including each worktree sub-agent, is given the same scratchpad directory.
A helper left at its top level can be overwritten or run by another agent, which then reports results from a tree it never touched.

- Keep scratch files in a subdirectory of the scratchpad named after your worktree directory (`agent-<id>`), or for the top-level agent, the checkout directory, never at its top level.
- A helper that reports a test result prints the worktree path and `HEAD` it ran against, and you check both before reporting.

The second point is what catches a crossed result; the first only makes one rarer.
github-supplement's scratchpad hook warns a worktree agent whose `Bash` command, or `Write`, `Edit` or `NotebookEdit` path, reaches the scratchpad outside its subdirectory.

## Prose style

These rules apply to prose in documents, code comments, and text output.

- In Markdown and other auto-flowed text, split prose at sentence breaks.
- Prefer ASCII where there is a choice: no em-dashes (use commas, semicolons, parentheses or `--`), no ellipsis character (use `...`), and straight quotes only.
  Characters chosen for their meaning in code or markup are exempt.
- Write double-hyphens without surrounding spaces--like this.
- Cite code as `path/to/file.py:59`, linked to that line where the surface renders links.
