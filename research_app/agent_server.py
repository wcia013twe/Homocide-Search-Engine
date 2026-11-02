"""Databricks Apps HTTP entry point for the first research pass."""
import os
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from research_app.agent_service import run_research
from research_app.research_agent import PADMINI_QUERY
from research_app.research_review import ReviewDecision
from research_app.hosted_session import open_hosted_session, scoped_session_id, SessionBusyError


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(default=PADMINI_QUERY, min_length=1, max_length=1000)
    provider: Literal["Exa", "Brave"] = "Exa"


class SessionRequest(ResearchRequest):
    session_id: UUID


def researcher_identity(request: Request):
    if not os.environ.get("DATABRICKS_APP_NAME"):
        raise HTTPException(503, "Hosted invocation requires the Databricks Apps identity proxy.")
    actor = request.headers.get("x-forwarded-user") or request.headers.get("x-forwarded-email")
    if not actor:
        raise HTTPException(401, "Authenticated researcher identity is required.")
    return actor


def session_output(session, key, actor, public_id):
    snapshot = session.inspect(key, actor)
    state = snapshot.values
    return {"session_id": str(public_id), "status": state.get("status"),
            "search_run_id": state.get("search_run_id"), "search_count": state.get("search_count", 0),
            "search_history": state.get("search_history", []),
            "review_history": state.get("review_history", []),
            "results": [{key: result.get(key) for key in ("result_rank", "title", "url", "snippet", "published_date")}
                        for result in state.get("results", [])],
            "assessments": state.get("triage", {}).get("assessments", []),
            "prompt_version": state.get("triage", {}).get("prompt_version"),
            "pending_review": [item.value for task in snapshot.tasks for item in task.interrupts],
            "stop_reason": state.get("stop_reason"),
            "interrupted_by_error": any(task.error for task in snapshot.tasks)}


app = FastAPI(title="Homicide Research Agent", docs_url=None, redoc_url=None)


@app.get("/health")
def health():
    return {"status": "ok", "workflow": "discovery-triage-v1"}


@app.post("/research")
def research(payload: ResearchRequest, request: Request):
    if not payload.query.strip():
        raise HTTPException(422, "A nonempty query is required.")
    # Trust forwarded identity only inside the Databricks Apps reverse proxy.
    actor = researcher_identity(request)
    try:
        return run_research(payload.query.strip(), payload.provider, actor)
    except Exception as exc:
        # Provider/SDK exceptions may include sensitive URLs or response details.
        raise HTTPException(502, "Research could not finish. Check the configured provider, model, and audit resources.") from exc


@app.post("/sessions")
def start_session(payload: SessionRequest, request: Request):
    actor = researcher_identity(request)
    if not payload.query.strip():
        raise HTTPException(422, "A nonempty query is required.")
    key = scoped_session_id(str(payload.session_id), actor)
    try:
        with open_hosted_session(key) as session:
            current = session.graph.get_state(session._config(key)).values
            if current:
                initial = current.get("search_history", [current])[0]
                if initial["query"] != payload.query.strip() or initial["provider"] != payload.provider:
                    raise HTTPException(409, "Session ID was already used with different search inputs.")
            else:
                session.start(key, actor, payload.query.strip(), payload.provider)
            return session_output(session, key, actor, payload.session_id)
    except HTTPException:
        raise
    except SessionBusyError as exc:
        raise HTTPException(409, "Session is already running; inspect it before retrying.") from exc
    except Exception as exc:
        raise HTTPException(502, "Session could not finish. Inspect its state before retrying.") from exc


@app.get("/sessions/{session_id}")
def inspect_session(session_id: UUID, request: Request):
    actor = researcher_identity(request)
    key = scoped_session_id(str(session_id), actor)
    try:
        with open_hosted_session(key) as session:
            return session_output(session, key, actor, session_id)
    except ValueError as exc:
        raise HTTPException(404, "Session not found.") from exc
    except SessionBusyError as exc:
        raise HTTPException(409, "Session is currently running.") from exc
    except Exception as exc:
        raise HTTPException(502, "Session storage is unavailable.") from exc


@app.post("/sessions/{session_id}/resume")
def resume_session(session_id: UUID, payload: ReviewDecision, request: Request):
    actor = researcher_identity(request)
    key = scoped_session_id(str(session_id), actor)
    try:
        with open_hosted_session(key) as session:
            session.resume(key, actor, payload.model_dump())
            return session_output(session, key, actor, session_id)
    except ValueError as exc:
        raise HTTPException(409, "Review is stale, invalid, or the session is not awaiting review.") from exc
    except SessionBusyError as exc:
        raise HTTPException(409, "Session is already running.") from exc
    except Exception as exc:
        raise HTTPException(502, "Session could not resume. Inspect its state before retrying.") from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("DATABRICKS_APP_PORT", "8000")))
