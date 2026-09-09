import { ComponentFixture, TestBed } from '@angular/core/testing';

import { RecoveryCase } from '../../core/recovery.models';
import { DemoControlsComponent } from './demo-controls';

describe('DemoControlsComponent', () => {
  let fixture: ComponentFixture<DemoControlsComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DemoControlsComponent],
    }).compileComponents();
    fixture = TestBed.createComponent(DemoControlsComponent);
  });

  function recoveryWith(personId: string): RecoveryCase {
    return {
      status: 'WAITING_FOR_RESPONSE',
      events: [],
      active_plan: {
        coverage_segments: [{ assigned_person_id: personId }],
      },
    } as unknown as RecoveryCase;
  }

  it('offers the decline event only when active Plan A depends on Grandma', () => {
    fixture.componentRef.setInput('recovery', recoveryWith('grandma'));
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Simulate Grandma decline');

    fixture.componentRef.setInput('recovery', recoveryWith('backup_sitter'));
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).not.toContain('Simulate Grandma decline');
  });
});
