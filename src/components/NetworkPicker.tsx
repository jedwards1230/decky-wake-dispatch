import {
  DialogBodyText,
  DialogButton,
  DialogButtonSecondary,
  DialogFooter,
  DialogHeader,
  Field,
  Focusable,
  ModalRoot,
  Spinner,
  TextField,
  showModal,
} from "@decky/ui";
import { useCallback, useEffect, useRef, useState } from "react";

import { cancelScan, currentNetwork, findHost, neighbours, scanNetwork, type Neighbour } from "../api";
import { useDevices } from "../store";
import { PICKER } from "../strings";
import { ConfirmAction } from "./ConfirmAction";
import { focusSoon } from "./focus";
import { InlineError, hintOrError } from "./InlineError";

interface Props {
  onPick: (n: Neighbour) => void;
  closeModal?: () => void;
}

type ScanState =
  | { phase: "idle" }
  | { phase: "scanning" }
  | { phase: "done"; found: number; named: number }
  | { phase: "message"; text: string; error: boolean };

/** Named devices first, the router last; otherwise keep the backend's order. */
function rank(n: Neighbour, gateway: string | null): number {
  if (gateway !== null && n.ip === gateway) return 2;
  return n.hostname ? 0 : 1;
}

/** "gaming-pc.local" → "gaming-pc": the suffix only adds noise in a short list. */
export function displayName(hostname: string): string {
  return hostname.replace(/\.(local|lan)\.?$/i, "");
}

/** Scan results update entries with the same MAC and add new ones; a name is never lost. */
function merge(current: Neighbour[], found: Neighbour[]): Neighbour[] {
  const byMac = new Map(current.map((n) => [n.mac, n]));
  for (const n of found) {
    const prev = byMac.get(n.mac);
    byMac.set(n.mac, { ...n, hostname: n.hostname ?? prev?.hostname ?? null });
  }
  return [...byMac.values()];
}

/** Whether focus is on `el` or inside it. */
function holdsFocus(el: HTMLElement | null | undefined): boolean {
  if (!el) return false;
  const active = el.ownerDocument.activeElement;
  return active !== null && el.contains(active);
}

/**
 * Modal list of LAN devices: what this Deck has seen recently, plus Scan network
 * (the whole home network, about 10 s) and Find by IP or name (one address). Each
 * entry is one focusable row. Nothing found is remembered. B closes, which also
 * cancels a running scan.
 */
