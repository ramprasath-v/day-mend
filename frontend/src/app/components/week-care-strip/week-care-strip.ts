import { Component, computed, input } from '@angular/core';

import { RecoveryAction } from '../../core/recovery.store';
import { CoverageWindow, RecoveryCase } from '../../core/recovery.models';

type WeekCareTone = 'scheduled' | 'repairing' | 'proposed' | 'recovered' | 'unresolved';

interface WeekCareDay {
  key: string;
  weekday: string;
  date: string;
  isCareDate: boolean;
  primary: string;
  secondary: string;
  status: string;
  tone: WeekCareTone;
}

@Component({
  selector: 'app-week-care-strip',
  templateUrl: './week-care-strip.html',
  styleUrl: './week-care-strip.css',
})
export class WeekCareStripComponent {
  readonly careWindow = input<CoverageWindow | null>(null);
  readonly recovery = input<RecoveryCase | null>(null);
  readonly busy = input(false);
  readonly action = input<RecoveryAction | null>(null);

  readonly days = computed<WeekCareDay[]>(() => {
    const window = this.careWindow();
    if (!window) return [];
    const anchor = this.calendarDate(window.start);
    if (!anchor) return [];

    const weekStart = new Date(anchor);
    const careState = this.careDateState(window);

    return Array.from({ length: 7 }, (_, index) => {
      const date = new Date(weekStart);
      date.setDate(weekStart.getDate() + index);
      const isCareDate = index === 0;
      const weekend = date.getDay() === 0 || date.getDay() === 6;
      return {
        key: this.dateKey(date),
        weekday: new Intl.DateTimeFormat('en-US', { weekday: 'short' }).format(date),
        date: new Intl.DateTimeFormat('en-US', { day: 'numeric' }).format(date),
        isCareDate,
        ...(isCareDate
          ? careState
          : weekend
            ? {
                primary: 'No scheduled care',
                secondary: 'Family day',
                status: '',
                tone: 'scheduled' as const,
              }
            : {
                primary: 'Nanny',
                secondary: this.timeRange(window),
                status: 'Scheduled',
                tone: 'scheduled' as const,
              }),
      };
    });
  });

  private careDateState(window: CoverageWindow): Omit<WeekCareDay, 'key' | 'weekday' | 'date' | 'isCareDate'> {
    const recovery = this.recovery();
    const action = this.action();
    const rejected = recovery?.approval_history.at(-1)?.status === 'REJECTED';
    const noOption =
      recovery?.status === 'NO_RECOVERY_OPTION' ||
      recovery?.events.some((event) => event.details['outcome_code'] === 'NO_RECOVERY_OPTION');

    if (noOption) {
      return {
        primary: 'Coverage unresolved',
        secondary: 'Current settings leave a gap',
        status: 'Needs another option',
        tone: 'unresolved',
      };
    }
    if (rejected) {
      return {
        primary: 'Coverage unresolved',
        secondary: 'Alternative not applied',
        status: 'Recovery not approved',
        tone: 'unresolved',
      };
    }
    if (recovery?.status === 'RESOLVED') {
      return {
        primary: 'Covered again',
        secondary: 'Repaired by DayMend',
        status: 'Recovered',
        tone: 'recovered',
      };
    }
    if (recovery?.pending_approval || recovery?.status === 'APPROVAL_REQUIRED') {
      return {
        primary: 'Proposed repair',
        secondary: 'Awaiting your decision',
        status: 'Not applied',
        tone: 'proposed',
      };
    }
    if (
      (this.busy() && (action === 'starting' || action === 'declining')) ||
      recovery?.status === 'DETECTED' ||
      recovery?.status === 'ASSESSING' ||
      recovery?.status === 'PLANNING' ||
      recovery?.status === 'REPLANNING'
    ) {
      return {
        primary: 'Care disrupted',
        secondary: 'DayMend repairing',
        status: 'In progress',
        tone: 'repairing',
      };
    }
    if (recovery?.active_plan) {
      return {
        primary: 'Workable Plan A',
        secondary: 'Ready for today',
        status: 'Coverage planned',
        tone: 'proposed',
      };
    }
    return {
      primary: 'Nanny',
      secondary: this.timeRange(window),
      status: 'Scheduled',
      tone: 'scheduled',
    };
  }

  private timeRange(window: CoverageWindow): string {
    return `${this.time(window.start)}–${this.time(window.end)}`;
  }

  private time(value: string): string {
    return new Intl.DateTimeFormat('en-US', {
      hour: 'numeric',
      minute: '2-digit',
    }).format(new Date(value));
  }

  private calendarDate(value: string): Date | null {
    const date = value.slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return null;
    const [year, month, day] = date.split('-').map(Number);
    const parsed = new Date(year, month - 1, day, 12);
    return Number.isFinite(parsed.getTime()) ? parsed : null;
  }

  private dateKey(value: Date): string {
    const pad = (part: number) => String(part).padStart(2, '0');
    return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`;
  }
}
