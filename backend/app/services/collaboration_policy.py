from datetime import datetime, timezone

from app.models.collaboration_run import CollaborationRun

RUN_STATUS_RUNNING = "running"
RUN_STATUS_BLOCKED = "blocked"
RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_STOPPED = "stopped"
RUN_STATUS_FAILED = "failed"

REVIEW_BLOCKING_STATUSES = {"blocked", "revise", "changes_requested"}
REVIEW_APPROVED_STATUSES = {"approved"}
DECISION_COMPLETED_STATUSES = {"completed", "approved"}
DECISION_BLOCKED_STATUSES = {"blocked", "revise", "changes_requested"}


def touch_run(run: CollaborationRun) -> None:
    run.updated_at = datetime.now(timezone.utc)


def stop_run(run: CollaborationRun, status: str, reason: str) -> None:
    run.status = status
    run.stop_reason = reason
    touch_run(run)


def register_step(run: CollaborationRun) -> None:
    run.step_count += 1
    touch_run(run)


def register_review_round(run: CollaborationRun) -> None:
    run.review_round_count += 1
    touch_run(run)


def should_stop_for_limits(run: CollaborationRun) -> str | None:
    if run.step_count >= run.max_steps:
        return "max_steps_reached"
    if run.review_round_count >= run.max_review_rounds:
        return "max_review_rounds_reached"
    return None


def finalize_run_from_artifact(
    run: CollaborationRun,
    artifact_type: str | None,
    artifact_status: str | None,
) -> None:
    if artifact_type == "decision":
        if artifact_status in DECISION_COMPLETED_STATUSES:
            stop_run(run, RUN_STATUS_COMPLETED, "decision_completed")
        elif artifact_status in DECISION_BLOCKED_STATUSES:
            stop_run(run, RUN_STATUS_BLOCKED, f"decision_{artifact_status}")
        return

    if artifact_type == "review":
        if artifact_status in REVIEW_BLOCKING_STATUSES:
            stop_run(run, RUN_STATUS_BLOCKED, f"review_{artifact_status}")
        elif artifact_status in REVIEW_APPROVED_STATUSES:
            touch_run(run)
