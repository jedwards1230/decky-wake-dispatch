import { useCallback, useEffect, useRef, useState } from "react";

import { setUpdateCheck, updateInfo, type UpdateInfo } from "../api";
import { lastForcedUpdate, rememberForcedUpdate } from "../store";
import { S, UPDATE } from "../strings";

export interface UpdateState {
  info: UpdateInfo | null; // null until the first answer
  checking: boolean;
  /** Shown under Check for updates: "checked less than a minute ago" or a failure. */
  checkNote: string | null;
  /** Shown on the Check daily toggle when saving it failed. */
  toggleError: string | null;
  /** The value being saved, shown on the toggle until the save settles. */
  pendingEnabled: boolean | null;
  /** Bumped when the toggle must re-read its value (an ignored or failed press). */
  toggleKey: number;
  checkNow: () => void;
  setDaily: (on: boolean) => void;
}

/**
 * Update status for the panel: one update_info(false) when the panel opens (the
 * backend decides whether that sends anything), Check for updates forces one.
 * Nothing touches state after unmount, and repeat presses are ignored rather
 * than disabling the focused button.
 */
export function useUpdate(): UpdateState {
  const [info, setInfo] = useState<UpdateInfo | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkNote, setCheckNote] = useState<string | null>(null);
  const [toggleError, setToggleError] = useState<string | null>(null);
  const [pendingEnabled, setPendingEnabled] = useState<boolean | null>(null);
  const [toggleKey, setToggleKey] = useState(0);
  const mounted = useRef(true);
  const checkingRef = useRef(false);
  const savingToggle = useRef(false);

  const load = useCallback(async (force: boolean): Promise<UpdateInfo | null> => {
    try {
      const answer = await updateInfo(force);
      if (force) rememberForcedUpdate(answer);
      // "Off" or "never checked" says less than a check made this session: keep showing that.
      const forced = lastForcedUpdate();
      const next =
        !force && forced && (answer.status === "disabled" || answer.status === "unchecked")
          ? { ...forced, enabled: answer.enabled, throttled: false }
          : answer;
      if (mounted.current) setInfo(next);
      return next;
    } catch (e) {
      console.warn("[Wake Dispatch] update_info failed", e);
      return null;
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void load(false);
    return () => {
      mounted.current = false;
    };
  }, [load]);

  const checkNow = useCallback(() => {
    if (checkingRef.current) return;
    checkingRef.current = true;
    setChecking(true);
    setCheckNote(null);
    void load(true).then((next) => {
      checkingRef.current = false;
      if (!mounted.current) return;
      setChecking(false);
      if (next === null) setCheckNote(S.backendError);
      else if (next.throttled) setCheckNote(UPDATE.throttled);
    });
  }, [load]);

  const setDaily = useCallback(
    (on: boolean) => {
      if (savingToggle.current) {
        // Ignored: make the toggle show the value being saved again.
        setToggleKey((k) => k + 1);
        return;
      }
      savingToggle.current = true;
      setToggleError(null);
      setPendingEnabled(on);
      setUpdateCheck(on)
        .then(async (saved) => {
          if (!mounted.current) return;
          if (!saved.ok) {
            setToggleError(saved.error);
            setToggleKey((k) => k + 1);
            return;
          }
          setInfo((prev) => (prev ? { ...prev, enabled: saved.enabled } : prev));
          // Turning it on may run the first daily check; turning it off shows "off".
          await load(false);
        })
        .catch((e: unknown) => {
          console.warn("[Wake Dispatch] set_update_check failed", e);
          if (!mounted.current) return;
          setToggleError(S.backendError);
          setToggleKey((k) => k + 1);
        })
        .finally(() => {
          savingToggle.current = false;
          if (mounted.current) setPendingEnabled(null);
        });
    },
    [load],
  );

  return { info, checking, checkNote, toggleError, pendingEnabled, toggleKey, checkNow, setDaily };
}
