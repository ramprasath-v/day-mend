import { TestBed } from '@angular/core/testing';

import { CoverageSegment, RecoveryCase } from '../../core/recovery.models';
import { approvalCase } from '../../testing/recovery.fixture';
import { PlanChangeComponent } from './plan-change';

describe('PlanChangeComponent', () => {
  const planA: CoverageSegment[] = [
    {
      segment_id: 'parent-care',
      window: { start: '2026-08-27T08:00:00-07:00', end: '2026-08-27T08:45:00-07:00' },
      assigned_person_id: 'parent_a',
      source: 'PARENT',
      segment_type: 'CARE',
      location_id: 'family_home',
      estimated_cost: '0',
    },
    {
      segment_id: 'parent-transport',
      window: { start: '2026-08-27T08:45:00-07:00', end: '2026-08-27T09:00:00-07:00' },
      assigned_person_id: 'parent_a',
      source: 'PARENT',
      segment_type: 'TRANSPORT',
      location_id: 'family_home',
      destination_location_id: 'grandma_home',
      transporter_id: 'parent_a',
      estimated_cost: '0',
    },
    {
      segment_id: 'grandma-care',
      window: { start: '2026-08-27T09:00:00-07:00', end: '2026-08-27T12:00:00-07:00' },
      assigned_person_id: 'grandma',
      source: 'CAREGIVER',
      segment_type: 'CARE',
      location_id: 'grandma_home',
      estimated_cost: '0',
    },
    {
      segment_id: 'grandma-transport',
      window: { start: '2026-08-27T12:00:00-07:00', end: '2026-08-27T12:15:00-07:00' },
      assigned_person_id: 'grandma',
      source: 'CAREGIVER',
      segment_type: 'TRANSPORT',
      location_id: 'grandma_home',
      destination_location_id: 'family_home',
      transporter_id: 'grandma',
      estimated_cost: '0',
    },
    {
      segment_id: 'late-sitter',
      window: { start: '2026-08-27T12:15:00-07:00', end: '2026-08-27T16:00:00-07:00' },
      assigned_person_id: 'backup_sitter',
      source: 'CAREGIVER',
      segment_type: 'CARE',
      location_id: 'family_home',
      estimated_cost: '0',
    },
  ];

  const planB: CoverageSegment[] = [
    { ...planA[0], segment_id: 'plan-b-parent-care' },
    {
      segment_id: 'harbor-replacement',
      window: { start: '2026-08-27T08:45:00-07:00', end: '2026-08-27T12:15:00-07:00' },
      assigned_person_id: 'harbor_nanny_coop',
      source: 'CAREGIVER',
      segment_type: 'CARE',
      location_id: 'family_home',
      estimated_cost: '94.50',
    },
    { ...planA[4], segment_id: 'plan-b-late-sitter' },
  ];

  const recovery: RecoveryCase = {
    ...approvalCase,
    previous_plans: [
      {
        ...approvalCase.previous_plans[0],
        coverage_segments: planA,
      },
    ],
    active_plan: {
      ...approvalCase.active_plan!,
      coverage_segments: planB,
    },
    invalidated_assumptions: [
      {
        ...approvalCase.invalidated_assumptions[0],
        assumption_id: 'grandma-care-unavailable',
        relevant_window: planA[2].window,
      },
      {
        ...approvalCase.invalidated_assumptions[0],
        assumption_id: 'grandma-transport-unavailable',
        relevant_window: planA[3].window,
      },
    ],
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [PlanChangeComponent] }).compileComponents();
  });

  function render(): HTMLElement {
    const fixture = TestBed.createComponent(PlanChangeComponent);
    fixture.componentRef.setInput('recovery', recovery);
    fixture.detectChanges();
    return fixture.nativeElement;
  }


  it('shows two kept, two invalidated and one replacement', () => {
    const el = render();
    expect(el.textContent).toContain('Kept · 2');
    expect(el.textContent).toContain('Invalidated · 2');
    expect(el.textContent).toContain('Replacement · 1');
    expect(el.querySelectorAll('[data-classification="Kept"]').length).toBe(2);
    expect(el.querySelectorAll('[data-classification="Unavailable"]').length).toBe(2);
  });
  it('renders replacement only once across its full interval', () => {
    const el = render();
    expect(el.querySelectorAll('[data-classification="Replacement"]').length).toBe(1);
    expect(el.querySelector('.now')?.textContent).toContain('Harbor Nanny Coop');
    expect(el.querySelectorAll('.repair-interval').length).toBe(1);
  });
  it('keeps identical segments with different IDs anchored outside the changed interval', () => {
    const el = render();
    const kept = el.querySelectorAll('.kept');
    expect(kept.length).toBe(2);
    expect(kept[0].textContent).toContain('Parent A');
    expect(kept[1].textContent).toContain('Backup sitter');
  });
  it('shows removed transport only when validated replacement care covers it', () => {
    expect(render().querySelector('[data-classification="Transport no longer needed"]')?.textContent).toContain('Parent A');
    const fixture = TestBed.createComponent(PlanChangeComponent);
    fixture.componentRef.setInput('recovery', { ...recovery, active_plan: { ...recovery.active_plan, validation_state: 'NOT_VALIDATED' } });
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[data-classification="Transport no longer needed"]')).toBeNull();
  });
  it('does not claim transport is unnecessary when there is a coverage gap', () => {
    const fixture = TestBed.createComponent(PlanChangeComponent);
    fixture.componentRef.setInput('recovery', { ...recovery, active_plan: { ...recovery.active_plan, coverage_segments: [planB[0], planB[2]] } });
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[data-classification="Transport no longer needed"]')).toBeNull();
  });
  it('retains the repaired schedule after resolution without clipping narrow columns', () => {
    const fixture = TestBed.createComponent(PlanChangeComponent);
    fixture.componentRef.setInput('recovery', { ...recovery, status: 'RESOLVED' });
    fixture.detectChanges();
    for (const width of [1200, 900, 700, 350]) {
      fixture.nativeElement.style.width = width + 'px';
      const el = fixture.nativeElement.querySelector('.change') as HTMLElement;
      expect(el.scrollWidth).toBeLessThanOrEqual(el.clientWidth);
      expect(el.querySelector('.repair-interval')).not.toBeNull();
      expect(getComputedStyle(el.querySelector('strong')!).textOverflow).not.toBe('ellipsis');
    }
  });
});
