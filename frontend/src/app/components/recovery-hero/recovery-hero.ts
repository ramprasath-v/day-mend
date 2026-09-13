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
  readonly busy = input(false);
  readonly resetDemo = output<void>();
  readonly money = Number;
  readonly status = computed(() => {
    const recovery = this.recovery();
    const base = recovery ? RECOVERY_STATUS_COPY[recovery.status] : INITIAL_STATUS;
    if (this.busy()) return { ...base, title: 'Adjusting your day.', description: 'The current request is in progress. Your recorded schedule stays here while DayMend works.' };
    if (recovery?.status === 'APPROVAL_REQUIRED') return { ...base, title: 'One decision needs you.', description: 'The proposed plan is ready. Review the care and spending below.' };
    if (recovery?.status === 'RESOLVED') return { ...base, title: 'Your day is recovered.', description: 'Completion verified within the demo scenario and simulated execution results.' };
    return base;
  });
}
