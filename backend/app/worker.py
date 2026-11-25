"""RQ job entry point for solver workers.

Pure: receives a serialised Problem, returns a serialised SolveResult. Workers
need no database credentials (see docs, Figure 1).

Run:  rq worker solve --url $REDIS_URL
"""
from .domain.solver import solve
from .domain.types import Problem


def solve_problem(problem: dict) -> dict:
    return solve(Problem.from_dict(problem)).to_dict()
