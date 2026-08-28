"""Reading the data folder into graph inputs.

The folder is the whole contract. Point DATA_DIR somewhere else and the
workflow runs against different evidence with no code change — which is what
makes it rerunnable rather than a demo of one particular quarter.
"""

from __future__ import annotations

from .config import Settings
from .evidence import load_evidence, parse_field_table
from .understand import Cache
from .graph.state import initial_state


def load_workspace(settings: Settings) -> dict:
    """Whatever is currently in the data folder, including nothing.

    The setup screen has to render before anyone has uploaded an objective
    record — that is how files arrive, rather than from a committed pack.
    """
    objective: dict[str, str] = {}
    if settings.objective_file.exists():
        objective = parse_field_table(
            settings.objective_file.read_text(encoding="utf-8")
        )

    prior_update: dict[str, str] = {}
    if settings.prior_update_file.exists():
        prior_update = parse_field_table(
            settings.prior_update_file.read_text(encoding="utf-8")
        )

    return {
        "objective": objective,
        "prior_update": prior_update,
        "docs": load_evidence(
            settings.evidence_dir, cache=Cache(settings.understanding_dir)
        ),
    }


def load_inputs(settings: Settings) -> dict:
    workspace = load_workspace(settings)
    if not settings.objective_file.exists():
        raise FileNotFoundError(
            f"no objective record at {settings.objective_file}. "
            "Upload one from the browser and mark it as the Objective record, "
            "or load the demo pack."
        )

    return initial_state(
        quarter=settings.quarter,
        objective=workspace["objective"],
        prior_update=workspace["prior_update"],
        docs=workspace["docs"],
    )
