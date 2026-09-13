import { TestBed } from '@angular/core/testing';

import { RecoveryPlan } from '../../core/recovery.models';
import { approvalCase } from '../../testing/recovery.fixture';
import { CoveragePlanComponent } from './coverage-plan';

describe('CoveragePlanComponent agenda layout', () => {
  it('keeps every schedule fact inside a narrow plan column', async () => {
    await TestBed.configureTestingModule({ imports: [CoveragePlanComponent] }).compileComponents();
    const fixture = TestBed.createComponent(CoveragePlanComponent);
    const priorPlan = approvalCase.previous_plans[0];
    const plan: RecoveryPlan = {
      ...approvalCase.active_plan!,
      coverage_segments: [
        priorPlan.coverage_segments[0],
        {
          segment_id: 'harbor-replacement',
          window: {
            start: '2026-08-27T10:00:00-07:00',
            end: '2026-08-27T13:00:00-07:00',
          },
          assigned_person_id: 'harbor_nanny_coop',
          source: 'CAREGIVER',
          segment_type: 'CARE',
          location_id: 'family_home',
          location_label: 'Family home',
          estimated_cost: '72',
        },
        priorPlan.coverage_segments[3],
        priorPlan.coverage_segments[4],
      ],
    };
    fixture.componentRef.setInput('plan', plan);
    fixture.componentRef.setInput('previousPlan', priorPlan);
    fixture.componentRef.setInput('invalidatedAssumptions', approvalCase.invalidated_assumptions);
    fixture.componentRef.setInput('requiresApproval', true);
    fixture.detectChanges();

    for (const width of [700, 421, 326, 300]) {
      fixture.nativeElement.style.width = `${width}px`;
      fixture.detectChanges();
      const planElement = fixture.nativeElement.querySelector('.plan') as HTMLElement;
      expect(planElement.scrollWidth).withContext('agenda width ' + width).toBeLessThanOrEqual(planElement.clientWidth);
      expect(planElement.textContent).toContain('Harbor Nanny Coop');
      expect(planElement.textContent).toContain('$72.00');
      for (const row of Array.from(planElement.querySelectorAll<HTMLElement>('.coverage-row'))) {
        expect(getComputedStyle(row).textOverflow).not.toBe('ellipsis');
      }
    }
  });
});
