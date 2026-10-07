// Fast wake confirmation: after a manual wake, poll each device's status check
// until it answers or a deadline passes. Pure TypeScript with injected timers and
// status calls (no @decky imports), so it runs under `node --test`.
// Only erasable TypeScript syntax is used here, so Node can strip the types.

export type PollStatus = "awake" | "asleep" | "unknown";

export interface PollTarget {
  id: string;
  name: string;
}

export interface PollTimers {
  set: (fn: () => void, ms: number) => unknown;
  clear: (handle: unknown) => void;
}

export interface PollHooks {
  /** Every answer for a device, and `final` once when its polling ends. */
  onStatus?: (id: string, status: PollStatus, final: boolean) => void;
  /** A device answered "awake" and wasn't awake before the wake: toast it. */
  onAwake?: (target: PollTarget) => void;
  /** At the deadline: devices whose last answer was "asleep" (never "unknown"). */
  onNotWoken?: (targets: PollTarget[]) => void;
}

export interface PollOptions {
  firstMs?: number;
  everyMs?: number;
  deadlineMs?: number;
}

export const FIRST_POLL_MS = 1_000;
export const POLL_EVERY_MS = 2_000;
export const POLL_DEADLINE_MS = 60_000;

interface DeviceState {
  target: PollTarget;
  group: Group;
  pending: boolean;
  done: boolean;
  last: PollStatus | null;
}

interface Group {
  tick: unknown;
  deadline: unknown;
  ended: boolean;
  hooks: PollHooks;
  before: Promise<Record<string, PollStatus>>;
}

/**
 * One poller per plugin. `start` begins polling a set of devices for one wake;
 * a later `start` that includes a device takes that device over (the older wake
 * stops reporting it). Status calls never overlap per device: a tick skips any
 * device whose previous call hasn't answered. `cancelAll` stops every timer.
 */
export class WakePoller {
  private readonly devices = new Map<string, DeviceState>();
  private readonly groups = new Set<Group>();
  private readonly check: (ids: string[]) => Promise<Record<string, PollStatus>>;
  private readonly timers: PollTimers;
  private readonly firstMs: number;
  private readonly everyMs: number;
  private readonly deadlineMs: number;

  constructor(
    check: (ids: string[]) => Promise<Record<string, PollStatus>>,
    timers: PollTimers,
    options: PollOptions = {},
  ) {
    this.check = check;
    this.timers = timers;
    this.firstMs = options.firstMs ?? FIRST_POLL_MS;
    this.everyMs = options.everyMs ?? POLL_EVERY_MS;
    this.deadlineMs = options.deadlineMs ?? POLL_DEADLINE_MS;
  }

  /**
   * Poll `targets` for one wake. `before` is the status known when the wake was
   * sent; a device that was already awake then gets no "is awake" toast.
   */
  start(targets: PollTarget[], before: Promise<Record<string, PollStatus>>, hooks: PollHooks = {}): void {
    if (targets.length === 0) return;
    const group: Group = {
      tick: null,
      deadline: null,
      ended: false,
      hooks,
      before: before.catch(() => ({})),
    };
    this.groups.add(group);
    for (const target of targets) {
      // Takes over from an older wake still polling this device.
      this.devices.set(target.id, { target, group, pending: false, done: false, last: null });
    }
    group.tick = this.timers.set(() => this.tick(group), this.firstMs);
    group.deadline = this.timers.set(() => this.expire(group), this.deadlineMs);
  }

  /** Stop everything (plugin unload). No hook fires afterwards. */
  cancelAll(): void {
    for (const group of this.groups) this.stop(group);
    this.groups.clear();
    this.devices.clear();
  }

  /** Devices a group still owns (not taken over by a newer wake). */
  private owned(group: Group): DeviceState[] {
    return [...this.devices.values()].filter((d) => d.group === group);
  }

  private tick(group: Group): void {
    group.tick = null;
    if (group.ended) return;
    const mine = this.owned(group);
    // Every device was taken over by newer wakes: nothing left to poll.
    if (mine.length === 0) {
      this.finish(group);
      return;
    }
    const due = mine.filter((d) => !d.done && !d.pending);
    if (due.length > 0) {
      for (const d of due) d.pending = true;
      const ids = due.map((d) => d.target.id);
      this.check(ids)
        .catch(() => ({}) as Record<string, PollStatus>)
        .then((answers) => {
          for (const d of due) this.answer(group, d, answers[d.target.id] ?? "unknown");
        });
    }
    if (!group.ended) group.tick = this.timers.set(() => this.tick(group), this.everyMs);
  }

  private answer(group: Group, d: DeviceState, status: PollStatus): void {
    d.pending = false;
    // A newer wake owns it now, or this wake's polling already ended.
    if (group.ended || this.devices.get(d.target.id) !== d) return;
    d.last = status;
    if (status !== "awake") {
      group.hooks.onStatus?.(d.target.id, status, false);
      return;
    }
    d.done = true;
    group.hooks.onStatus?.(d.target.id, "awake", true);
    void group.before.then((prior) => {
      if (prior[d.target.id] !== "awake") group.hooks.onAwake?.(d.target);
    });
    if (this.owned(group).every((x) => x.done)) this.finish(group);
  }

  private expire(group: Group): void {
    group.deadline = null;
    if (group.ended) return;
    const left = this.owned(group).filter((d) => !d.done);
    for (const d of left) group.hooks.onStatus?.(d.target.id, d.last ?? "unknown", true);
    const asleep = left.filter((d) => d.last === "asleep").map((d) => d.target);
    if (asleep.length > 0) group.hooks.onNotWoken?.(asleep);
    this.finish(group);
  }

  private finish(group: Group): void {
    this.stop(group);
    this.groups.delete(group);
    for (const d of this.owned(group)) this.devices.delete(d.target.id);
  }

  private stop(group: Group): void {
    group.ended = true;
    if (group.tick !== null) this.timers.clear(group.tick);
    if (group.deadline !== null) this.timers.clear(group.deadline);
    group.tick = null;
    group.deadline = null;
  }
}
