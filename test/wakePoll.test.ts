// Unit tests for the fast wake confirmation scheduler (src/wakePoll.ts).
// Run with `pnpm test` (Node's built-in runner; Node strips the types).
import assert from "node:assert/strict";
import { test } from "node:test";

import { WakePoller, type PollStatus, type PollTarget } from "../src/wakePoll.ts";

/** Manual timers: nothing runs until advance() moves the fake clock. */
class FakeTimers {
  now = 0;
  private seq = 0;
  private pending = new Map<number, { at: number; fn: () => void }>();

  set = (fn: () => void, ms: number): unknown => {
    const id = ++this.seq;
    this.pending.set(id, { at: this.now + ms, fn });
    return id;
  };

  clear = (handle: unknown): void => {
    this.pending.delete(handle as number);
  };

  get count(): number {
    return this.pending.size;
  }

  /** Move time forward, firing due timers in order and letting promises settle. */
  async advance(ms: number): Promise<void> {
    const end = this.now + ms;
    for (;;) {
      const next = [...this.pending.entries()].filter(([, t]) => t.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
      if (!next) break;
      const [id, t] = next;
      this.pending.delete(id);
      this.now = t.at;
      t.fn();
      await flush();
    }
    this.now = end;
    await flush();
  }
}

async function flush(): Promise<void> {
  for (let i = 0; i < 10; i++) await Promise.resolve();
}

/** A status backend whose answers the test sets per device; records each call. */
function backend(initial: Record<string, PollStatus> = {}) {
  const state: Record<string, PollStatus> = { ...initial };
  const calls: { at: number; ids: string[] }[] = [];
  let hold: Promise<void> | null = null;
  let timers: FakeTimers | null = null;
  const check = async (ids: string[]): Promise<Record<string, PollStatus>> => {
    calls.push({ at: timers?.now ?? -1, ids: [...ids] });
    if (hold) await hold;
    return Object.fromEntries(ids.map((id) => [id, state[id] ?? "unknown"]));
  };
  return {
    state,
    calls,
    check,
    attach(t: FakeTimers) {
      timers = t;
    },
    /** Keep calls pending until the returned release() is called. */
    block(): () => void {
      let release = () => {};
      hold = new Promise<void>((r) => {
        release = () => {
          hold = null;
          r();
        };
      });
      return release;
    },
  };
}

function recorder() {
  const awake: string[] = [];
  const notWoken: string[][] = [];
  const statuses: { id: string; status: PollStatus; final: boolean }[] = [];
  return {
    awake,
    notWoken,
    statuses,
    hooks: {
      onAwake: (t: PollTarget) => awake.push(t.id),
      onNotWoken: (ts: PollTarget[]) => notWoken.push(ts.map((t) => t.id)),
      onStatus: (id: string, status: PollStatus, final: boolean) => statuses.push({ id, status, final }),
    },
  };
}

const PC: PollTarget = { id: "pc", name: "Gaming PC" };
const NAS: PollTarget = { id: "nas", name: "Media Server" };
const asleepBefore = Promise.resolve<Record<string, PollStatus>>({ pc: "asleep", nas: "asleep" });

function setup(initial: Record<string, PollStatus> = {}) {
  const timers = new FakeTimers();
  const api = backend(initial);
  api.attach(timers);
  const poller = new WakePoller(api.check, timers);
  return { timers, api, poller };
}

test("first poll at 1 s, then every 2 s", async () => {
  const { timers, api, poller } = setup({ pc: "asleep" });
  poller.start([PC], asleepBefore, recorder().hooks);
  await timers.advance(999);
  assert.equal(api.calls.length, 0);
  await timers.advance(1);
  assert.deepEqual(
    api.calls.map((c) => c.at),
    [1_000],
  );
  await timers.advance(6_000);
  assert.deepEqual(
    api.calls.map((c) => c.at),
    [1_000, 3_000, 5_000, 7_000],
  );
  poller.cancelAll();
});

test("stops polling a device once it is awake, and toasts it once", async () => {
  const { timers, api, poller } = setup({ pc: "asleep" });
  const rec = recorder();
  poller.start([PC], asleepBefore, rec.hooks);
  await timers.advance(3_000);
  api.state.pc = "awake";
  await timers.advance(2_000); // 5 s poll sees it awake
  const callsAtAwake = api.calls.length;
  await timers.advance(20_000);
  assert.equal(api.calls.length, callsAtAwake, "no polls after awake");
  assert.deepEqual(rec.awake, ["pc"]);
  assert.deepEqual(rec.notWoken, []);
  assert.equal(timers.count, 0, "no timers left once every device answered");
  assert.deepEqual(rec.statuses.at(-1), { id: "pc", status: "awake", final: true });
});

test("one combined hasn't-woken report at the 60 s deadline", async () => {
  const { timers, api, poller } = setup({ pc: "asleep", nas: "asleep" });
  const rec = recorder();
  poller.start([PC, NAS], asleepBefore, rec.hooks);
  await timers.advance(59_999);
  assert.deepEqual(rec.notWoken, []);
  await timers.advance(1);
  assert.deepEqual(rec.notWoken, [["pc", "nas"]]);
  assert.equal(timers.count, 0, "everything stopped at the deadline");
  const calls = api.calls.length;
  await timers.advance(10_000);
  assert.equal(api.calls.length, calls);
  assert.deepEqual(
    rec.statuses.filter((s) => s.final).map((s) => [s.id, s.status]),
    [
      ["pc", "asleep"],
      ["nas", "asleep"],
    ],
  );
});

test("a tick is skipped while the previous call is still pending", async () => {
  const { timers, api, poller } = setup({ pc: "asleep" });
  poller.start([PC], asleepBefore, recorder().hooks);
  const release = api.block();
  await timers.advance(1_000); // call 1 starts and hangs
  await timers.advance(6_000); // ticks at 3, 5, 7 s are skipped
  assert.equal(api.calls.length, 1);
  release();
  await flush();
  await timers.advance(2_000); // 9 s tick polls again
  assert.equal(api.calls.length, 2);
  poller.cancelAll();
});

test("no awake toast for a device that was already awake when the wake was sent", async () => {
  const { timers, poller } = setup({ pc: "awake", nas: "awake" });
  const rec = recorder();
  poller.start([PC, NAS], Promise.resolve({ pc: "awake", nas: "asleep" }), rec.hooks);
  await timers.advance(1_000);
  assert.deepEqual(rec.awake, ["nas"]);
});

test("unknown never produces a hasn't-woken report", async () => {
  const { timers, api, poller } = setup({ pc: "unknown", nas: "asleep" });
  const rec = recorder();
  poller.start([PC, NAS], asleepBefore, rec.hooks);
  await timers.advance(30_000);
  api.state.nas = "unknown"; // last answer before the deadline is unknown
  await timers.advance(30_000);
  assert.deepEqual(rec.notWoken, []);
  assert.deepEqual(
    rec.statuses.filter((s) => s.final).map((s) => [s.id, s.status]),
    [
      ["pc", "unknown"],
      ["nas", "unknown"],
    ],
  );
});

test("a failed status call counts as unknown, not asleep", async () => {
  const timers = new FakeTimers();
  const poller = new WakePoller(() => Promise.reject(new Error("backend gone")), timers);
  const rec = recorder();
  poller.start([PC], asleepBefore, rec.hooks);
  await timers.advance(60_000);
  assert.deepEqual(rec.notWoken, []);
  assert.deepEqual(rec.statuses.at(-1), { id: "pc", status: "unknown", final: true });
});

test("a newer wake takes the device over from the older one", async () => {
  const { timers, api, poller } = setup({ pc: "asleep", nas: "asleep" });
  const first = recorder();
  const second = recorder();
  poller.start([PC, NAS], asleepBefore, first.hooks);
  await timers.advance(10_000);
  poller.start([PC], asleepBefore, second.hooks); // re-wake pc only
  await timers.advance(1_000);
  // pc is polled for the new wake only: never two calls for it in one tick.
  for (const call of api.calls) assert.ok(call.ids.filter((id) => id === "pc").length <= 1);
  api.state.pc = "awake";
  await timers.advance(2_000);
  assert.deepEqual(first.awake, [], "the old wake no longer reports pc");
  assert.deepEqual(second.awake, ["pc"]);
  await timers.advance(60_000);
  assert.deepEqual(first.notWoken, [["nas"]], "the old wake still reports the device it kept");
  assert.deepEqual(second.notWoken, []);
  assert.equal(timers.count, 0);
});

test("an older wake whose devices were all taken over stops its timers", async () => {
  const { timers, poller } = setup({ pc: "asleep" });
  const first = recorder();
  poller.start([PC], asleepBefore, first.hooks);
  poller.start([PC], asleepBefore, recorder().hooks);
  await timers.advance(1_000);
  // Only the newer wake's two timers (next tick, deadline) remain.
  assert.equal(timers.count, 2);
  await timers.advance(70_000);
  assert.deepEqual(first.notWoken, []);
  assert.equal(timers.count, 0);
});

test("cancelAll stops every timer and silences late answers", async () => {
  const { timers, api, poller } = setup({ pc: "asleep", nas: "asleep" });
  const rec = recorder();
  poller.start([PC], asleepBefore, rec.hooks);
  poller.start([NAS], asleepBefore, rec.hooks);
  const release = api.block();
  await timers.advance(1_000);
  poller.cancelAll();
  assert.equal(timers.count, 0);
  api.state.pc = "awake";
  release();
  await flush();
  await timers.advance(120_000);
  assert.deepEqual(rec.awake, []);
  assert.deepEqual(rec.notWoken, []);
  assert.deepEqual(rec.statuses, []);
});
