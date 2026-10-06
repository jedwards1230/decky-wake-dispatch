import {
  ConfirmModal,
  DialogButton,
  DialogFooter,
  DialogHeader,
  DialogSubHeader,
  DropdownItem,
  Focusable,
  ModalRoot,
  TextField,
  ToggleField,
  showModal,
} from "@decky/ui";
import { useRef, useState } from "react";

import { currentNetwork, validateMac, type AutoTrigger, type Device, type Neighbour } from "../api";
import { toastInfo } from "../notify";
import { saveDevice } from "../store";
import { DEFAULT_BROADCAST, DEFAULT_PORT, EDITOR, TOAST } from "../strings";
import { InlineError, hintOrError } from "./InlineError";
import { NetworkPicker } from "./NetworkPicker";

type FieldName = "name" | "mac" | "broadcast" | "port" | "host" | "status_port" | "secureon" | "home_gateway";
type Errors = Partial<Record<FieldName, string>>;
type CheckMode = "none" | "sunshine" | "ssh" | "rdp" | "other";

interface Props {
  device?: Device;
  closeModal?: () => void;
}

const FIELDS: readonly string[] = ["name", "mac", "broadcast", "port", "host", "status_port", "secureon", "home_gateway"];
const ADVANCED_FIELDS: readonly string[] = ["broadcast", "port", "host", "status_port", "secureon"];

const PRESET_PORTS: Partial<Record<CheckMode, number>> = { sunshine: 47989, ssh: 22, rdp: 3389 };

const CHECK_OPTIONS: { data: CheckMode; label: string }[] = [
  { data: "none", label: EDITOR.checkNone },
  { data: "sunshine", label: EDITOR.checkSunshine },
  { data: "ssh", label: EDITOR.checkSsh },
  { data: "rdp", label: EDITOR.checkRdp },
  { data: "other", label: EDITOR.checkOther },
];

function modeForPort(text: string): CheckMode {
  const t = text.trim();
  if (t === "") return "none";
  const match = (Object.keys(PRESET_PORTS) as CheckMode[]).find((m) => String(PRESET_PORTS[m]) === t);
  return match ?? "other";
}

function parsePort(text: string, allowEmpty: boolean): number | null | undefined {
  const t = text.trim();
  if (t === "") return allowEmpty ? null : undefined;
  if (!/^\d+$/.test(t)) return undefined;
  const n = Number(t);
  return n >= 1 && n <= 65535 ? n : undefined;
}

function nameFromNeighbour(n: Neighbour): string {
  return n.hostname ? n.hostname.split(".")[0].slice(0, 64) : EDITOR.pcAt(n.ip);
}

/** Form-level pointer to whatever is wrong, shown next to the footer. */
function summarise(errors: Errors): string | null {
  const bad = (Object.keys(errors) as FieldName[]).filter((k) => errors[k]);
  if (bad.length === 0) return null;
  if (bad.length === 1 && bad[0] === "name") return EDITOR.fixName;
  if (bad.length === 1 && bad[0] === "mac") return EDITOR.fixMac;
  return EDITOR.fixFields;
}

