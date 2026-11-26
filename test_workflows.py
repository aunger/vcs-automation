#!/usr/bin/env python3
"""Checks on this repository's own workflows, which call its actions by local path.

Each workflow in `.github/workflows` that runs an action here calls it as
`uses: ./<action>`, from a checkout of this repository. What is checked is what
would otherwise show only as a failed or misbehaving run on GitHub:

- every action runs here: a workflow step calls it, or a called action's
  `action.yml` runs its files (as three actions run
  install-pinned-requirements' installer);
- each `./<action>` step comes after a checkout in its job, and a sparse
  checkout holds the action's directory and every sibling directory that it,
  its scripts, or those siblings reach by `..` (`shared/`, for instance);
- each such step passes only inputs the action declares, and every input the
  action requires, since GitHub only warns about an unknown input and a
  misspelled optional table would then read as its default;
- each label action is called by exactly one step, and its tables parse with
  the action's own parsers;
- the copies of a shared table agree, as the README's "Label actions" section
  asks, and the tables hold the orchestrate protocol's labels where its "The
  merge gate and orchestrate's labels" section puts them;
- the merge gate's job runs enforcement first and passes on what it removed,
  on the triggers check-blocking-labels/action.yml names;
- a few of this repository's titles and paths get the labels the rules are
  meant to give them.
"""

import dataclasses
import re
import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
WORKFLOWS = ROOT / ".github" / "workflows"

sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(ROOT / "label-by-title"))
sys.path.insert(0, str(ROOT / "label-by-files"))
import label_by_files as lbf  # noqa: E402
import label_by_title as lbt  # noqa: E402
import label_common as lc  # noqa: E402

LOCAL_USES = re.compile(r"\./(?P<action>[A-Za-z0-9_.-]+)/?")
CHECKOUT = re.compile(r"actions/checkout@\S+")
# A sibling directory reached from an action.yml step, or from a script's
# `os.path.join(..., "..", "<dir>")`.
SIBLING_IN_ACTION = re.compile(r"\$GITHUB_ACTION_PATH/\.\./([A-Za-z0-9_.-]+)/")
SIBLING_IN_SCRIPT = re.compile(r"""["']\.\.["'],\s*["']([A-Za-z0-9_.-]+)["']""")

TITLE = "label-by-title"
FILES = "label-by-files"
ENFORCE = "enforce-mutually-exclusive-labels"
GATE = "check-blocking-labels"
SNOOZE = "snooze-issues"
WAKE = "wake-snoozed-issues"
PROPAGATE = "propagate-issue-labels"
RECONCILE = "reconcile-issue-labels"
LABEL_ACTIONS = (TITLE, FILES, ENFORCE, GATE, SNOOZE, WAKE, PROPAGATE, RECONCILE)

# Inputs of the label actions that are not tables.
NOT_TABLES = {"github-token", "removed-labels"}

# The orchestrate plugin's label protocol, as the README's "The merge gate and
# orchestrate's labels" section gives it.
BLOCKING_LABELS = frozenset(
    {"orchestrating", "verification needed", "changes requested", "changes done"}
)
PROTOCOL_LABELS = BLOCKING_LABELS | {"orchestrate", "verified"}
PROTOCOL_SETS = frozenset(
    {
        frozenset({"orchestrate", "orchestrating"}),
        frozenset({"verification needed", "verified"}),
        frozenset({"changes requested", "changes done"}),
    }
)
PROTOCOL_PREFIXES = frozenset({"c-a-", "c-r-"})
GATE_PULL_REQUEST_TYPES = {"opened", "reopened", "synchronize", "labeled", "unlabeled", "closed"}


@dataclasses.dataclass(frozen=True)
class Step:
    """One workflow step that calls an action of this repository by local path."""

    workflow: str
    job: str
    index: int
    action: str
    id: str | None
    inputs: dict[str, str]
    # The `with:` of the last actions/checkout step before this one in its
    # job, or None when there is none.
    checkout: dict | None


def action_names() -> list[str]:
    return sorted(
        path.parent.name
        for path in ROOT.glob("*/action.yml")
        if not path.parent.name.startswith(".")
    )


def action_manifest(action: str) -> dict:
    return yaml.safe_load((ROOT / action / "action.yml").read_text(encoding="utf-8"))


