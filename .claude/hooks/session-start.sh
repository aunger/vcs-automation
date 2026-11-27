#!/usr/bin/env bash
# The SessionStart hook .claude/settings.json runs: in a cloud session, installs
# the Claude Code plugins .claude/vcs-automation-tools pins.
#
# A cloud session never installs the plugins a repository declares in its
# .claude/settings.json, so this hook does (aunger/vcs-automation#53).
# .claude/install-plugins.sh says what it installs, when it does nothing, and what
# its one line of stdout, which reaches the session's context, asks of the user.
#
# Elsewhere it does nothing: run .claude/install-plugins.sh by hand there.
#
# A failure of the script is reported on stdout, so the session hears of it,
# and the hook still exits 0.

set -uo pipefail

if [[ "${CLAUDE_CODE_REMOTE:-}" != "true" ]]; then
    exit 0
fi

"$(dirname "${BASH_SOURCE[0]}")/../install-plugins.sh" \
    || echo "[session-start] warning: .claude/install-plugins.sh failed (exit $?), so the plugins it installs are missing or not at their pinned commit. Run it again from the Bash tool to see why, then ask the user to run /reload-skills."
