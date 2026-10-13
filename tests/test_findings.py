"""The three findings, pinned.

These tests exist so a change in LangGraph that moves any of them fails loudly
instead of quietly making the README wrong.
"""

from __future__ import annotations

import pathlib

import pytest

from experiments import e1_replay, e2_siblings


@pytest.fixture(scope="module")
def e1(tmp_path_factory) -> dict:
    return e1_replay.run(tmp_path_factory.mktemp("e1"))


@pytest.fixture(scope="module")
def e2(tmp_path_factory) -> dict:
    return e2_siblings.run(tmp_path_factory.mktemp("e2"))


# -- Finding 1 -------------------------------------------------------------

def test_der_router_wird_nach_der_pause_nicht_erneut_ausgefuehrt(e1):
    """The ADK failure cannot occur here, because the router does not re-run.

    This is the whole difference. ADK replays the invocation and re-executes
    the routers; LangGraph restores the decision from the checkpoint. A router
    that reads the world therefore cannot diverge, because it is not asked
    twice.
    """
    assert e1["router_calls"] == {"a": 1, "b": 1, "c": 1}


def test_der_lauf_ueberlebt_eine_welt_die_sich_waehrend_der_pause_bewegt(e1):
    """"b" was listed from outside while the graph was paused."""
    assert e1["crashed"] is False
    assert e1["finished"] is True
    assert e1["took_changed_branch"] == {"a": 0, "b": 0, "c": 0}
    assert e1["world_at_end"] == ["a", "b", "c"]


# -- Finding 2 -------------------------------------------------------------

def test_ein_pausierter_zweig_bricht_seine_geschwister_nicht_ab(e2):
    """ADK: nothing got through. Here: everything that could, did."""
    assert e2["paused"] == ["r07"]
    assert e2["siblings_listed"] == e2["siblings_expected"] == 18
    assert e2["missing"] == []


# -- Finding 3 -- the one that costs something -----------------------------

def test_der_pausierende_knoten_selbst_laeuft_zweimal(e1):
    """LangGraph re-executes the INTERRUPTED NODE from its first line.

    `interrupt()` does not suspend a coroutine -- on resume the node function is
    called again and `interrupt()` returns the answer instead of raising. Every
    side effect placed BEFORE that call therefore happens twice.

    The probe shows it directly: `ask_for_grade` logs a call and then
    interrupts, and the log holds two entries per record for one question.

    So the replay problem is not gone, it is bounded: ADK replays the path,
    LangGraph replays the node. The blast radius differs, the discipline does
    not -- nothing that must happen once belongs above an interrupt().
    """
    assert e1["pause_node_calls"] == {"a": 2, "b": 2, "c": 2}
    # and the node after the pause stays exactly-once
    assert e1["after_pause_calls"] == {"a": 1, "b": 1, "c": 1}
