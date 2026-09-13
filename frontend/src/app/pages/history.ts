import { Component, inject } from '@angular/core';
import { CurrencyPipe, DatePipe } from '@angular/common';
import { RecoveryStore } from '../core/recovery.store';
import { RECOVERY_STATUS_COPY, friendlyPerson } from '../core/recovery-status';
import { PlanChangeComponent } from '../components/plan-change/plan-change';
import { CoveragePlanComponent } from '../components/coverage-plan/coverage-plan';
import { LiveRecoveryComponent } from '../components/live-recovery/live-recovery';

@Component({
  selector: 'app-history',
  imports: [CurrencyPipe, DatePipe, PlanChangeComponent, CoveragePlanComponent, LiveRecoveryComponent],
  template: `
    <header class="page-heading"><p class="eyebrow">Your recoveries</p><h1>A day worth keeping.</h1>
    <p class="muted">This browser can reopen its saved recovery. A list of other saved cases is not available.</p></header>
    @if (store.currentCase(); as recovery) {
      <article class="open-section">
        <p>{{ recovery.timestamps.created_at | date:'longDate' }}</p>
        <h2>{{ friendlyPerson(recovery.original_disruption.caregiver_id) }} unavailable</h2>
        <p>{{ recovery.original_disruption.message }}</p>
        <p>{{ copy[recovery.status].eyebrow }} · {{ recovery.current_deterministic_cost | currency: recovery.currency ?? 'USD':'symbol':'1.2-2' }}</p>
        <p>{{ recovery.pending_approval || recovery.approval_history.length ? 'Approval requested for this recovery' : 'No approval request recorded' }}</p>
        <details><summary>Open recovery · read only</summary>
          @if (recovery.family_policy_snapshot; as policy) {
            <section class="open-section"><h3>Rules at recovery time</h3>
              <p>Automatic spend limit: {{ policy.automatic_spend_limit | currency: policy.currency:'symbol':'1.2-2' }}</p>
              <p>Unfamiliar paid providers: {{ policy.require_approval_for_unfamiliar_paid_caregiver ? 'approval required' : 'no separate unfamiliar-provider approval' }}</p>
              <p>External providers {{ policy.allow_external_backup_providers ? 'allowed' : 'disabled' }} · provider transport {{ policy.allow_provider_transport ? 'allowed' : 'disabled' }}</p>
              <p class="muted">Family profile version {{ recovery.family_profile_version }}. This snapshot is read only.</p>
            </section>
          }
          @if (recovery.active_plan; as plan) {
            @if (recovery.previous_plans.length) { <app-plan-change [recovery]="recovery" /> }
            @else { <app-coverage-plan [plan]="plan" [currency]="recovery.currency ?? 'USD'" /> }
          }
          <section class="open-section"><h3>Your decision</h3>
          @for (approval of recovery.approval_history; track approval.approval_id) { <p>{{ approval.status }} · {{ approval.amount | currency: approval.currency ?? recovery.currency ?? 'USD':'symbol':'1.2-2' }} · {{ approval.decided_at | date:'medium' }}</p> }
          @empty { <p>{{ recovery.pending_approval ? 'Awaiting approval. Return to Today to decide.' : 'No decision recorded.' }}</p> }
          </section>
          <section class="open-section"><h3>Execution results</h3>
            @for (action of recovery.execution_actions; track action.action_id) {
              <p>{{ action.action_type === 'RESERVE_CAREGIVER' ? 'Reserve care' : 'Update calendar' }} · {{ friendlyPerson(action.target_id) }} · {{ action.status }}<br>{{ action.result || action.error }}</p>
            } @empty { <p>No execution actions recorded.</p> }
            @if (recovery.timestamps.completion_verified_at) { <p>Completion verified · {{ recovery.timestamps.completion_verified_at | date:'medium' }}</p> }
          </section>
          <details><summary>Recorded case events</summary>
            <ol>@for (event of recovery.events; track event.event_id) { <li>{{ event.occurred_at | date:'medium' }} · {{ event.message || event.event_type.replaceAll('_', ' ').toLowerCase() }}</li> }</ol>
          </details>
          <app-live-recovery [events]="store.progressEvents()" [recovery]="recovery" />
        </details>
      </article>
    } @else { <p>{{ store.loading() ? 'Loading the saved recovery…' : 'No recovery is available in this browser yet.' }}</p> }
    @if (store.error()) { <p role="alert">{{ store.error() }}</p> }
  `,
})
export class HistoryPage {
  readonly store = inject(RecoveryStore);
  readonly copy = RECOVERY_STATUS_COPY;
  readonly friendlyPerson = friendlyPerson;
}
