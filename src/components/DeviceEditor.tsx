import {
  DialogButton,
  DialogFooter,
  DialogHeader,
  DialogSubHeader,
  Focusable,
  ModalRoot,
  TextField,
  ToggleField,
  showModal,
} from "@decky/ui";
import { useState } from "react";

import { currentNetwork, validateMac, type AutoTrigger, type Device, type Neighbour } from "../api";
import { saveDevice } from "../store";
import { DEFAULT_BROADCAST, DEFAULT_PORT, EDITOR } from "../strings";
import { InlineError, hintOrError } from "./InlineError";
import { NetworkPicker } from "./NetworkPicker";

type FieldName = "name" | "mac" | "broadcast" | "port" | "host" | "status_port" | "secureon" | "home_gateway";
type Errors = Partial<Record<FieldName, string>>;

interface Props {
  device?: Device;
  closeModal?: () => void;
}

const FIELDS: readonly string[] = ["name", "mac", "broadcast", "port", "host", "status_port", "secureon", "home_gateway"];
const ADVANCED_FIELDS: readonly string[] = ["broadcast", "port", "host", "status_port", "secureon"];

function parsePort(text: string, allowEmpty: boolean): number | null | undefined {
  const t = text.trim();
  if (t === "") return allowEmpty ? null : undefined;
  if (!/^\d+$/.test(t)) return undefined;
  const n = Number(t);
  return n >= 1 && n <= 65535 ? n : undefined;
}

function nameFromHostname(hostname: string | null): string {
  return hostname ? hostname.split(".")[0].slice(0, 64) : "";
}

