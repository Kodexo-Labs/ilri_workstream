"""Reading the data folder into graph inputs.

The folder is the whole contract. Point DATA_DIR somewhere else and the
workflow runs against different evidence with no code change — which is what
makes it rerunnable rather than a demo of one particular quarter.
"""

from __future__ import annotations

from pathlib import Path

from .config import Settings
from .evidence import complete_objective_fields, load_evidence, parse_field_table
from .store import assigned_paths, objective_path, prior_path
from .understand import Cache
from .graph.state import initial_state


def load_workspace(settings: Settings) -> dict:
    """Whatever is currently in the data folder, including nothing.

    The setup screen has to render before anyone has uploaded an objective
    record — that is how files arrive, rather than from a committed pack.
    """
    objective: dict[str, str] = {}
    obj = objective_path(settings)
    if obj is not None:
        text = obj.read_text(encoding="utf-8")
        objective = complete_objective_fields(text, parse_field_table(text))

    prior_update: dict[str, str] = {}
    prior = prior_path(settings)
    if prior is not None:
        prior_update = parse_field_table(prior.read_text(encoding="utf-8"))

    skip = assigned_paths(settings)
    docs = [
        doc
        for doc in load_evidence(
            settings.evidence_dir, cache=Cache(settings.understanding_dir)
        )
        if _doc_path(doc) not in skip
    ]

    return {
        "objective": objective,
        "prior_update": prior_update,
        "docs": docs,
    }


def _doc_path(doc) -> Path:
    try:
        return Path(doc.source_path).resolve()
    except OSError:
        return Path(doc.source_path)


def load_inputs(settings: Settings) -> dict:
    workspace = load_workspace(settings)
    if objective_path(settings) is None:
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
