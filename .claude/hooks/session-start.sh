#!/usr/bin/env bash
# SessionStart hook: in a cloud session, run .claude/install-plugins.sh, since a
# cloud session never installs the plugins a repository declares. A failure is
# reported on stdout, which the session sees, and the hook still exits 0.

set -uo pipefail

if [[ "${CLAUDE_CODE_REMOTE:-}" != "true" ]]; then
    exit 0
fi

"$(dirname "${BASH_SOURCE[0]}")/../install-plugins.sh" \
    || echo "[session-start] warning: .claude/install-plugins.sh failed (exit $?), so the plugins it installs are missing or not at their pinned commit. Run it again from the Bash tool to see why, then ask the user to run /reload-skills."
