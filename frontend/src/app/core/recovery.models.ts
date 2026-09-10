export type RecoveryStatus =
  | 'DETECTED'
  | 'ASSESSING'
  | 'PLANNING'
  | 'EXECUTING'
  | 'WAITING_FOR_RESPONSE'
  | 'REPLANNING'
  | 'APPROVAL_REQUIRED'
  | 'RESOLVED'
  | 'FAILED';

export type MoneyValue = string | number;

export interface CoverageWindow {
  start: string;
  end: string;
}

export interface CoverageSegment {
  segment_id: string;
  window: CoverageWindow;
  assigned_person_id: string;
  source: 'CAREGIVER' | 'PARENT';
  segment_type?: 'CARE' | 'TRANSPORT';
  location_id?: string;
  location_label?: string;
  destination_location_id?: string | null;
  destination_location_label?: string | null;
  transporter_id?: string | null;
  estimated_cost: MoneyValue;
}

export interface CalendarChange {
  event_id: string;
  owner_id: string;
  title: string;
  window: CoverageWindow;
  location: string | null;
}

export interface RecoveryPlan {
  plan_id: string;
  coverage_segments: CoverageSegment[];
  calendar_changes: CalendarChange[];
  estimated_cost: MoneyValue;
  validation_state: 'NOT_VALIDATED' | 'VALID' | 'INVALID';
  validation_errors: string[];
}

export interface RecoveryPlanSummary {
  plan_id: string;
  validation_state: 'NOT_VALIDATED' | 'VALID' | 'INVALID';
  estimated_cost: MoneyValue;
  coverage_segment_count: number;
}

export interface RecoveryEvent {
  event_id: string;
  event_type: string;
  occurred_at: string;
  caregiver_id: string | null;
  relevant_window: CoverageWindow | null;
  message: string | null;
  details: Record<string, unknown>;
}

export interface InvalidatedAssumption {
  assumption_id: string;
  assumption_type: string;
  subject_id: string;
  relevant_window: CoverageWindow | null;
  status: 'INVALIDATED';
  invalidated_at: string | null;
  invalidation_reason: string | null;
  triggering_event_id: string | null;
}

export interface ApprovalRequest {
  approval_id: string;
  approval_type: string;
  plan_id: string;
  reason: string;
  summary: string;
  consequence: string;
  requested_at: string;
  status: 'PENDING' | 'APPROVED' | 'REJECTED';
  amount: MoneyValue | null;
  currency: string | null;
  decided_at: string | null;
}

export interface ExecutionAction {
  action_id: string;
  action_type: 'RESERVE_CAREGIVER' | 'UPDATE_CALENDAR';
  target_id: string;
  plan_id: string;
  status: 'PENDING' | 'SUCCEEDED' | 'FAILED';
  attempted_at: string;
  completed_at: string | null;
  result: string | null;
  error: string | null;
}

export interface RecoveryCase {
  recovery_case_id: string;
  status: RecoveryStatus;
  original_disruption: {
    disruption_type: string;
    occurred_at: string;
    caregiver_id: string;
    message: string;
  };
  active_plan: RecoveryPlan | null;
  plan_history: RecoveryPlanSummary[];
  previous_plans: RecoveryPlan[];
  events: RecoveryEvent[];
  invalidated_assumptions: InvalidatedAssumption[];
  pending_approval: ApprovalRequest | null;
  approval_history: ApprovalRequest[];
  execution_actions: ExecutionAction[];
  current_deterministic_cost: MoneyValue;
  requires_approval: boolean;
  automatic_spend_limit: MoneyValue | null;
  currency: string | null;
  latest_trigger: string | null;
  timestamps: {
    created_at: string;
    updated_at: string;
    completion_verified_at: string | null;
  };
  version: number;
}

export interface ApiErrorBody {
  error?: { code?: string; message?: string };
}

export interface CreateRecoveryRequest {
  disruption_type: 'CHILDCARE_UNAVAILABLE';
  occurred_at: string;
  caregiver_id: string;
  message: string;
}

export interface ExternalEventRequest {
  event_type: 'CAREGIVER_DECLINED';
  caregiver_id: string;
  occurred_at: string;
  relevant_window: CoverageWindow;
  message: string;
  expected_version: number;
}

export interface ApprovalDecisionRequest {
  decision: 'APPROVE' | 'REJECT';
  reason?: string;
  expected_version: number;
}

export type ProgressActorType = 'AGENT' | 'DETERMINISTIC_SERVICE' | 'HUMAN' | 'SYSTEM';
export type ProgressStatus = 'WAITING' | 'ACTIVE' | 'COMPLETED' | 'WARNING' | 'FAILED';

export interface RecoveryProgressEvent {
  id: string;
  progress_id: string;
  recovery_case_id: string | null;
  sequence: number;
  timestamp: string;
  event_type: string;
  actor_type: ProgressActorType;
  actor_name: string;
  stage: string;
  status: ProgressStatus;
  summary: string;
  details: {
    action_id?: string;
    action_type?: string;
    affected_windows?: string[];
    attempt_number?: number;
    candidate_count?: number;
    cost?: MoneyValue;
    eligible_candidate_count?: number;
    invalidated_count?: number;
    issue_codes?: string[];
    issue_count?: number;
    operation?: string;
    orchestrator_invocation_count?: number;
    plan_id?: string;
    planner_invocation_count?: number;
    preserved_count?: number;
    recommended_candidate_id?: string;
    research_agent_invocation_count?: number;
    requires_approval?: boolean;
    success?: boolean;
  };
}
