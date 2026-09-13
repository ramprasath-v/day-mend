import { DatePipe } from '@angular/common';
import { Component, computed, input, output } from '@angular/core';

import { RecoveryCase } from '../../core/recovery.models';
import { INITIAL_STATUS, RECOVERY_STATUS_COPY } from '../../core/recovery-status';

@Component({
  selector: 'app-recovery-hero',
  imports: [DatePipe],
  templateUrl: './recovery-hero.html',
  styleUrl: './recovery-hero.css',
})
export class RecoveryHeroComponent {
  readonly recovery = input<RecoveryCase | null>(null);
  readonly careDate = input<string | null>(null);
  readonly busy = input(false);
  readonly resetDemo = output<void>();
  readonly money = Number;
  readonly displayedCareDate = computed(
    () =>
      this.recovery()?.active_plan?.coverage_segments?.[0]?.window.start ?? this.careDate(),
  );
  readonly dateLabel = computed(() => {
    const value = this.displayedCareDate();
    if (!value) return 'Care date';
    const careDate = new Date(value);
    const now = new Date();
    return careDate.getFullYear() === now.getFullYear() &&
      careDate.getMonth() === now.getMonth() &&
      careDate.getDate() === now.getDate()
      ? 'Today'
      : 'Care date';
  });
  readonly status = computed(() => {
    const recovery = this.recovery();
    const base = recovery ? RECOVERY_STATUS_COPY[recovery.status] : INITIAL_STATUS;
    if (this.busy()) return {
      ...base,
      title: 'Today changed. DayMend is repairing it.',
      description: 'Your recorded schedule stays visible while DayMend checks the affected care and handoffs.',
    };
    const noOptionEvent = recovery?.events.find(
      (event) => event.details['outcome_code'] === 'NO_RECOVERY_OPTION',
    );
    if (noOptionEvent) {
      const supportingText = noOptionEvent.details['supporting_text'];
      return {
        ...base,
        eyebrow: 'Recovery needs another option',
        title: 'No recovery option is available with your current settings.',
        description:
          typeof supportingText === 'string'
            ? supportingText
            : 'Known caregivers cannot cover the remaining gap with the current family settings.',
        tone: 'attention' as const,
      };
    }
    if (recovery?.approval_history.at(-1)?.status === 'REJECTED') {
      return {
        ...base,
        eyebrow: 'Decision recorded',
        title: 'Recovery not approved',
        description: 'The proposed alternative was not applied. Your still-valid coverage remains in place.',
        tone: 'attention' as const,
      };
    }
    if (recovery?.status === 'APPROVAL_REQUIRED') return {
      ...base,
      title: 'DayMend found a safe alternative.',
      description: 'Everything else is ready. Review the proposed care and spending below.',
    };
    if (recovery?.status === 'RESOLVED') return {
      ...base,
      title: 'Today is covered again.',
      description: 'Completion verified within the demo scenario and simulated execution results.',
    };
    if (recovery?.status === 'WAITING_FOR_RESPONSE') return {
      ...base,
      title: 'Your day has a workable Plan A.',
      description: 'Today’s care is covered, and DayMend can adjust it if another caregiver responds.',
    };
    if (!recovery) return {
      ...base,
      title: 'Your childcare is covered this week.',
      description: "Today’s nanny is scheduled from 8:00 AM to 4:00 PM.",
    };
    return base;
  });
}
