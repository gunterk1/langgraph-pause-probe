"""E1 -- Does the world moving during a pause kill the run?

discogs-filler, ADK 2.0:

    On resume, ADK replays the invocation and expects every node to take the
    same path as before. The routers read the database, the world changes
    between question and answer, the router picks a different branch, and the
    run dies with `Replay divergence detected`.

The probe reproduces the setup exactly: three records, all OPEN, all pausing
for a human. While they are paused, one of them is listed FROM OUTSIDE -- the
world moves. Then the run is resumed.

What is counted is how often each node actually executed, logged to the
database rather than to memory, because a counter in memory would be reset by
the resume and would answer the wrong question.
"""

from __future__ import annotations

import pathlib
import tempfile

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from probe import graph as G
from probe.world import World

ITEMS = ["a", "b", "c"]


def run(tmp: pathlib.Path) -> dict:
    world = World(tmp / "world.db")
    world.seed(ITEMS)
    with SqliteSaver.from_conn_string(str(tmp / "cp.db")) as cp:
        app = G.build(world, cp)
        cfg = {"configurable": {"thread_id": "e1"}}

        first = app.invoke({"items": ITEMS}, cfg)
        interrupts = first.get("__interrupt__", [])

        # The world moves while the graph is paused: "b" is listed by someone
        # else. A re-executed router would now take a different branch.
        world.mark_listed("b")

        second = app.invoke(Command(resume={i.id: "VG+" for i in interrupts}), cfg)

        return {
            "paused": sorted(i.value["item_id"] for i in interrupts),
            "crashed": False,
            "router_calls": {i: world.calls("route_done", i) for i in ITEMS},
            "pause_node_calls": {i: world.calls("ask_for_grade", i) for i in ITEMS},
            "after_pause_calls": {i: world.calls("list_record", i) for i in ITEMS},
            "took_changed_branch": {i: world.calls("already_done", i) for i in ITEMS},
            "finished": not second.get("__interrupt__"),
            "world_at_end": world.listed(),
        }


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        for k, v in run(pathlib.Path(d)).items():
            print(f"{k:20} {v}")