/** Add/edit modal. Only the name needs typing; everything else has a default or a picker. */
export function DeviceEditor({ device, closeModal }: Props) {
  const [name, setName] = useState(device?.name ?? "");
  const [mac, setMac] = useState(device?.mac ?? "");
  const [broadcast, setBroadcast] = useState(device?.broadcast ?? DEFAULT_BROADCAST);
  const [port, setPort] = useState(String(device?.port ?? DEFAULT_PORT));
  const [host, setHost] = useState(device?.host ?? "");
  const [statusPort, setStatusPort] = useState(device?.status_port != null ? String(device.status_port) : "");
  const [secureon, setSecureon] = useState(device?.secureon ?? "");
  const [auto, setAuto] = useState<AutoTrigger[]>(device?.auto ?? []);
  const [homeGateway, setHomeGateway] = useState<string | null>(device?.home_gateway ?? null);

  const [showAdvanced, setShowAdvanced] = useState(false);
  const [pickedIp, setPickedIp] = useState<string | null>(null);
  const [errors, setErrors] = useState<Errors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const setError = (field: FieldName, message: string | undefined) =>
    setErrors((prev) => ({ ...prev, [field]: message }));

  const toggleAuto = (trigger: AutoTrigger, on: boolean) =>
    setAuto((prev) => (on ? [...prev.filter((t) => t !== trigger), trigger] : prev.filter((t) => t !== trigger)));

  const checkMac = async (): Promise<string | null> => {
    if (mac.trim() === "") {
      setError("mac", EDITOR.macRequired);
      return null;
    }
    try {
      const result = await validateMac(mac);
      if (result.ok) {
        setError("mac", undefined);
        return result.mac;
      }
      setError("mac", result.error);
    } catch (e) {
      console.error("[Wake Dispatch] validate_mac failed", e);
      setError("mac", EDITOR.saveFailed);
    }
    return null;
  };

  const pick = (n: Neighbour) => {
    setMac(n.mac);
    setHost(n.ip);
    setPickedIp(n.ip);
    setError("mac", undefined);
    if (name.trim() === "") setName(nameFromHostname(n.hostname));
  };

  const toggleHome = async (on: boolean) => {
    if (!on) {
      setHomeGateway(null);
      setError("home_gateway", undefined);
      return;
    }
    try {
      const net = await currentNetwork();
      if (net) {
        setHomeGateway(net.gateway);
        setError("home_gateway", undefined);
      } else {
        setError("home_gateway", EDITOR.homeOnlyNoNetwork);
      }
    } catch (e) {
      console.error("[Wake Dispatch] current_network failed", e);
      setError("home_gateway", EDITOR.homeOnlyFailed);
    }
  };

  const save = async () => {
    if (saving) return;
    setFormError(null);
    const next: Errors = {};
    if (name.trim() === "") next.name = EDITOR.nameRequired;
    const udp = parsePort(port, false);
    const tcp = parsePort(statusPort, true);
    if (udp === undefined) next.port = EDITOR.portInvalid;
    if (tcp === undefined) next.status_port = EDITOR.portInvalid;
    const normalisedMac = await checkMac();
    setErrors((prev) => ({ ...prev, ...next, mac: normalisedMac ? undefined : prev.mac }));
    if (Object.keys(next).length > 0 || !normalisedMac) {
      if (next.port || next.status_port) setShowAdvanced(true);
      return;
    }

    setSaving(true);
    try {
      const result = await saveDevice({
        id: device?.id ?? "",
        name: name.trim(),
        mac: normalisedMac,
        broadcast: broadcast.trim() || DEFAULT_BROADCAST,
        port: udp ?? DEFAULT_PORT,
        host: host.trim() || null,
        status_port: tcp ?? null,
        secureon: secureon.trim() || null,
        auto,
        home_gateway: homeGateway,
      });
      if (result.ok) {
        closeModal?.();
        return;
      }
      const field = result.field;
      if (result.atEdited && field && FIELDS.includes(field)) {
        setError(field as FieldName, result.error);
        if (ADVANCED_FIELDS.includes(field)) setShowAdvanced(true);
      } else {
        setFormError(result.error);
      }
    } catch (e) {
      console.error("[Wake Dispatch] save_devices failed", e);
      setFormError(EDITOR.saveFailed);
    } finally {
      setSaving(false);
    }
  };

  return (
    <ModalRoot onCancel={closeModal} closeModal={closeModal}>
      <DialogHeader>{device ? EDITOR.editTitle : EDITOR.addTitle}</DialogHeader>

      <TextField
        label={EDITOR.name}
        value={name}
        description={hintOrError(undefined, errors.name)}
        onChange={(e) => {
          setName(e.target.value);
          setError("name", undefined);
        }}
      />
      <TextField
        label={EDITOR.mac}
        value={mac}
        description={hintOrError(pickedIp ? EDITOR.pickedHostHint(pickedIp) : EDITOR.macHint, errors.mac)}
        onChange={(e) => {
          setMac(e.target.value);
          setError("mac", undefined);
        }}
        onBlur={() => {
          if (mac.trim() !== "") void checkMac();
        }}
      />
      <Focusable style={{ margin: "8px 0 16px" }}>
        <DialogButton onClick={() => showModal(<NetworkPicker onPick={pick} />)}>{EDITOR.pickFromNetwork}</DialogButton>
      </Focusable>

      <DialogSubHeader>{EDITOR.automationTitle}</DialogSubHeader>
      <div style={{ fontSize: "12px", opacity: 0.75, marginBottom: "4px" }}>{EDITOR.automationHint}</div>
      <ToggleField
        label={EDITOR.onBoot}
        description={EDITOR.onBootHint}
        checked={auto.includes("boot")}
        onChange={(on) => toggleAuto("boot", on)}
      />
      <ToggleField
        label={EDITOR.onResume}
        description={EDITOR.onResumeHint}
        checked={auto.includes("resume")}
        onChange={(on) => toggleAuto("resume", on)}
      />
      <ToggleField
        label={EDITOR.homeOnly}
        description={hintOrError(
          homeGateway ? EDITOR.homeOnlyOn(homeGateway) : EDITOR.homeOnlyOff,
          errors.home_gateway,
        )}
        checked={homeGateway !== null}
        onChange={(on) => void toggleHome(on)}
      />

      <Focusable style={{ margin: "16px 0 8px" }}>
        <DialogButton onClick={() => setShowAdvanced((v) => !v)}>
          {showAdvanced ? `▾ ${EDITOR.hideAdvanced}` : `▸ ${EDITOR.showAdvanced}`}
        </DialogButton>
      </Focusable>
      {showAdvanced && (
        <>
          <TextField
            label={EDITOR.broadcast}
            value={broadcast}
            description={hintOrError(EDITOR.broadcastHint, errors.broadcast)}
            onChange={(e) => {
              setBroadcast(e.target.value);
              setError("broadcast", undefined);
            }}
          />
          <TextField
            label={EDITOR.port}
            value={port}
            mustBeNumeric
            description={hintOrError(EDITOR.portHint, errors.port)}
            onChange={(e) => {
              setPort(e.target.value);
              setError("port", undefined);
            }}
          />
          <TextField
            label={EDITOR.statusHost}
            value={host}
            description={hintOrError(EDITOR.statusHostHint, errors.host)}
            onChange={(e) => {
              setHost(e.target.value);
              setError("host", undefined);
            }}
          />
          <TextField
            label={EDITOR.statusPort}
            value={statusPort}
            mustBeNumeric
            description={hintOrError(EDITOR.statusPortHint, errors.status_port)}
            onChange={(e) => {
              setStatusPort(e.target.value);
              setError("status_port", undefined);
            }}
          />
          <TextField
            label={EDITOR.secureon}
            value={secureon}
            description={hintOrError(EDITOR.secureonHint, errors.secureon)}
            onChange={(e) => {
              setSecureon(e.target.value);
              setError("secureon", undefined);
            }}
          />
        </>
      )}

      {formError && (
        <div style={{ marginTop: "12px" }}>
          <InlineError>{formError}</InlineError>
        </div>
      )}

      <DialogFooter>
        <Focusable flow-children="horizontal" style={{ display: "flex", gap: "8px", marginTop: "16px" }}>
          <DialogButton onClick={closeModal}>{EDITOR.cancel}</DialogButton>
          <DialogButton onClick={() => void save()}>{saving ? EDITOR.saving : EDITOR.save}</DialogButton>
        </Focusable>
      </DialogFooter>
    </ModalRoot>
  );
}

