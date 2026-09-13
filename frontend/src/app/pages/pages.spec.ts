import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { provideRouter, Router } from '@angular/router';
import { App } from '../app';
import { routes } from '../app.routes';
import { RecoveryStore } from '../core/recovery.store';
import { RecoveryCase } from '../core/recovery.models';
import { approvalCase, resolvedCase } from '../testing/recovery.fixture';
import { ApprovalCardComponent } from '../components/approval-card/approval-card';
import { LiveRecoveryComponent } from '../components/live-recovery/live-recovery';
import { FamilyService } from '../core/family.service';
import { familyFixture } from '../testing/family.fixture';
import { of } from 'rxjs';

describe('Consumer destinations', () => {
  let state: ReturnType<typeof makeState>;
  function makeState() {
    return { currentCase: signal<RecoveryCase | null>(resolvedCase), loading: signal(false), error: signal<string | null>(null),
      progressEvents: signal([]), progressConnected: signal(false), elapsedSeconds: signal(0),
      actionInProgress: signal(null), demoCareDate: signal(familyFixture.required_care_schedule.start) };
  }
  beforeEach(async () => {
    state = makeState();
    await TestBed.configureTestingModule({ imports: [App, ApprovalCardComponent, LiveRecoveryComponent],
      providers: [provideRouter(routes), { provide: RecoveryStore, useValue: state },
        { provide: FamilyService, useValue: { get: () => of(structuredClone(familyFixture)) } }] }).compileComponents();
  });
  for (const page of ['today', 'history', 'family', 'settings']) {
    it('navigates to ' + page + ' and marks only its navigation link active', async () => {
      const fixture = TestBed.createComponent(App);
      fixture.detectChanges();
      await TestBed.inject(Router).navigateByUrl('/' + page);
      fixture.detectChanges();
      await fixture.whenStable();
      fixture.detectChanges();
      const links = fixture.nativeElement.querySelectorAll('nav [aria-current="page"]');
      expect(links.length).toBe(1);
      expect(links[0].textContent.trim().toLowerCase()).toBe(page);
      expect(fixture.nativeElement.querySelector('app-' + page)).not.toBeNull();
    });
  }
  it('shows one available history record with read-only decisions and execution', async () => {
    const fixture = TestBed.createComponent(App); fixture.detectChanges();
    await TestBed.inject(Router).navigateByUrl('/history'); fixture.detectChanges();
    expect(fixture.nativeElement.querySelectorAll('app-history > article').length).toBe(1);
    expect(fixture.nativeElement.textContent).toContain('APPROVED');
    expect(fixture.nativeElement.textContent).toContain('SUCCEEDED');
    expect(fixture.nativeElement.querySelector('app-history button')).toBeNull();
    state.currentCase.set(null); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('No recovery is available');
    expect(fixture.nativeElement.querySelector('app-history article')).toBeNull();
  });
  it('shows saved family facts with editable care preferences', async () => {
    const fixture = TestBed.createComponent(App); fixture.detectChanges();
    await TestBed.inject(Router).navigateByUrl('/family'); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Family helper');
    expect(fixture.nativeElement.textContent).toContain('Helper home');
    expect(fixture.nativeElement.textContent).toContain('Care preferences');
    expect(fixture.nativeElement.textContent).toContain('never override safety rules');
  });
  it('loads current family settings independently of the recovery snapshot', async () => {
    state.currentCase.set({ ...resolvedCase, automatic_spend_limit: '42.50', currency: 'EUR' });
    const fixture = TestBed.createComponent(App); fixture.detectChanges();
    await TestBed.inject(Router).navigateByUrl('/settings'); fixture.detectChanges();
    await fixture.whenStable();
    expect(fixture.nativeElement.querySelector('input[inputmode="decimal"]').value).toBe('30.00');
    expect(fixture.nativeElement.textContent).toContain('unless another approval rule applies');
    state.currentCase.set(null); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('input[inputmode="decimal"]').value).toBe('30.00');
  });
  it('displays exact approval cents, generic currency, and threshold', () => {
    const fixture = TestBed.createComponent(ApprovalCardComponent);
    fixture.componentRef.setInput('recovery', { ...approvalCase, pending_approval: { ...approvalCase.pending_approval!, amount: '87.75' } });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Approve $87.75');
    expect(fixture.nativeElement.textContent).toContain('Above your $30 automatic-spend limit.');
    expect(fixture.nativeElement.textContent).not.toContain('$88');
    fixture.componentRef.setInput('recovery', { ...approvalCase, currency: 'EUR', pending_approval: { ...approvalCase.pending_approval!, currency: 'EUR', amount: '41.23' } });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Approve €41.23');
  });
  it('distinguishes awaiting approval from resolved and keeps the journal collapsed', () => {
    const fixture = TestBed.createComponent(LiveRecoveryComponent);
    fixture.componentRef.setInput('recovery', approvalCase); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Awaiting approval');
    expect(fixture.nativeElement.textContent).not.toContain('Complete');
    const details = fixture.nativeElement.querySelector('details');
    expect(details.open).toBeFalse();
    details.querySelector('summary').click();
    expect(details.open).toBeTrue();
    fixture.componentRef.setInput('recovery', resolvedCase); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Recovery resolved');
  });
  it('retains resolved diff in Today and has no action buttons in History', async () => {
    const fixture = TestBed.createComponent(App); fixture.detectChanges();
    await TestBed.inject(Router).navigateByUrl('/today'); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('app-plan-change .repair-interval')).not.toBeNull();
    expect(fixture.nativeElement.textContent).toContain('Your day is recovered.');
    expect(fixture.nativeElement.querySelector('app-approval-card')).toBeNull();
  });
});
