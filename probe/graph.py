"""The same shape as discogs-filler, reduced to what the two findings need.

    root      load_inventory -> [per record, fanned out] -> report
    record    route_done (reads the world) -> ask_for_grade (pauses) -> list_record

Compare filler/graph.py in discogs-filler. Everything the domain needed --
barcode search, vision, pricing, the join -- is gone. What is kept is the only
structure the findings depend on:

  * a router that reads the database, so the branch taken is a statement about
    the world and not about the graph,
  * a node that pauses for a human,
  * a node AFTER the pause that writes to the world, so "did anything get
    through?" is answerable by looking at the world rather than at a log,
  * dynamic fan-out over an unknown number of records.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt

from probe.world import GRADED, LISTED, OPEN, World

# Set by build(); the nodes are plain functions so the graph file stays readable.
_world: World | None = None


def world() -> World:
    assert _world is not None, "build(world) was not called"
    return _world


class RecordState(TypedDict, total=False):
    item_id: str
    route: str
    grade: str
    listed: Annotated[list[str], operator.add]


class Overall(TypedDict, total=False):
    items: list[str]
    listed: Annotated[list[str], operator.add]


# -- per record -----------------------------------------------------------

def route_done(state: RecordState) -> RecordState:
    """The router that asks the world a question.

    This is the node the whole probe is built around. In ADK it was re-executed
    on resume and chose a different branch, because the world had moved in the
    meantime.
    """
    item_id = state["item_id"]
    world().record_call("route_done", item_id)
    return {"route": world().state_of(item_id)}


def pick(state: RecordState) -> str:
    """Three ways out, as in filler/graph.py.

    LISTED -> nothing to do.
    GRADED -> straight to the listing, WITHOUT a pause. This is the branch the
              ADK finding is about: it never ran, because a sibling was always
              paused and ADK cancelled it.
    OPEN   -> a human has to grade it first.
    """
    route = state.get("route")
    if route == LISTED:
        return "already_done"
    if route == GRADED:
        return "list_record"
    return "ask_for_grade"


def ask_for_grade(state: RecordState) -> RecordState:
    """Condition cannot be seen on a photo -- a human decides. This pauses."""
    item_id = state["item_id"]
    world().record_call("ask_for_grade", item_id)
    answer = interrupt({"item_id": item_id, "question": "media condition?"})
    return {"grade": answer}


def list_record(state: RecordState) -> RecordState:
    """Runs AFTER the pause and moves the world. The ADK run never got here."""
    item_id = state["item_id"]
    world().record_call("list_record", item_id)
    world().mark_listed(item_id)
    return {"listed": [item_id]}


def already_done(state: RecordState) -> RecordState:
    world().record_call("already_done", state["item_id"])
    return {}


def record_graph():
    g = StateGraph(RecordState)
    g.add_node("route_done", route_done)
    g.add_node("ask_for_grade", ask_for_grade)
    g.add_node("list_record", list_record)
    g.add_node("already_done", already_done)
    g.add_edge(START, "route_done")
    g.add_conditional_edges("route_done", pick, ["ask_for_grade", "list_record", "already_done"])
    g.add_edge("ask_for_grade", "list_record")
    g.add_edge("list_record", END)
    g.add_edge("already_done", END)
    return g.compile()


# -- the whole run --------------------------------------------------------

def load_inventory(state: Overall) -> Overall:
    world().record_call("load_inventory", "-")
    return {}


def fan_out(state: Overall):
    """Dynamic fan-out. How many records there are is only clear at runtime."""
    return [Send("per_record", {"item_id": i}) for i in state["items"]]


def report(state: Overall) -> Overall:
    world().record_call("report", "-")
    return {}


def build(w: World, checkpointer):
    global _world
    _world = w
    g = StateGraph(Overall)
    g.add_node("load_inventory", load_inventory)
    g.add_node("per_record", record_graph())
    g.add_node("report", report)
    g.add_edge(START, "load_inventory")
    g.add_conditional_edges("load_inventory", fan_out, ["per_record"])
    g.add_edge("per_record", "report")
    g.add_edge("report", END)
    return g.compile(checkpointer=checkpointer)
