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
    if (this.busy()) return { ...base, title: 'Adjusting your day.', description: 'The current request is in progress. Your recorded schedule stays here while DayMend works.' };
    if (recovery?.approval_history.at(-1)?.status === 'REJECTED') {
      return {
        ...base,
        eyebrow: 'Decision recorded',
        title: 'Recovery not approved',
        description: 'The proposed alternative was not applied. Your still-valid coverage remains in place.',
        tone: 'attention' as const,
      };
    }
    if (recovery?.status === 'APPROVAL_REQUIRED') return { ...base, title: 'One decision needs you.', description: 'The proposed plan is ready. Review the care and spending below.' };
    if (recovery?.status === 'RESOLVED') return { ...base, title: 'Your day is recovered.', description: 'Completion verified within the demo scenario and simulated execution results.' };
    return base;
  });
}
