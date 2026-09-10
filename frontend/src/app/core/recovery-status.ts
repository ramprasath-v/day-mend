import { RecoveryStatus } from './recovery.models';

export interface StatusPresentation {
  eyebrow: string;
  title: string;
  description: string;
  tone: 'calm' | 'working' | 'attention' | 'success' | 'danger';
}

export const RECOVERY_STATUS_COPY: Record<RecoveryStatus, StatusPresentation> = {
  DETECTED: {
    eyebrow: 'Childcare changed',
    title: 'We noticed a gap in today’s care',
    description: 'DayMend is gathering the details needed to recover your day.',
    tone: 'attention',
  },
  ASSESSING: {
    eyebrow: 'Understanding the change',
    title: 'Checking today’s commitments',
    description: 'We’re reviewing coverage, calendars, and trusted backup options.',
    tone: 'working',
  },
  PLANNING: {
    eyebrow: 'Building a new plan',
    title: 'DayMend is rebuilding your day',
    description: 'A complete childcare plan is being checked against your family’s rules.',
    tone: 'working',
  },
  WAITING_FOR_RESPONSE: {
    eyebrow: 'A new plan for today',
    title: 'Your day has a workable Plan A',
    description: 'DayMend is keeping watch for caregiver responses and changes.',
    tone: 'calm',
  },
  REPLANNING: {
    eyebrow: 'Looking for backup care',
    title: 'DayMend is looking for another option',
    description: 'The affected coverage is being rebuilt while valid parts stay in place.',
    tone: 'working',
  },
  APPROVAL_REQUIRED: {
    eyebrow: 'Waiting for your approval',
    title: 'A valid recovery plan is ready',
    description: 'DayMend paused before taking an action outside your automatic-spend limit.',
    tone: 'attention',
  },
  EXECUTING: {
    eyebrow: 'Putting your plan in place',
    title: 'Confirming your recovered day',
    description: 'Calendar updates and backup coverage are being completed and verified.',
    tone: 'working',
  },
  RESOLVED: {
    eyebrow: 'Recovery complete',
    title: 'Day recovered',
    description: 'Childcare coverage restored through 4:00 PM.',
    tone: 'success',
  },
  FAILED: {
    eyebrow: 'Recovery needs attention',
    title: 'DayMend couldn’t finish this plan',
    description: 'No unsafe or incomplete recovery was marked as resolved.',
    tone: 'danger',
  },
};

export const INITIAL_STATUS: StatusPresentation = {
  eyebrow: 'Today’s childcare',
  title: 'Your day is covered',
  description: 'Your nanny is scheduled from 8:00 AM to 4:00 PM.',
  tone: 'calm',
};

export function friendlyPerson(personId: string): string {
  const names: Record<string, string> = {
    nanny: 'Nanny',
    grandma: 'Grandma',
    backup_sitter: 'Backup sitter',
    employer_backup_care: 'Employer backup care',
    harbor_nanny_coop: 'Harbor Nanny Coop',
    parent_a: 'Parent A',
    parent_b: 'Parent B',
  };
  return names[personId] ?? personId.replaceAll('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export function friendlyActionTarget(targetId: string): string {
  return friendlyPerson(targetId.replace(/^calendar:/, ''));
}
