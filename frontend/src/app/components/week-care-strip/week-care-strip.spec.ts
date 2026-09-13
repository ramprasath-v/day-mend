import { ComponentFixture, TestBed } from '@angular/core/testing';

import {
  approvalCase,
  noOptionCase,
  rejectedCase,
  resolvedCase,
} from '../../testing/recovery.fixture';
import { WeekCareStripComponent } from './week-care-strip';

describe('WeekCareStripComponent', () => {
  let fixture: ComponentFixture<WeekCareStripComponent>;
  const careWindow = {
    start: '2026-08-27T08:00:00-07:00',
    end: '2026-08-27T16:00:00-07:00',
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [WeekCareStripComponent] }).compileComponents();
    fixture = TestBed.createComponent(WeekCareStripComponent);
    fixture.componentRef.setInput('careWindow', careWindow);
  });

  function currentDay(): HTMLElement {
    fixture.detectChanges();
    return fixture.nativeElement.querySelector('[aria-current="date"]');
  }

  it('renders a seven-day care strip with the seeded care date highlighted', () => {
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelectorAll('[data-week-day]').length).toBe(7);
    expect(currentDay().textContent).toContain('Nanny');
    expect(currentDay().textContent).toContain('8:00 AM–4:00 PM');
    expect(currentDay().textContent).toContain('Scheduled');
  });

  it('changes only the care date while the first recovery is running', () => {
    fixture.componentRef.setInput('busy', true);
    fixture.componentRef.setInput('action', 'starting');

    expect(currentDay().textContent).toContain('Care disrupted');
    expect(currentDay().textContent).toContain('DayMend repairing');
    const otherDays = [
      ...fixture.nativeElement.querySelectorAll('[data-week-day]:not([aria-current="date"])'),
    ] as HTMLElement[];
    expect(otherDays.every((day) => !day.textContent?.includes('DayMend repairing'))).toBeTrue();
    expect(otherDays.some((day) => day.textContent?.includes('Nanny'))).toBeTrue();
  });

  it('shows an awaiting-approval repair as proposed rather than applied', () => {
    fixture.componentRef.setInput('recovery', approvalCase);

    expect(currentDay().textContent).toContain('Proposed repair');
    expect(currentDay().textContent).toContain('Awaiting your decision');
    expect(currentDay().textContent).toContain('Not applied');
    expect(currentDay().textContent).not.toContain('Covered again');
  });

  it('shows a resolved recovery as covered again', () => {
    fixture.componentRef.setInput('recovery', resolvedCase);

    expect(currentDay().textContent).toContain('Covered again');
    expect(currentDay().getAttribute('data-week-state')).toBe('recovered');
  });

  it('does not show a rejected proposal as repaired', () => {
    fixture.componentRef.setInput('recovery', rejectedCase);

    expect(currentDay().textContent).toContain('Coverage unresolved');
    expect(currentDay().textContent).toContain('Alternative not applied');
    expect(currentDay().textContent).not.toContain('Covered again');
  });

  it('shows no-option coverage as unresolved', () => {
    fixture.componentRef.setInput('recovery', noOptionCase);

    expect(currentDay().textContent).toContain('Coverage unresolved');
    expect(currentDay().textContent).toContain('Needs another option');
    expect(currentDay().getAttribute('data-week-state')).toBe('unresolved');
  });
});
