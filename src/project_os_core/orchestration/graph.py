from __future__ import annotations

from ..database import CanonicalDatabase, dump_json
from ..models import (
    AgentRole,
    ExecutionCheckpoint,
    ExecutionTicket,
    GraphState,
    MissionRun,
    RoleHandoff,
    RoutingAssignment,
    RoutingDecision,
    WorkerDispatchEnvelope,
    WorkerRequest,
    new_id,
    to_jsonable,
)
from ..runtime.journal import LocalJournal


CANONICAL_ROLE_SEQUENCE: list[AgentRole] = [
    AgentRole.OPERATOR_CONCIERGE,
    AgentRole.PLANNER,
    AgentRole.MEMORY_CURATOR,
    AgentRole.CRITIC,
    AgentRole.GUARDIAN,
    AgentRole.EXECUTOR_COORDINATOR,
]


class CanonicalMissionGraph:
    """Owns the six-role mission graph contract before the LangGraph adapter is added."""

    def __init__(self, *, database: CanonicalDatabase, journal: LocalJournal) -> None:
        self.database = database
        self.journal = journal

    def prepare_execution(
        self,
        *,
        mission_run: MissionRun,
        decision: RoutingDecision,
    ) -> dict[str, object]:
        if not decision.allowed:
            raise ValueError("Cannot prepare execution for a blocked routing decision")
        if not decision.chosen_worker:
            raise ValueError("Routing decision must choose a worker before execution")

        graph_state = GraphState(
            graph_state_id=new_id("graph_state"),
            mission_run_id=mission_run.mission_run_id,
            objective=mission_run.objective,
            active_role=AgentRole.EXECUTOR_COORDINATOR,
            status=mission_run.status.value,
            role_sequence=[role.value for role in CANONICAL_ROLE_SEQUENCE],
            metadata={"profile_name": mission_run.profile_name},
        )
        handoffs = self._build_handoffs(mission_run.mission_run_id)
        checkpoint = ExecutionCheckpoint(
            execution_checkpoint_id=new_id("exec_checkpoint"),
            mission_run_id=mission_run.mission_run_id,
            role=AgentRole.EXECUTOR_COORDINATOR,
            label="execution_ticket_issued",
            payload={"decision_id": decision.decision_id, "worker_kind": decision.chosen_worker},
        )
        assignment = RoutingAssignment(
            assignment_id=new_id("assignment"),
            mission_run_id=mission_run.mission_run_id,
            decision_id=decision.decision_id,
            worker_kind=decision.chosen_worker,
            execution_class=decision.execution_class,
            model_route=decision.model_route,
        )
        ticket = ExecutionTicket(
            ticket_id=new_id("ticket"),
            mission_run_id=mission_run.mission_run_id,
            assignment_id=assignment.assignment_id,
            worker_kind=assignment.worker_kind,
            action_name="execute_mission",
            payload={
                "objective": mission_run.objective,
                "profile_name": mission_run.profile_name,
                "routing_decision_id": decision.decision_id,
            },
            policy_verdict=decision.route_reason,
        )
        worker_request = WorkerRequest(
            request_id=new_id("worker_req"),
            worker_kind=ticket.worker_kind,
            action_name=ticket.action_name,
            payload=ticket.payload,
        )
        dispatch_envelope = WorkerDispatchEnvelope(
            dispatch_id=new_id("worker_dispatch"),
            ticket=ticket,
            worker_request=worker_request,
            metadata={"issued_by": AgentRole.EXECUTOR_COORDINATOR.value},
        )

        self._persist_graph_state(graph_state)
        for handoff in handoffs:
            self._persist_handoff(handoff)
        self._persist_checkpoint(checkpoint)
        self._persist_assignment(assignment)
        self._persist_ticket(ticket)
        self._persist_dispatch(dispatch_envelope)
        self.journal.append(
            "execution_ticket_issued",
            "orchestration",
            {
                "mission_run_id": mission_run.mission_run_id,
                "decision_id": decision.decision_id,
                "ticket_id": ticket.ticket_id,
                "worker_kind": ticket.worker_kind,
            },
        )
        return {
            "graph_state": graph_state,
            "handoffs": handoffs,
            "checkpoint": checkpoint,
            "assignment": assignment,
            "ticket": ticket,
            "worker_dispatch_envelope": dispatch_envelope,
        }

    def _build_handoffs(self, mission_run_id: str) -> list[RoleHandoff]:
        handoffs: list[RoleHandoff] = []
        previous = None
        for role in CANONICAL_ROLE_SEQUENCE:
            handoffs.append(
                RoleHandoff(
                    handoff_id=new_id("handoff"),
                    mission_run_id=mission_run_id,
                    from_role=previous,
                    to_role=role,
                    reason="canonical_graph_progression",
                    payload={"role": role.value},
                )
            )
            previous = role
        return handoffs

    def _persist_graph_state(self, graph_state: GraphState) -> None:
        self.database.execute(
            """
            INSERT OR REPLACE INTO graph_states(
                graph_state_id, mission_run_id, objective, active_role, status, role_sequence_json,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                graph_state.graph_state_id,
                graph_state.mission_run_id,
                graph_state.objective,
                graph_state.active_role.value,
                graph_state.status,
                dump_json(graph_state.role_sequence),
                dump_json(graph_state.metadata),
                graph_state.created_at,
            ),
        )

    def _persist_handoff(self, handoff: RoleHandoff) -> None:
        self.database.execute(
            """
            INSERT OR REPLACE INTO role_handoffs(
                handoff_id, mission_run_id, from_role, to_role, reason, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                handoff.handoff_id,
                handoff.mission_run_id,
                handoff.from_role.value if handoff.from_role else None,
                handoff.to_role.value,
                handoff.reason,
                dump_json(handoff.payload),
                handoff.created_at,
            ),
        )

    def _persist_checkpoint(self, checkpoint: ExecutionCheckpoint) -> None:
        self.database.execute(
            """
            INSERT OR REPLACE INTO execution_checkpoints(
                execution_checkpoint_id, mission_run_id, role, label, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                checkpoint.execution_checkpoint_id,
                checkpoint.mission_run_id,
                checkpoint.role.value,
                checkpoint.label,
                dump_json(checkpoint.payload),
                checkpoint.created_at,
            ),
        )

    def _persist_assignment(self, assignment: RoutingAssignment) -> None:
        self.database.execute(
            """
            INSERT OR REPLACE INTO routing_assignments(
                assignment_id, mission_run_id, decision_id, worker_kind, execution_class,
                model_route_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                assignment.assignment_id,
                assignment.mission_run_id,
                assignment.decision_id,
                assignment.worker_kind,
                assignment.execution_class.value,
                dump_json(to_jsonable(assignment.model_route)),
                assignment.created_at,
            ),
        )

    def _persist_ticket(self, ticket: ExecutionTicket) -> None:
        self.database.execute(
            """
            INSERT OR REPLACE INTO execution_tickets(
                ticket_id, mission_run_id, assignment_id, worker_kind, action_name,
                payload_json, policy_verdict, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticket.ticket_id,
                ticket.mission_run_id,
                ticket.assignment_id,
                ticket.worker_kind,
                ticket.action_name,
                dump_json(ticket.payload),
                ticket.policy_verdict,
                ticket.status,
                ticket.created_at,
            ),
        )

    def _persist_dispatch(self, envelope: WorkerDispatchEnvelope) -> None:
        self.database.execute(
            """
            INSERT OR REPLACE INTO worker_dispatch_envelopes(
                dispatch_id, ticket_id, worker_request_json, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                envelope.dispatch_id,
                envelope.ticket.ticket_id,
                dump_json(to_jsonable(envelope.worker_request)),
                dump_json(envelope.metadata),
                envelope.created_at,
            ),
        )
