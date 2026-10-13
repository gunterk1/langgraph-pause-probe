# langgraph-pause-probe

A controlled probe, not an application. It takes two limits I measured in
**Google ADK 2.0** while building [discogs-filler](https://github.com/gunterk1/discogs-filler),
rebuilds the exact graph shape they depend on in **LangGraph**, and measures
what happens there.

The honest short version: **both limits are gone, and a third one takes their
place.** The third is the interesting one.

---

## Where this comes from

discogs-filler turns photos of records into Discogs listings. Its graph pauses
in one place, because the condition of a record cannot be seen on a photo — a
human has to grade it. Keeping that pause inside the ADK graph dragged in two
problems that had nothing to do with the task, and both are written up in that
repository:

> **Replay divergence.** On resume, ADK replays the invocation and expects every
> node to take the same path as before. But the routers here read the database —
> *"is this record already listed?"* is a question about the world, not about the
> graph. The world changes between question and answer, the router picks a
> different branch, and the run dies with `Replay divergence detected`.

> **Cancelled sibling branches.** As soon as one branch pauses, ADK cancels all
> the others — including the ones that were about to create a listing. With
> nineteen records, one is always paused, so nothing ever got through.

`RequestInput` came back out. The nodes file their question and finish;
answering and listing happen outside the graph. That works, but it meant giving
up resumable runs, so the question stayed open: **is this the framework, or is
it the shape of the problem?**

This repository answers that for LangGraph.

## What was rebuilt, and what was thrown away

`probe/graph.py` keeps only the structure the findings depend on:

```
root      load_inventory -> [per record, fanned out] -> report
record    route_done (reads the world) -> ask_for_grade (pauses) -> list_record
```

Compare `filler/graph.py` in the original. Barcode search, vision, pricing, the
join over two price sources — all gone. What is kept:

* a **router that reads the database**, so the branch taken is a statement about
  the world and not about the graph,
* a node that **pauses** for a human,
* a node **after** the pause that **writes to the world**, so *"did anything get
  through?"* is answerable by looking at the world instead of reading a log,
* **dynamic fan-out** over a number of records only known at runtime,
* the same three-way route as the original — `LISTED` is skipped, `GRADED` goes
  straight to the listing **without pausing**, `OPEN` needs a human first. That
  `GRADED` branch is the one the second ADK finding is about.

Node executions are logged **into the database**, not into memory. A counter in
memory is reset by the resume and would answer a different question than the one
being asked.

## Finding 1 — the world may move during the pause

`experiments/e1_replay.py`: three records, all open, all paused for a human.
While they wait, one of them is listed **from outside** — the world moves
underneath the graph. Then the run resumes.

| | |
|---|---|
| paused | `a`, `b`, `c` |
| **router executions per record** | **1, 1, 1** |
| took the now-different branch | 0, 0, 0 |
| crashed | **no** |
| finished | yes — world ends as `a`, `b`, `c` |

**The router runs exactly once.** That is the whole difference. ADK replays the
invocation and re-executes the routers, so a router reading the world can
diverge. LangGraph restores the decision from the checkpoint and never asks
again — so it *cannot* diverge, because it is not asked twice.

Worth being precise about what this does and does not say: LangGraph does not
*solve* the stale-decision problem, it *avoids* it by not re-deciding. The
decision taken before the pause is simply kept, even though the world has moved
on. For this graph that is correct and the run completes. For a graph where the
stale branch would be wrong, the staleness is now **silent** rather than loud —
there is no `Replay divergence detected` to tell you about it.

## Finding 2 — a paused branch does not take its siblings down

`experiments/e2_siblings.py`: nineteen records, eighteen already graded and
needing nothing but a listing, one still open and therefore pausing.

| | ADK 2.0 | LangGraph 1.2 |
|---|---|---|
| records | 19 | 19 |
| branches paused | 1 | 1 |
| **siblings that reached the listing** | **0** | **18 of 18** |

Nothing missing. The eighteen graded records are listed while the nineteenth
waits for a human. This is exactly the case that made the original give up on
in-graph pausing.

## Finding 3 — the node that pauses runs twice

This is the one that costs something, and it is why this repository exists
rather than a one-line note saying *"LangGraph handles it."*

`interrupt()` does not suspend a coroutine. On resume **the node function is
called again from its first line**, and this time `interrupt()` returns the
answer instead of raising. Every side effect placed **before** that call
therefore happens twice.

The probe shows it directly — `ask_for_grade` logs a call and then interrupts:

| node | executions per record, for one question |
|---|---|
| `route_done` (before the pause, different node) | 1 |
| **`ask_for_grade` (the pausing node itself)** | **2** |
| `list_record` (after the pause) | 1 |

So the replay problem is not gone. It is **bounded**: ADK replays the path,
LangGraph replays the node. The blast radius differs by orders of magnitude —
but the discipline does not. **Nothing that must happen once belongs above an
`interrupt()`.** A charge, an email, an API write placed there will happen twice
and nothing will warn you.

In the original that discipline was enforced by the architecture, because the
state machine lived in its own database and the graph ended at the question.
Here it has to be enforced by hand.

## Side observation — the branches are threads

Found by having it break: a single shared `sqlite3` connection fails inside the
fanned-out branches with `sqlite3.InterfaceError: bad parameter or other API
misuse`. It is a race, so it survived the first run and blew up on the second.
LangGraph runs fanned-out branches in a real thread pool — they are not
cooperatively scheduled. `probe/world.py` therefore keeps one connection per
thread, and says so where it does it.

## Running it

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt && pip install -e .
python experiments/e1_replay.py
python experiments/e2_siblings.py
pytest -q                      # 4 tests, they pin the three findings
```

No API keys, no network, no model calls. Everything is local SQLite.

## Scope — what this is not

* **Not a benchmark.** Two specific behaviours, one graph shape.
* **Not a verdict on either framework.** ADK's replay model buys determinism
  that this probe does not test for and does not credit it with.
* **Version-bound.** Measured against the versions in `requirements.txt`:
  LangGraph 1.2.15, langgraph-checkpoint-sqlite 3.1.2, Python 3.14.4 — against
  `google-adk[db]>=2.9.0` as pinned by discogs-filler. The tests exist so a
  change that moves any finding fails loudly instead of quietly making this
  page wrong.
* **No production claim.** This is a probe written to answer one question I had
  left open, and the answer is in the three sections above.
