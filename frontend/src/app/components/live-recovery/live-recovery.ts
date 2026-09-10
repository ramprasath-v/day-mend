import { Component, computed, input } from '@angular/core';

import {
  ProgressActorType,
  ProgressStatus,
  RecoveryProgressEvent,
} from '../../core/recovery.models';

interface OrchestrationNode {
  key: string;
  label: string;
  role: ProgressActorType;
  status: ProgressStatus;
  detail: string;
  branch?: boolean;
}

const NODE_DEFINITIONS = [
  { key: 'recovery_orchestrator', label: 'Understanding the change', role: 'AGENT' },
  { key: 'constraint_planner', label: 'Building your plan', role: 'AGENT' },
  { key: 'backup_care_research', label: 'Finding backup care', role: 'AGENT', branch: true },
  { key: 'plan_validator', label: 'Checking every detail', role: 'DETERMINISTIC_SERVICE' },
  { key: 'human_approval', label: 'Your decision', role: 'HUMAN' },
  { key: 'execution_service', label: 'Putting it in place', role: 'DETERMINISTIC_SERVICE' },
  { key: 'completion_verifier', label: 'Final coverage check', role: 'DETERMINISTIC_SERVICE' },
] as const;

@Component({
  selector: 'app-live-recovery',
  templateUrl: './live-recovery.html',
  styleUrl: './live-recovery.css',
})
export class LiveRecoveryComponent {
  readonly events = input<RecoveryProgressEvent[]>([]);
  readonly busy = input(false);
  readonly connected = input(false);
  readonly elapsedSeconds = input(0);

  readonly nodes = computed<OrchestrationNode[]>(() =>
    NODE_DEFINITIONS.map((definition) => {
      const latest = this.events()
        .filter((event) => this.nodeKey(event) === definition.key)
        .at(-1);
      return {
        ...definition,
        status: latest?.status ?? 'WAITING',
        detail: latest?.summary ?? 'Waiting',
      };
    }),
  );

  readonly recentEvents = computed(() => this.events().slice(-9).reverse());
  readonly lastCompleted = computed(() =>
    this.events()
      .filter((event) => event.status === 'COMPLETED')
      .at(-1),
  );

  elapsed(): string {
    const seconds = this.elapsedSeconds();
    return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
  }

  actorLabel(actor: ProgressActorType): string {
    if (actor === 'DETERMINISTIC_SERVICE') return 'DayMend check';
    if (actor === 'HUMAN') return 'You';
    return 'Recovery agent';
  }

  stageLabel(stage: string): string {
    return stage.replaceAll('_', ' ');
  }

  detailItems(event: RecoveryProgressEvent): string[] {
    const details = event.details;
    const items: string[] = [];
    if (details.attempt_number) items.push(`Attempt ${details.attempt_number}`);
    if (details.issue_count !== undefined) {
      items.push(`${details.issue_count} validation issue${details.issue_count === 1 ? '' : 's'}`);
    }
    if (details.issue_codes?.length) items.push(details.issue_codes.join(', '));
    if (details.preserved_count !== undefined) items.push(`${details.preserved_count} preserved`);
    if (details.invalidated_count !== undefined) {
      items.push(`${details.invalidated_count} invalidated`);
    }
    if (details.eligible_candidate_count !== undefined) {
      items.push(`${details.eligible_candidate_count} eligible`);
    }
    if (details.recommended_candidate_id) {
      items.push(this.friendly(details.recommended_candidate_id));
    }
    if (details.action_type) items.push(this.friendly(details.action_type));
    if (details.cost !== undefined) items.push(`$${details.cost}`);
    if (details.orchestrator_invocation_count !== undefined) {
      items.push(`${details.orchestrator_invocation_count} orchestrator invocation`);
    }
    if (details.planner_invocation_count !== undefined) {
      items.push(`${details.planner_invocation_count} planner invocation`);
    }
    if (details.research_agent_invocation_count !== undefined) {
      items.push(`${details.research_agent_invocation_count} research invocation`);
    }
    return items;
  }

  private nodeKey(event: RecoveryProgressEvent): string {
    if (event.event_type.startsWith('APPROVAL_')) return 'human_approval';
    if (event.actor_name === 'deterministic_policy' || event.actor_name === 'user') {
      return 'human_approval';
    }
    if (event.actor_name === 'plan_invalidation') return 'plan_validator';
    if (event.actor_name === 'daymend' && event.event_type === 'RECOVERY_RESOLVED') {
      return 'completion_verifier';
    }
    return event.actor_name;
  }

  private friendly(value: string): string {
    return value
      .toLowerCase()
      .split('_')
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  }
}
