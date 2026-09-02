#!/usr/bin/env python3
"""Fail closed if the CLI interaction-surface contract drifts from runtime code.

contracts/interaction_surface.json declared the controls that stand in front of a
real external effect, and nothing executed those declarations. A contract with no
gate is a claim, not a control: every requirement below must name the source marker
that enforces it, and an unmapped requirement is itself an error.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = Path("contracts/interaction_surface.json")
FINAL_DELIVERY = "src/bro_runtime/final_delivery.py"
CONVERSATION = "src/bro_runtime/conversation.py"
SURFACE = "src/bro_runtime/interaction_surface.py"
ENTRYPOINT = "scripts/bro_interact.py"

# Each declared requirement must name the source marker that enforces it.
REQUIREMENT_MARKERS: dict[str, tuple[tuple[str, str], ...]] = {
    "natural_language_intake": ((ENTRYPOINT, "argparse"), (FINAL_DELIVERY, "def interpret(")),
    "automatic_talk_think_act_routing": ((CONVERSATION, "routed = dict(self.router(request, self.history))"),),
    "study_is_read_and_learn_only": (
        (CONVERSATION, "if mode is InteractionMode.STUDY:"),
        ("src/bro_runtime/study_runtime.py", "never produces permission"),
    ),
    "conversation_history_in_session": ((CONVERSATION, "self._history.append(ConversationMessage(role, content))"),),
    "talk_think_never_execute_external_effects": ((CONVERSATION, "if mode is InteractionMode.ACT:"),),
    "action_credentials_required_only_for_act_execution": ((ENTRYPOINT, 'required("BRO_GITHUB_TOKEN")'),),
    "explicit_material_scope_confirmation": (
        (FINAL_DELIVERY, "material=self.material_floor or bool(parsed.get(\"material\", True)),"),
        (FINAL_DELIVERY, "material interpreted scope requires explicit confirmation"),
    ),
    "materiality_owned_by_runtime_not_model": (
        (FINAL_DELIVERY, "material_floor: bool = True"),
        (FINAL_DELIVERY, "self.material_floor = bool(material_floor)"),
    ),
    "specialist_selection": ((FINAL_DELIVERY, "planner did not select a specialist"),),
    "real_provider_execution": ((FINAL_DELIVERY, "execution missing"),),
    "independent_external_readback": ((FINAL_DELIVERY, "cannot self-attest as independent readback"),),
    "parallel_demo_path_forbidden": ((SURFACE, "does not create a second execution path"),),
}

ASSURANCE_FLOOR_MARKERS = {
    "external_system": (FINAL_DELIVERY, "real capability execution requires external-system readback"),
}

# Only the governed ACT closures may demand effect-provider credentials; a TALK or
# THINK turn must remain executable without them.
ACT_CREDENTIAL_OWNERS = {"github_binding", "executor", "readback"}
ACT_CREDENTIAL_NAMES = ("BRO_GITHUB_TOKEN", "BRO_GITHUB_OWNER", "BRO_GITHUB_REPOSITORY", "BRO_GITHUB_ISSUE")


def _read(root: Path, relative: str) -> str | None:
    path = root / relative
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def _credential_owners(source: str) -> list[str]:
    """Return the enclosing function of every action-credential reference."""
    tree = ast.parse(source)
    owners: list[str] = []
    stack: list[str] = []

    class Walker(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        def visit_Constant(self, node: ast.Constant) -> None:
            if isinstance(node.value, str) and node.value in ACT_CREDENTIAL_NAMES:
                owners.append(stack[-1] if stack else "<module>")

    Walker().visit(tree)
    return owners


def validate(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    raw = _read(root, str(CONTRACT))
    if raw is None:
        return [f"missing interaction surface contract: {CONTRACT}"]
    try:
        contract = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [f"{CONTRACT}: {exc}"]

    entrypoint = contract.get("entrypoint", "")
    if not entrypoint or not (root / entrypoint).is_file():
        errors.append(f"declared entrypoint is missing: {entrypoint!r}")

    for key, dotted in (("runtime", contract.get("runtime")), ("conversation_runtime", contract.get("conversation_runtime"))):
        if not isinstance(dotted, str) or "." not in dotted:
            errors.append(f"{key} must name a module-qualified runtime class")
            continue
        module, _, symbol = dotted.rpartition(".")
        relative = "src/" + module.replace(".", "/") + ".py"
        source = _read(root, relative)
        if source is None:
            errors.append(f"{key}: missing module {relative}")
        elif f"class {symbol}" not in source:
            errors.append(f"{key}: {relative} does not define {symbol}")

    modes = contract.get("modes")
    conversation = _read(root, CONVERSATION)
    if not isinstance(modes, dict) or not modes:
        errors.append("contract must declare interaction modes")
    elif conversation is None:
        errors.append(f"missing {CONVERSATION}")
    else:
        for mode in modes:
            if f'{mode} = "{mode}"' not in conversation:
                errors.append(f"declared mode {mode} is not an InteractionMode member")

    requirements = contract.get("requirements")
    if not isinstance(requirements, dict) or not requirements:
        errors.append("contract must declare requirements")
        requirements = {}
    for name, declared in sorted(requirements.items()):
        if name not in REQUIREMENT_MARKERS:
            errors.append(f"declared requirement has no executable enforcement mapping: {name}")
            continue
        if not declared:
            continue
        for relative, marker in REQUIREMENT_MARKERS[name]:
            source = _read(root, relative)
            if source is None:
                errors.append(f"{name}: missing enforcement file {relative}")
            elif marker not in source:
                errors.append(f"{name}: {relative} lost its enforcement marker: {marker!r}")

    floor = contract.get("assurance_floor_for_act")
    if floor not in ASSURANCE_FLOOR_MARKERS:
        errors.append(f"unsupported assurance floor for ACT: {floor!r}")
    else:
        relative, marker = ASSURANCE_FLOOR_MARKERS[floor]
        source = _read(root, relative)
        if source is None or marker not in source:
            errors.append(f"assurance floor {floor} is not enforced in {relative}")

    if requirements.get("action_credentials_required_only_for_act_execution"):
        source = _read(root, entrypoint) if entrypoint else None
        if source is None:
            errors.append("cannot verify action-credential ownership without the entrypoint")
        else:
            try:
                owners = _credential_owners(source)
            except SyntaxError as exc:
                errors.append(f"{entrypoint}: {exc}")
                owners = []
            if not owners:
                errors.append(f"{entrypoint}: no action-credential reference found to bind to the ACT path")
            for owner in sorted(set(owners)):
                if owner not in ACT_CREDENTIAL_OWNERS:
                    errors.append(f"{entrypoint}: action credentials required outside the ACT path (in {owner})")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    contract = json.loads((ROOT / CONTRACT).read_text(encoding="utf-8"))
    print(
        f"PASS: {len(contract['requirements'])} interaction-surface requirements are contract-bound "
        "to executable fail-closed controls"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