def load_workflow(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def triggers(workflow: dict) -> dict:
    # PyYAML reads the bare key `on` as the boolean True.
    on = workflow.get("on", workflow.get(True))
    if isinstance(on, str):
        return {on: None}
    if isinstance(on, list):
        return dict.fromkeys(on)
    return on or {}


def local_steps() -> list[Step]:
    found = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for job_id, job in (load_workflow(path).get("jobs") or {}).items():
            checkout = None
            for index, step in enumerate((job or {}).get("steps") or []):
                uses = str(step.get("uses", "")).strip()
                if CHECKOUT.fullmatch(uses):
                    checkout = step.get("with") or {}
                    continue
                match = LOCAL_USES.fullmatch(uses)
                if not match:
                    continue
                inputs = {
                    str(key): "" if value is None else str(value)
                    for key, value in (step.get("with") or {}).items()
                }
                found.append(
                    Step(
                        path.name, job_id, index, match["action"], step.get("id"), inputs, checkout
                    )
                )
    return found


def siblings_run_by(action: str) -> set[str]:
    """Return the sibling actions whose files *action*'s action.yml runs."""
    text = (ROOT / action / "action.yml").read_text(encoding="utf-8")
    return set(SIBLING_IN_ACTION.findall(text))


def directories_needed(action: str) -> set[str]:
    """Return *action*'s directory and every directory it reaches by `..`, transitively."""
    needed: set[str] = set()
    pending = [action]
    while pending:
        directory = pending.pop()
        if directory in needed:
            continue
        needed.add(directory)
        reached = set()
        manifest = ROOT / directory / "action.yml"
        if manifest.is_file():
            reached |= set(SIBLING_IN_ACTION.findall(manifest.read_text(encoding="utf-8")))
        for script in (ROOT / directory).iterdir():
            if script.suffix in {".py", ".sh"} and not script.name.startswith("test_"):
                reached |= set(SIBLING_IN_SCRIPT.findall(script.read_text(encoding="utf-8")))
        pending += sorted(reached - needed)
    return needed


def sparse_directories(checkout: dict) -> set[str] | None:
    """Return the directories a checkout's `sparse-checkout` lists, or None for a full one."""
    text = checkout.get("sparse-checkout")
    if not text:
        return None
    return {line.strip().strip("/") for line in str(text).splitlines() if line.strip()}


def label_steps() -> dict[str, Step]:
    """Return {label action: its one step}; fail unless each has exactly one."""
    by_action: dict[str, list[Step]] = {action: [] for action in LABEL_ACTIONS}
    for step in local_steps():
        if step.action in by_action:
            by_action[step.action].append(step)
    problems = [
        f"{action} is called by {len(steps)} steps "
        f"({', '.join(s.workflow for s in steps) or 'none'})"
        for action, steps in by_action.items()
        if len(steps) != 1
    ]
    if problems:
        raise AssertionError("; ".join(problems) + "; expected one each")
    return {action: steps[0] for action, steps in by_action.items()}


def table_text(step: Step, name: str) -> str:
    """Return the text the runner passes for table input *name*: the step's, or the default."""
    if name in step.inputs:
        return step.inputs[name]
    return str(action_manifest(step.action)["inputs"][name].get("default", ""))


PARSERS = {
    "skip-on-pull-requests": lambda text: lc.parse_label_list("skip-on-pull-requests", text),
    "exclusive-sets": lambda text: frozenset(lc.parse_label_sets("exclusive-sets", text)),
    "exclusive-prefixes": lambda text: frozenset(lc.parse_prefixes("exclusive-prefixes", text)),
    "blocking-labels": lambda text: lc.parse_label_list("blocking-labels", text, required=True),
    "snooze-labels": lambda text: {
        label.lower(): days for label, days in lc.parse_snooze_labels("snooze-labels", text).items()
    },
    "remove-on-wake": lambda text: lc.parse_label_list("remove-on-wake", text),
    "excluded-labels": lambda text: lc.parse_label_list("excluded-labels", text),
}
RULE_PARSERS = {
    TITLE: lambda text: lbt.parse_rules(text, "rules"),
    FILES: lambda text: lbf.parse_rules(text, "rules"),
}


def parse_table(step: Step, name: str) -> object:
    text = table_text(step, name)
    parser = RULE_PARSERS[step.action] if name == "rules" else PARSERS[name]
    return parser(text)


def table_names(action: str) -> list[str]:
    return [name for name in action_manifest(action).get("inputs") or {} if name not in NOT_TABLES]


def tables() -> dict[str, dict[str, object]]:
    """Return {label action: {table input: its parsed value}}."""
    return {
        action: {name: parse_table(step, name) for name in table_names(action)}
        for action, step in label_steps().items()
    }


def any_file_labels(rules: list) -> frozenset[str]:
    return frozenset(rule.label.lower() for rule in rules if rule.mode == "any-file")


class LocalStepsTest(unittest.TestCase):
    def setUp(self):
        self.steps = local_steps()

    def test_there_are_local_steps_to_check(self):
        self.assertTrue(self.steps, "found no `uses: ./<action>` steps")

    def test_every_action_runs_here(self):
        called = {step.action for step in self.steps}
        reached = set().union(*(siblings_run_by(action) for action in called))
        for action in action_names():
            with self.subTest(action=action):
                self.assertIn(action, called | reached, "no workflow here calls it")

    def test_each_local_step_names_an_action(self):
        actions = set(action_names())
        for step in self.steps:
            with self.subTest(workflow=step.workflow, job=step.job, step=step.index):
                self.assertIn(step.action, actions)

    def test_each_local_step_follows_a_checkout_that_holds_it(self):
        for step in self.steps:
            with self.subTest(workflow=step.workflow, job=step.job, action=step.action):
                self.assertIsNotNone(step.checkout, "no actions/checkout step before it in its job")
                sparse = sparse_directories(step.checkout)
                if sparse is not None:
                    missing = directories_needed(step.action) - sparse
                    self.assertFalse(missing, f"the sparse checkout lacks {sorted(missing)}")

    def test_each_local_step_passes_only_declared_inputs_and_every_required_one(self):
        for step in self.steps:
            with self.subTest(workflow=step.workflow, job=step.job, action=step.action):
                declared = action_manifest(step.action).get("inputs") or {}
                self.assertLessEqual(set(step.inputs), set(declared))
                required = {
                    name
                    for name, spec in declared.items()
                    if spec.get("required") and "default" not in spec
                }
                self.assertLessEqual(required, set(step.inputs))


class DirectoriesNeededTest(unittest.TestCase):
    def test_follows_scripts_and_action_files_transitively(self):
        self.assertEqual({RECONCILE, PROPAGATE, "shared"}, directories_needed(RECONCILE))
        self.assertEqual(
            {"dependency-audit", "install-pinned-requirements", "shared"},
            directories_needed("dependency-audit"),
        )


class LabelTablesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.steps = label_steps()
        cls.tables = tables()

    def assertSameTable(self, name, *actions):
        first, *others = actions
        for other in others:
            workflows = (self.steps[first].workflow, self.steps[other].workflow)
            with self.subTest(table=name, workflows=workflows):
                self.assertEqual(self.tables[first][name], self.tables[other][name])

    def test_exclusive_sets_and_prefixes_agree(self):
        for name in ("exclusive-sets", "exclusive-prefixes"):
            self.assertSameTable(name, ENFORCE, PROPAGATE, RECONCILE)

    def test_propagation_and_reconciliation_exclude_the_same_labels(self):
        self.assertSameTable("excluded-labels", PROPAGATE, RECONCILE)

    def test_snooze_labels_agree_and_are_one_exclusive_set(self):
        self.assertSameTable("snooze-labels", SNOOZE, WAKE)
        ladder = frozenset(self.tables[SNOOZE]["snooze-labels"])
        self.assertIn(ladder, self.tables[ENFORCE]["exclusive-sets"])

    def test_any_file_labels_are_skipped_by_title_and_never_copied(self):
        any_file = any_file_labels(self.tables[FILES]["rules"])
        self.assertTrue(any_file, "label-by-files has no any-file rule to exercise")
        self.assertEqual(any_file, self.tables[TITLE]["skip-on-pull-requests"])
        for action in (PROPAGATE, RECONCILE):
            with self.subTest(action=action):
                self.assertLessEqual(any_file, self.tables[action]["excluded-labels"])

    def test_the_gate_blocks_on_the_protocol_labels(self):
        self.assertEqual(BLOCKING_LABELS, self.tables[GATE]["blocking-labels"])

    def test_the_protocol_pairs_are_separate_exclusive_sets(self):
        self.assertLessEqual(PROTOCOL_SETS, self.tables[ENFORCE]["exclusive-sets"])
        self.assertLessEqual(PROTOCOL_PREFIXES, self.tables[ENFORCE]["exclusive-prefixes"])

    def test_protocol_labels_are_never_copied_and_are_removed_on_wake(self):
        for action in (PROPAGATE, RECONCILE):
            with self.subTest(action=action):
                self.assertLessEqual(PROTOCOL_LABELS, self.tables[action]["excluded-labels"])
        self.assertLessEqual(PROTOCOL_LABELS, self.tables[WAKE]["remove-on-wake"])

    def test_the_parsers_refuse_a_malformed_table(self):
        """The parsers are stricter than JSON: a check that they ran on the tables above."""
        bad = dataclasses.replace(self.steps[ENFORCE], inputs={"exclusive-sets": '[["only one"]]'})
        with self.assertRaises(lc.InputError):
            parse_table(bad, "exclusive-sets")


class MergeGateTest(unittest.TestCase):
    def setUp(self):
        steps = label_steps()
        self.enforce, self.gate = steps[ENFORCE], steps[GATE]

    def test_enforcement_runs_first_in_the_gate_job(self):
        self.assertEqual(
            (self.enforce.workflow, self.enforce.job), (self.gate.workflow, self.gate.job)
        )
        self.assertLess(self.enforce.index, self.gate.index)

    def test_the_gate_drops_what_enforcement_removed(self):
        self.assertTrue(self.enforce.id, "the enforce step needs an id")
        self.assertEqual(
            f"${{{{ steps.{self.enforce.id}.outputs.removed }}}}",
            self.gate.inputs.get("removed-labels", "").strip(),
        )

    def test_the_gate_runs_on_the_events_its_action_names(self):
        on = triggers(load_workflow(WORKFLOWS / self.gate.workflow))
        pull_request_types = set((on.get("pull_request") or {}).get("types") or [])
        self.assertLessEqual(GATE_PULL_REQUEST_TYPES, pull_request_types)
        self.assertIn("labeled", (on.get("issues") or {}).get("types") or [])

    def test_the_gate_job_has_a_name_for_the_required_check(self):
        job = load_workflow(WORKFLOWS / self.gate.workflow)["jobs"][self.gate.job]
        self.assertEqual("Merge gate", job.get("name"))


class RulesTest(unittest.TestCase):
    """Some of this repository's own titles and paths, and the labels they should get."""

    @classmethod
    def setUpClass(cls):
        found = tables()
        cls.title_rules = found[TITLE]["rules"]
        cls.skip = found[TITLE]["skip-on-pull-requests"]
        cls.file_rules = found[FILES]["rules"]

    def test_titles(self):
        for title, labels in {
            "Hide all Claude Code attribution in commits and pull requests": ["agents"],
            "Add CodeQL analysis workflow configuration": ["ci"],
            "Name the repository vcs-automation in the README title and uses: examples": [
                "documentation"
            ],
            "Run every action on this repository's own issues, pull requests and branches": [],
            "Compute branch reachability in fewer git calls in branch-cleanup-report": [],
        }.items():
            with self.subTest(title=title):
                self.assertEqual(labels, lbt.matching_labels(title, self.title_rules))

    def test_agents_is_left_to_the_files_on_pull_requests(self):
        title = "Hide all Claude Code attribution in commits and pull requests"
        self.assertEqual([], lbt.matching_labels(title, self.title_rules, True, self.skip))

    def test_files(self):
        for paths, labels in {
            ("README.md", "dependency-audit/README.md"): ["documentation"],
            (".github/workflows/test.yml", ".github/dependabot.yml"): ["ci"],
            (".claude/settings.json", "README.md"): ["agents"],
            (".github/workflows/merge-gate.yml", "test_workflows.py"): [],
        }.items():
            with self.subTest(paths=paths):
                self.assertEqual(sorted(labels), lbf.matching_labels(list(paths), self.file_rules))


if __name__ == "__main__":
    unittest.main()
