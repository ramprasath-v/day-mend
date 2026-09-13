import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { of } from 'rxjs';
import { TodayPage } from './today';
import { HistoryPage } from './history';
import { LiveRecoveryComponent } from '../components/live-recovery/live-recovery';
import { RepairZoneComponent } from '../components/repair-zone/repair-zone';
import { RecoveryStore } from '../core/recovery.store';
import { FamilyService } from '../core/family.service';
import { RecoveryCase, RecoveryProgressEvent } from '../core/recovery.models';
import { planACase, approvalCase, resolvedCase } from '../testing/recovery.fixture';
import { familyFixture } from '../testing/family.fixture';

const event = (type: string, sequence = 1, status: RecoveryProgressEvent['status'] = 'ACTIVE'): RecoveryProgressEvent => ({
  id: String(sequence), sequence, progress_id: 'test', recovery_case_id: planACase.recovery_case_id,
  timestamp: '2026-09-12T18:00:00Z', event_type: type, actor_type: 'SYSTEM', actor_name: 'daymend',
  stage: 'replanning', status, summary: type, details: {},
});

describe('Repairing day experience', () => {
  let state: {
    currentCase: ReturnType<typeof signal<RecoveryCase | null>>;
    loading: ReturnType<typeof signal<boolean>>;
    error: ReturnType<typeof signal<string | null>>;
    progressEvents: ReturnType<typeof signal<RecoveryProgressEvent[]>>;
    progressConnected: ReturnType<typeof signal<boolean>>;
    elapsedSeconds: ReturnType<typeof signal<number>>;
    actionInProgress: ReturnType<typeof signal<string | null>>;
  };
  beforeEach(async () => {
    state = { currentCase: signal(planACase), loading: signal(true), error: signal(null),
      progressEvents: signal([]), progressConnected: signal(true), elapsedSeconds: signal(38), actionInProgress: signal('declining') };
    await TestBed.configureTestingModule({
      imports: [TodayPage, HistoryPage, LiveRecoveryComponent, RepairZoneComponent],
      providers: [{ provide: RecoveryStore, useValue: state }, { provide: FamilyService, useValue: { get: () => of(familyFixture) } }],
    }).compileComponents();
  });
  it('places the active strip above the schedule and shows measured elapsed time without a percentage', () => {
    const f = TestBed.createComponent(TodayPage); f.detectChanges();
    const html = f.nativeElement as HTMLElement;
    expect(html.textContent).toContain('Working for 38s');
    expect(html.textContent).not.toContain('%');
    expect(html.querySelector('app-live-recovery')!.compareDocumentPosition(html.querySelector('app-repair-zone')!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(html.querySelectorAll('.pulse').length).toBe(1);
  });
  it('distinguishes sending the decline from confirmed unavailability without waiting for Plan B', () => {
    const f = TestBed.createComponent(TodayPage); f.detectChanges();
    expect(f.nativeElement.textContent).toContain('Decline being sent');
    expect(f.nativeElement.querySelector('[data-repair-status^="Unavailable"]')).toBeNull();
    state.progressEvents.set([event('WORLD_STATE_CHANGED', 1, 'WARNING')]); f.detectChanges();
    expect(f.nativeElement.querySelector('[data-repair-status^="Unavailable"]').textContent).toContain('Grandma');
    expect(f.nativeElement.textContent).toContain('Coverage needed');
    expect(f.nativeElement.textContent).toContain('Unchanged in the current plan');
    expect(f.nativeElement.textContent).toContain('Backup sitter');
  });
  it('maps real research and validation events to the current phase, not imagined steps', () => {
    const f = TestBed.createComponent(TodayPage);
    state.progressEvents.set([event('RESEARCH_STARTED')]); f.detectChanges();
    expect(f.nativeElement.querySelector('[role="status"]').textContent).toContain('Looking for backup care');
    state.progressEvents.set([event('VALIDATION_STARTED', 2)]); f.detectChanges();
    expect(f.nativeElement.querySelector('[role="status"]').textContent).toContain('Checking timing, travel and cost');
    expect(f.nativeElement.textContent).not.toContain('Your day is recovered');
  });
  it('does not reuse a completed Plan A phase for the new decline', () => {
    state.progressEvents.set([event('RESEARCH_STARTED'), event('PLAN_A_ACCEPTED', 2, 'COMPLETED')]);
    const f = TestBed.createComponent(TodayPage); f.detectChanges();
    expect(f.nativeElement.querySelector('[role="status"]').textContent).toContain('Sending the change');
  });
  it('does not paint failed completion as success', () => {
    const f = TestBed.createComponent(LiveRecoveryComponent);
    expect(f.componentInstance.eventLabel({ ...event('COMPLETION_VERIFIED', 1, 'FAILED'), summary: 'Final coverage verification failed' })).toBe('Final coverage verification failed');
  });
  it('flags inbound transport for review without falsely declaring it invalid or preserved', () => {
    const f = TestBed.createComponent(RepairZoneComponent);
    const care = { ...planACase.active_plan!.coverage_segments[2], location_id: 'helper_home' };
    const trip = { ...planACase.active_plan!.coverage_segments[0], segment_id: 'trip', segment_type: 'TRANSPORT' as const, destination_location_id: 'helper_home' };
    f.componentRef.setInput('plan', { ...planACase.active_plan, coverage_segments: [trip, care] });
    f.componentRef.setInput('personId', care.assigned_person_id);
    f.componentRef.setInput('confirmed', true); f.detectChanges();
    expect(f.componentInstance.label(trip)).toBe('Handoff needs review');
    expect(f.nativeElement.querySelector('.broken').textContent).toContain('Unavailable');
  });
  it('keeps the active repair surface readable at narrow component widths', () => {
    const f = TestBed.createComponent(RepairZoneComponent);
    f.componentRef.setInput('plan', planACase.active_plan); f.componentRef.setInput('personId', 'grandma');
    f.componentRef.setInput('confirmed', true); f.detectChanges();
    for (const width of [1344,1184,928,350]) {
      f.nativeElement.style.width = width + 'px'; f.detectChanges();
      const surface = f.nativeElement.querySelector('.repair') as HTMLElement;
      expect(surface.scrollWidth).withContext('width ' + width).toBeLessThanOrEqual(surface.clientWidth);
      expect(surface.textContent).toContain('Coverage needed');
    }
  });
  it('replaces the repair area with the persisted comparison and exact approval sheet', () => {
    state.currentCase.set(approvalCase); state.loading.set(false); state.actionInProgress.set(null);
    const f = TestBed.createComponent(TodayPage); f.detectChanges();
    expect(f.nativeElement.querySelector('app-repair-zone')).toBeNull();
    expect(f.nativeElement.querySelectorAll('[data-classification="Replacement"]').length).toBe(1);
    expect(f.nativeElement.textContent).toContain('Approve $92.00');
    expect(f.nativeElement.textContent).toContain(approvalCase.pending_approval!.reason);
    expect(f.nativeElement.querySelector('app-plan-change')).not.toBeNull();
  });
  it('settles resolved progress using actual action count and retains What changed', () => {
    state.currentCase.set(resolvedCase); state.loading.set(false); state.actionInProgress.set(null);
    const f = TestBed.createComponent(TodayPage); f.detectChanges();
    expect(f.nativeElement.textContent).toContain('3 actions completed');
    expect(f.nativeElement.textContent).toContain('What changed');
    expect(f.nativeElement.querySelector('.pulse')).toBeNull();
    expect(f.nativeElement.textContent).toContain('Care date');
    expect(f.nativeElement.textContent).toContain('Recovery run completed');
    expect(f.nativeElement.querySelector('.resolved-changes').open).toBeFalse();
    expect(f.nativeElement.querySelector('app-coverage-plan')).not.toBeNull();
  });
  it('keeps History parent-facing, with decisions and technical details under native disclosure controls', () => {
    state.currentCase.set(resolvedCase);
    const f = TestBed.createComponent(HistoryPage); f.detectChanges();
    expect(f.nativeElement.textContent).toContain('Past repaired days.');
    expect(f.nativeElement.textContent).toContain('What stayed the same');
    expect(f.nativeElement.textContent).toContain('What changed');
    expect(f.nativeElement.textContent).toContain('You approved $92.00');
    const technical = f.nativeElement.querySelector('.technical') as HTMLDetailsElement;
    expect(technical.open).toBeFalse();
    expect(technical.textContent).toContain('SUCCEEDED');
    expect(f.nativeElement.querySelector('.day-heading').textContent).not.toContain('SUCCEEDED');
    expect(f.nativeElement.textContent).toContain('Care date');
    expect(technical.textContent).toContain('Recovery run started');
    technical.querySelector('summary')!.click(); expect(technical.open).toBeTrue();
  });
  it('does not turn a non-resolved history record into a recovered day', () => {
    state.currentCase.set(approvalCase);
    const f = TestBed.createComponent(HistoryPage); f.detectChanges();
    expect(f.nativeElement.querySelector('.recovered')).toBeNull();
    expect(f.nativeElement.textContent).toContain('This recovery is not resolved yet');
  });
  it('uses a reduced-motion override and leaves the textual working status intact', () => {
    const f = TestBed.createComponent(TodayPage); f.detectChanges();
    const rules = [...document.styleSheets].flatMap(sheet => [...sheet.cssRules]);
    expect(rules.some(rule => rule instanceof CSSMediaRule
      && rule.conditionText.includes('prefers-reduced-motion')
      && [...rule.cssRules].some(child => child instanceof CSSStyleRule && child.style.animationName === 'none'))).toBeTrue();
    expect(f.nativeElement.querySelector('[role="status"]').textContent.length).toBeGreaterThan(0);
  });
});