export function NetworkPicker({ onPick, closeModal }: Props) {
  const [items, setItems] = useState<Neighbour[] | null>(null);
  const [gateway, setGateway] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [scan, setScan] = useState<ScanState>({ phase: "idle" });
  const [address, setAddress] = useState("");
  const [finding, setFinding] = useState(false);
  const [findError, setFindError] = useState<string | null>(null);
  const { devices } = useDevices();

  const mounted = useRef(true);
  const scanning = useRef(false);
  const findingRef = useRef(false);
  const picked = useRef(false);
  const firstRef = useRef<HTMLDivElement>(null);
  const scanRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      // Closing the picker (B, Cancel, or a pick) stops a scan that is still running.
      if (scanning.current) void cancelScan().catch(() => undefined);
    };
  }, []);

  const load = useCallback(() => {
    setItems(null);
    setFailed(false);
    currentNetwork()
      .then((net) => mounted.current && setGateway(net?.gateway ?? null))
      .catch(() => mounted.current && setGateway(null));
    neighbours()
      .then((list) => mounted.current && setItems(list))
      .catch((e: unknown) => {
        console.error("[Wake Dispatch] neighbours failed", e);
        if (!mounted.current) return;
        setItems([]);
        setFailed(true);
      });
  }, []);

  useEffect(load, [load]);

  // Once the list is in: the first entry if there is one, else Scan network.
  // preferredFocus alone doesn't win (the footer already holds focus), and
  // someone who already moved to Cancel keeps their place.
  const loaded = items !== null;
  useEffect(() => {
    if (!loaded || holdsFocus(cancelRef.current)) return;
    focusSoon(() => (items && items.length > 0 ? firstRef.current : scanRef.current));
  }, [loaded]);

  const pick = (n: Neighbour) => {
    if (picked.current) return;
    picked.current = true;
    onPick(n);
    closeModal?.();
  };

  const runScan = async (confirmAway: boolean) => {
    if (scanning.current) return;
    scanning.current = true;
    setScan({ phase: "scanning" });
    try {
      const result = await scanNetwork(confirmAway);
      if (!mounted.current) return;
      if (result.ok) {
        setItems((prev) => merge(prev ?? [], result.neighbours));
        setFailed(false);
        setGateway(result.gateway);
        setScan({ phase: "done", found: result.found, named: result.named });
        // Move to the results only if focus is still on Scan network.
        if (result.neighbours.length > 0 && holdsFocus(scanRef.current)) {
          focusSoon(() => firstRef.current);
        }
        return;
      }
      if (result.cancelled) setScan({ phase: "idle" });
      else if (result.needs_confirm) {
        setScan({ phase: "idle" });
        showModal(
          <ConfirmAction
            title={PICKER.awayTitle}
            body={PICKER.awayBody}
            okText={PICKER.awayOk}
            onOK={() => void runScan(true)}
          />,
        );
      } else if (result.busy) setScan({ phase: "message", text: PICKER.scanBusy, error: false });
      else if (result.retry_in !== undefined) {
        setScan({ phase: "message", text: PICKER.scanRetryIn(result.retry_in), error: false });
      } else setScan({ phase: "message", text: result.error, error: true });
    } catch (e) {
      console.error("[Wake Dispatch] scan_network failed", e);
      if (mounted.current) setScan({ phase: "message", text: PICKER.failed, error: true });
    } finally {
      scanning.current = false;
    }
  };

  const stopScan = () => {
    if (!scanning.current) return;
    // The pending scan call then resolves with cancelled: true and goes back to idle.
    void cancelScan().catch((e: unknown) => console.warn("[Wake Dispatch] cancel_scan failed", e));
  };

  const find = async () => {
    if (findingRef.current) return;
    const text = address.trim();
    if (text === "") {
      setFindError(PICKER.findEmpty);
      return;
    }
    findingRef.current = true;
    setFinding(true);
    setFindError(null);
    try {
      const result = await findHost(text);
      if (!mounted.current) return;
      if (result.ok) {
        pick({ ip: result.ip, mac: result.mac, iface: "", hostname: result.name });
        return;
      }
      if (!result.cancelled) setFindError(result.error);
    } catch (e) {
      console.error("[Wake Dispatch] find_host failed", e);
      if (mounted.current) setFindError(PICKER.failed);
    } finally {
      findingRef.current = false;
      if (mounted.current) setFinding(false);
    }
  };

  const added = new Set((devices ?? []).map((d) => d.mac.toLowerCase()));
  const sorted = items
    ? items
        .map((n, i) => ({ n, i }))
        .sort((a, b) => rank(a.n, gateway) - rank(b.n, gateway) || a.i - b.i)
        .map(({ n }) => n)
    : null;

  const scanStatus =
    scan.phase === "scanning" ? (
      <span style={{ display: "inline-flex", alignItems: "center", gap: "8px" }}>
        <Spinner style={{ width: "16px", height: "16px" }} />
        {PICKER.scanning}
      </span>
    ) : scan.phase === "done" ? (
      PICKER.scanFound(scan.found, scan.named)
    ) : scan.phase === "message" ? (
      scan.error ? (
        <InlineError>{scan.text}</InlineError>
      ) : (
        scan.text
      )
    ) : (
      PICKER.scanHint
    );

  return (
    <ModalRoot onCancel={closeModal} closeModal={closeModal}>
      <DialogHeader>{PICKER.title}</DialogHeader>
      <DialogBodyText style={{ marginBottom: "12px" }}>{PICKER.intro}</DialogBodyText>

      {sorted === null ? (
        <Field
          description={
            <span style={{ display: "inline-flex", alignItems: "center", gap: "8px" }}>
              <Spinner style={{ width: "16px", height: "16px" }} />
              {PICKER.loading}
            </span>
          }
          bottomSeparator="none"
          focusable={false}
        />
      ) : failed && sorted.length === 0 ? (
        <Field description={<InlineError>{PICKER.failed}</InlineError>} bottomSeparator="none" focusable={false} />
      ) : sorted.length === 0 ? (
        <>
          <Field label={PICKER.empty} description={PICKER.asleepHint} bottomSeparator="none" focusable={false} />
          <Field description={PICKER.macHowTo} bottomSeparator="none" focusable={false} />
        </>
      ) : (
        <Focusable style={{ display: "flex", flexDirection: "column" }}>
          {sorted.map((n, i) => {
            const isRouter = gateway !== null && n.ip === gateway;
            const name = n.hostname ? displayName(n.hostname) : n.ip;
            const already = added.has(n.mac.toLowerCase());
            // Already added stays selectable: picking it again fills the editor
            // with its current address, which helps when the PC moved.
            return (
              <Field
                key={`${n.mac}-${n.ip}`}
                ref={i === 0 ? firstRef : undefined}
                preferredFocus={i === 0}
                label={`${name}${isRouter ? ` ${PICKER.router}` : ""}`}
                description={[n.ip, n.mac, ...(already ? [PICKER.alreadyAdded] : [])].join(" · ")}
                focusable
                highlightOnFocus
                bottomSeparator="standard"
                onActivate={() => pick(n)}
                onClick={() => pick(n)}
              />
            );
          })}
        </Focusable>
      )}

      <Focusable flow-children="horizontal" style={{ display: "flex", gap: "8px", marginTop: "12px" }}>
        <div ref={scanRef} style={{ flex: 1 }}>
          {/* Never disabled while scanning (it may hold focus); repeat presses are ignored. */}
          <DialogButton onClick={() => void runScan(false)}>{scan.phase === "scanning" ? PICKER.scanning : PICKER.scan}</DialogButton>
        </div>
        {scan.phase === "scanning" && (
          <DialogButton style={{ flex: 1 }} onClick={stopScan}>
            {PICKER.cancelScan}
          </DialogButton>
        )}
      </Focusable>
      <Field description={scanStatus} bottomSeparator="none" focusable={false} />

      <TextField
        label={PICKER.find}
        value={address}
        description={hintOrError(PICKER.findHint, findError)}
        onChange={(e) => {
          setAddress(e.target.value);
          setFindError(null);
        }}
      />
      <Focusable style={{ display: "flex", marginTop: "4px" }}>
        <DialogButton onClick={() => void find()}>{finding ? PICKER.finding : PICKER.findButton}</DialogButton>
      </Focusable>

      <DialogFooter>
        <Focusable flow-children="horizontal" style={{ display: "flex", gap: "8px", marginTop: "12px" }}>
          <DialogButton onClick={load}>{PICKER.refresh}</DialogButton>
          <DialogButtonSecondary ref={cancelRef} onClick={closeModal}>
            {PICKER.cancel}
          </DialogButtonSecondary>
        </Focusable>
      </DialogFooter>
    </ModalRoot>
  );
}
