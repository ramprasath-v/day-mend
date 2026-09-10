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

  it('shows exactly two materially preserved and two invalidated segments', () => {
    const cards = render().querySelectorAll<HTMLElement>('.change__grid article');
    const preserved = cards[0].textContent ?? '';
    const invalidated = cards[1].textContent ?? '';

    expect(preserved).toContain('Preserved · 2');
    expect(preserved).toContain('Parent A');
    expect(preserved).toContain('Backup sitter');
    expect(preserved).not.toContain('Transport with Parent A');
    expect(invalidated).toContain('Invalidated · 2');
    expect(invalidated).toContain('Grandma');
    expect(invalidated).toContain('Transport with Grandma');
  });

  it('preserves semantically identical segments even when their IDs change', () => {
    const preserved = render().querySelector<HTMLElement>('.change__grid article');
    const rows = preserved?.querySelectorAll('.segment') ?? [];

    expect(rows.length).toBe(2);
    expect(preserved?.textContent).toContain('Parent A');
    expect(preserved?.textContent).toContain('Backup sitter');
  });

  it('shows only the new Harbor Nanny Coop segment as the replacement', () => {
    const cards = render().querySelectorAll<HTMLElement>('.change__grid article');
    const replacement = cards[2];

    expect(replacement.textContent).toContain('Replacement · 1');
    expect(replacement.textContent).toContain('Harbor Nanny Coop');
    expect(replacement.querySelectorAll('.segment').length).toBe(1);
  });

  it('keeps complete time and description fields in separate non-truncated grid cells', () => {
    const rows = render().querySelectorAll<HTMLElement>('.segment');

    for (const row of rows) {
      const time = row.querySelector('strong');
      const description = row.querySelector<HTMLElement>('span');
      expect(time?.textContent).toContain('–');
      expect(description?.textContent?.trim().length).toBeGreaterThan(0);
      expect(getComputedStyle(row).display).toBe('grid');
      expect(getComputedStyle(description!).overflow).not.toBe('hidden');
      expect(getComputedStyle(description!).textOverflow).not.toBe('ellipsis');
    }
  });
});
