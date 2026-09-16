"""Set Agent — the advisory layer (spec B-7..B-10, Part E).

Three rules hold everywhere in this package:

1. The agent never mutates a Set Draft. It produces a ChangeSet; the user applies it.
2. Numbers come from the analysis engines, never from an LLM and never from arithmetic
   done in a prompt.
3. Track suggestions are real rows from the user's library. Nothing invents a title.
"""
from setagent.agent.changeset import ChangeSet, Op, Proposal, build_change_set
from setagent.agent.tools import AgentTools

__all__ = ["ChangeSet", "Op", "Proposal", "build_change_set", "AgentTools"]