/** Add/edit modal. Only the name needs typing; everything else has a default or a picker. */
export function DeviceEditor({ device, closeModal }: Props) {
  const [name, setName] = useState(device?.name ?? "");
  const [mac, setMac] = useState(device?.mac ?? "");
  const [broadcast, setBroadcast] = useState(device?.broadcast ?? DEFAULT_BROADCAST);
  const [port, setPort] = useState(String(device?.port ?? DEFAULT_PORT));
  const [host, setHost] = useState(device?.host ?? "");
  const [statusPort, setStatusPort] = useState(device?.status_port != null ? String(device.status_port) : "");
  const [checkMode, setCheckMode] = useState<CheckMode>(() => modeForPort(statusPort));
  const [secureon, setSecureon] = useState(device?.secureon ?? "");
  const [auto, setAuto] = useState<AutoTrigger[]>(device?.auto ?? []);
  const [homeGateway, setHomeGateway] = useState<string | null>(device?.home_gateway ?? null);

  const [showAdvanced, setShowAdvanced] = useState(false);
  const [pickedIp, setPickedIp] = useState<string | null>(null);
  const [homeAutoOn, setHomeAutoOn] = useState(false);
  const [errors, setErrors] = useState<Errors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const closing = useRef(false);

  const draft = JSON.stringify([name, mac, broadcast, port, host, statusPort, secureon, auto, homeGateway]);
  const [initialDraft] = useState(draft);
  const dirty = draft !== initialDraft;

  const setError = (field: FieldName, message: string | undefined) =>
    setErrors((prev) => ({ ...prev, [field]: message }));

  /** B, Cancel and background dismiss all land here; a dirty form asks first. */
  const requestClose = () => {
    if (closing.current) return;
    closing.current = true;
    if (!dirty) {
      closeModal?.();
      return;
    }
    showModal(
      <ConfirmModal
        strTitle={EDITOR.discardTitle}
        strDescription={EDITOR.discardBody}
        strOKButtonText={EDITOR.discard}
        strCancelButtonText={EDITOR.keepEditing}
        onOK={() => closeModal?.()}
      />,
      undefined,
      {
        fnOnClose: () => {
          closing.current = false;
        },
      },
    );
  };

  const captureHome = async (automatic: boolean) => {
    try {
      const net = await currentNetwork();
      if (net) {
        setHomeGateway(net.gateway);
        setHomeAutoOn(automatic);
        setError("home_gateway", undefined);
      } else {
        setError("home_gateway", EDITOR.homeOnlyNoNetwork);
      }
    } catch (e) {
      console.error("[Wake Dispatch] current_network failed", e);
      setError("home_gateway", EDITOR.homeOnlyFailed);
    }
  };

  const toggleAuto = (trigger: AutoTrigger, on: boolean) => {
    const wasEmpty = auto.length === 0;
    setAuto((prev) => (on ? [...prev.filter((t) => t !== trigger), trigger] : prev.filter((t) => t !== trigger)));
    if (on && wasEmpty && homeGateway === null) void captureHome(true);
  };

  const toggleHome = (on: boolean) => {
    setHomeAutoOn(false);
    if (on) {
      void captureHome(false);
    } else {
      setHomeGateway(null);
      setError("home_gateway", undefined);
    }
  };

  const changeCheckMode = (mode: CheckMode) => {
    setCheckMode(mode);
    setError("status_port", undefined);
    const preset = PRESET_PORTS[mode];
    if (preset !== undefined) setStatusPort(String(preset));
    else if (mode === "none") setStatusPort("");
    else setShowAdvanced(true);
  };

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
      setError("mac", EDITOR.macCheckFailed);
    }
    return null;
  };

  const pick = (n: Neighbour) => {
    setMac(n.mac);
    setHost(n.ip);
    setPickedIp(n.ip);
    setError("mac", undefined);
    if (name.trim() === "") setName(nameFromNeighbour(n));
  };

  const save = async () => {
    if (saving) return;
    setFormError(null);
    const next: Errors = {};
    if (name.trim() === "") next.name = EDITOR.nameRequired;
    const udp = parsePort(port, false);
    const tcp = checkMode === "none" ? null : parsePort(statusPort, true);
    if (udp === undefined) next.port = EDITOR.portInvalid;
    if (tcp === undefined) next.status_port = EDITOR.portInvalid;
    const normalisedMac = await checkMac();
    if (!normalisedMac) next.mac = errors.mac ?? EDITOR.fixMac;
    if (Object.keys(next).length > 0) {
      setErrors((prev) => ({ ...prev, ...next, mac: normalisedMac ? undefined : prev.mac ?? next.mac }));
      setFormError(summarise(next));
      if (next.port || next.status_port) setShowAdvanced(true);
      return;
    }

    setSaving(true);
    try {
      const result = await saveDevice({
        id: device?.id ?? "",
        name: name.trim(),
        mac: normalisedMac ?? "",
        broadcast: broadcast.trim() || DEFAULT_BROADCAST,
        port: udp ?? DEFAULT_PORT,
        host: host.trim() || null,
        status_port: tcp ?? null,
        secureon: secureon.trim() || null,
        auto,
        home_gateway: homeGateway,
      });
      if (result.ok) {
        if (!device) toastInfo(TOAST.added(name.trim()), TOAST.addedBody);
        closing.current = true;
        closeModal?.();
        return;
      }
      const field = result.field;
      if (result.atEdited && field && FIELDS.includes(field)) {
        setError(field as FieldName, result.error);
        setFormError(summarise({ [field]: result.error }));
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

  const hasAuto = auto.length > 0;
  const needsHost = checkMode !== "none" && host.trim() === "";

  const homeDescription = !hasAuto
    ? EDITOR.homeOnlyNeedsTrigger
    : hintOrError(
        homeGateway === null ? EDITOR.homeOnlyOff : homeAutoOn ? EDITOR.homeOnlyAutoOn : EDITOR.homeOnlyOn(homeGateway),
        errors.home_gateway,
      );

  const macHint = pickedIp
    ? checkMode === "none"
      ? EDITOR.foundAtChooseCheck(pickedIp)
      : EDITOR.foundAt(pickedIp)
    : EDITOR.macHint;

  const pickButton = (
    <Focusable style={{ margin: "8px 0" }}>
      <DialogButton onClick={() => showModal(<NetworkPicker onPick={pick} />)}>{EDITOR.pickFromNetwork}</DialogButton>
    </Focusable>
  );

  const nameField = (
    <TextField
      label={EDITOR.name}
      value={name}
      description={hintOrError(undefined, errors.name)}
      onChange={(e) => {
        setName(e.target.value);
        setError("name", undefined);
      }}
    />
  );

  const macField = (
    <TextField
      label={EDITOR.mac}
      value={mac}
      description={hintOrError(macHint, errors.mac)}
      onChange={(e) => {
        setMac(e.target.value);
        setError("mac", undefined);
      }}
      onBlur={() => {
        if (mac.trim() !== "") void checkMac();
      }}
    />
  );

  return (
    <ModalRoot onCancel={requestClose} closeModal={requestClose}>
      <DialogHeader>{device ? EDITOR.editTitle : EDITOR.addTitle}</DialogHeader>

      {device ? (
        <>
          {nameField}
          {macField}
          {pickButton}
        </>
      ) : (
        <>
          {pickButton}
          <div style={{ fontSize: "12px", opacity: 0.75, marginBottom: "8px" }}>{EDITOR.orTypeMac}</div>
          {nameField}
          {macField}
        </>
      )}

      <DropdownItem
        label={EDITOR.checkLabel}
        description={needsHost ? EDITOR.checkNeedsHost : EDITOR.checkHint}
        rgOptions={CHECK_OPTIONS}
        selectedOption={checkMode}
        onChange={(opt) => changeCheckMode(opt.data as CheckMode)}
      />

      <DialogSubHeader style={{ marginTop: "16px" }}>{EDITOR.automationTitle}</DialogSubHeader>
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
        description={homeDescription}
        indentLevel={1}
        disabled={!hasAuto}
        checked={homeGateway !== null}
        onChange={toggleHome}
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
              const v = e.target.value;
              setStatusPort(v);
              setCheckMode((prev) => (v.trim() === "" && prev === "other" ? "other" : modeForPort(v)));
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
          <DialogButton onClick={requestClose}>{EDITOR.cancel}</DialogButton>
          <DialogButton onClick={() => void save()}>{saving ? EDITOR.saving : EDITOR.save}</DialogButton>
        </Focusable>
      </DialogFooter>
    </ModalRoot>
  );
}
