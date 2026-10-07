import {
  ConfirmModal,
  DialogButton,
  DialogButtonPrimary,
  DialogButtonSecondary,
  DialogFooter,
  DialogHeader,
  DropdownItem,
  Focusable,
  ModalRoot,
  NavEntryPositionPreferences,
  TextField,
  ToggleField,
  showModal,
} from "@decky/ui";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { FaChevronDown, FaChevronRight } from "react-icons/fa";

import { currentNetwork, validateMac, type AutoTrigger, type Device, type Neighbour } from "../api";
import { badMacChar } from "../format";
import { toastInfo } from "../notify";
import { ADD_DEVICE_FOCUS, deleteDevice, neighbourOf, requestFocus, saveDevice } from "../store";
import { DEFAULT_BROADCAST, DEFAULT_PORT, EDITOR, S, TOAST } from "../strings";
import { ConfirmAction } from "./ConfirmAction";
import { focusSoon } from "./focus";
import { InlineError, hintOrError } from "./InlineError";
import { NetworkPicker } from "./NetworkPicker";

// status_check is the "Check if it's awake" dropdown; the rest are Device fields.
type FieldName =
  | "name"
  | "mac"
  | "status_check"
  | "home_gateway"
  | "host"
  | "status_port"
  | "port"
  | "broadcast"
  | "secureon";
type Errors = Partial<Record<FieldName, string>>;
type CheckMode = "none" | "sunshine" | "ssh" | "rdp" | "other";
type AutoChoice = "never" | "boot" | "resume" | "both";

interface Props {
  device?: Device;
  /** Where focus should go once the editor closes (a device id or ADD_DEVICE_FOCUS). */
  onFocusTarget?: (id: string) => void;
  closeModal?: () => void;
}

/** Top-to-bottom order on screen; the first invalid one takes focus after a failed Save. */
const FIELD_ORDER: readonly FieldName[] = [
  "name",
  "mac",
  "status_check",
  "home_gateway",
  "host",
  "status_port",
  "port",
  "broadcast",
  "secureon",
];
const MORE_FIELDS: readonly FieldName[] = ["host", "status_port", "port", "broadcast", "secureon"];

const PRESET_PORTS: Partial<Record<CheckMode, number>> = { sunshine: 47989, ssh: 22, rdp: 3389 };

const CHECK_OPTIONS: { data: CheckMode; label: string }[] = [
  { data: "none", label: EDITOR.checkNone },
  { data: "sunshine", label: EDITOR.checkSunshine },
  { data: "ssh", label: EDITOR.checkSsh },
  { data: "rdp", label: EDITOR.checkRdp },
  { data: "other", label: EDITOR.checkOther },
];

const AUTO_OPTIONS: { data: AutoChoice; label: string }[] = [
  { data: "never", label: EDITOR.autoNever },
  { data: "boot", label: EDITOR.autoBoot },
  { data: "resume", label: EDITOR.autoResume },
  { data: "both", label: EDITOR.autoBoth },
];

const AUTO_TRIGGERS: Record<AutoChoice, AutoTrigger[]> = {
  never: [],
  boot: ["boot"],
  resume: ["resume"],
  both: ["boot", "resume"],
};

function autoChoice(auto: readonly AutoTrigger[]): AutoChoice {
  const boot = auto.includes("boot");
  const resume = auto.includes("resume");
  return boot && resume ? "both" : boot ? "boot" : resume ? "resume" : "never";
}

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

function firstInvalid(errors: Errors): FieldName | null {
  return FIELD_ORDER.find((f) => errors[f]) ?? null;
}

/** Open the add (no device) or edit modal; focus returns to the right row's Wake when it closes. */
export function openDeviceEditor(device?: Device): void {
  let target = device?.id ?? ADD_DEVICE_FOCUS;
  showModal(<DeviceEditor device={device} onFocusTarget={(id) => (target = id)} />, undefined, {
    fnOnClose: () => requestFocus(target),
  });
}

/**
 * Ask, then delete. Opens on Cancel. Once the device is gone, `onRemoved` gets
 * the focus target that replaces its row: the next row's Wake, else the
 * previous one's, else Add device. If deleting fails (already toasted), nothing
 * else happens.
 */
export function confirmDeleteDevice(device: Device, onRemoved: (nextFocus: string) => void): void {
  showModal(
    <ConfirmAction
      title={S.deleteTitle(device.name)}
      body={S.deleteBody}
      okText={S.delete}
      destructive
      onOK={() => {
        const next = neighbourOf(device.id) ?? ADD_DEVICE_FOCUS;
        void deleteDevice(device.id).then((removed) => {
          if (removed) onRemoved(next);
        });
      }}
    />,
  );
}

/**
 * Add/edit modal, the same layout for both. The everyday fields come first and
 * the rarely needed ones sit under More settings, folded, so Save is a few
 * D-pad presses away. Only the name needs typing.
 */
export function DeviceEditor({ device, onFocusTarget, closeModal }: Props) {
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

  const [showMore, setShowMore] = useState(false);
  const [pickedIp, setPickedIp] = useState<string | null>(null);
  const [errors, setErrors] = useState<Errors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // Set synchronously so a second Save press during the MAC check is ignored.
  const savingRef = useRef(false);
  const [focusField, setFocusField] = useState<{ field: FieldName; seq: number } | null>(null);
  const closing = useRef(false);
  const fieldRefs = useRef<Partial<Record<FieldName, HTMLDivElement | null>>>({});

  const draft = JSON.stringify([name, mac, broadcast, port, host, statusPort, secureon, auto, homeGateway]);
  const [initialDraft] = useState(draft);
  const dirty = draft !== initialDraft;

  // After a failed Save, once More settings has rendered, focus the first bad field.
  useEffect(() => {
    if (!focusField) return;
    focusSoon(() => fieldRefs.current[focusField.field], { centre: true });
  }, [focusField]);

  const setError = (field: FieldName, message: string | undefined) =>
    setErrors((prev) => ({ ...prev, [field]: message }));

  const showErrors = (bad: Errors, summary: string | null) => {
    setErrors((prev) => ({ ...prev, ...bad }));
    setFormError(summary);
    const first = firstInvalid(bad);
    if (!first) return;
    if (MORE_FIELDS.includes(first)) setShowMore(true);
    setFocusField((prev) => ({ field: first, seq: (prev?.seq ?? 0) + 1 }));
  };

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

  const captureHome = async () => {
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

  const changeAuto = (choice: AutoChoice) => {
    const next = AUTO_TRIGGERS[choice];
    // Turning automation on for the first time limits it to the current network.
    if (auto.length === 0 && next.length > 0 && homeGateway === null) void captureHome();
    setAuto(next);
  };

  const toggleHome = (on: boolean) => {
    if (on) {
      void captureHome();
    } else {
      setHomeGateway(null);
      setError("home_gateway", undefined);
    }
  };

  const changeCheckMode = (mode: CheckMode) => {
    setCheckMode(mode);
    setError("status_check", undefined);
    setError("status_port", undefined);
    const preset = PRESET_PORTS[mode];
    if (preset !== undefined) setStatusPort(String(preset));
    else if (mode === "none") setStatusPort("");
    else {
      // "Another port…": open More settings and go straight to the port field.
      setShowMore(true);
      setFocusField((prev) => ({ field: "status_port", seq: (prev?.seq ?? 0) + 1 }));
    }
  };

  const checkMac = async (): Promise<{ mac: string } | { error: string }> => {
    if (mac.trim() === "") return { error: EDITOR.macRequired };
    const bad = badMacChar(mac);
    if (bad !== null) return { error: EDITOR.macBadChar(bad) };
    try {
      const result = await validateMac(mac);
      return result.ok ? { mac: result.mac } : { error: result.error };
    } catch (e) {
      console.error("[Wake Dispatch] validate_mac failed", e);
      return { error: EDITOR.macCheckFailed };
    }
  };

  const pick = (n: Neighbour) => {
    setMac(n.mac);
    setHost(n.ip);
    setPickedIp(n.ip);
    setError("mac", undefined);
    setError("host", undefined);
    setError("status_check", undefined);
    if (name.trim() === "") setName(nameFromNeighbour(n));
  };

  const save = async () => {
    if (savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    try {
      await saveChecked();
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };

  const saveChecked = async () => {
    setFormError(null);
    const bad: Errors = {};
    if (name.trim() === "") bad.name = EDITOR.nameRequired;
    const udp = parsePort(port, false);
    const tcp = checkMode === "none" ? null : parsePort(statusPort, checkMode !== "other");
    if (udp === undefined) bad.port = EDITOR.portInvalid;
    if (tcp === undefined) bad.status_port = EDITOR.portInvalid;
    if (checkMode !== "none" && host.trim() === "") bad.status_check = EDITOR.checkNeedsHost;
    const macResult = await checkMac();
    if ("error" in macResult) bad.mac = macResult.error;
    if (Object.keys(bad).length > 0) {
      showErrors(bad, EDITOR.fixFields);
      return;
    }
    const normalisedMac = "mac" in macResult ? macResult.mac : "";

    try {
      const result = await saveDevice({
        id: device?.id ?? "",
        name: name.trim(),
        mac: normalisedMac,
        broadcast: broadcast.trim() || DEFAULT_BROADCAST,
        port: udp ?? DEFAULT_PORT,
        host: host.trim() || null,
        status_port: checkMode === "none" ? null : (tcp ?? null),
        secureon: secureon.trim() || null,
        auto,
        home_gateway: homeGateway,
      });
      if (result.ok) {
        if (!device) toastInfo(TOAST.added(name.trim()), TOAST.addedBody);
        if (result.savedId) onFocusTarget?.(result.savedId);
        closing.current = true;
        closeModal?.();
        return;
      }
      // A bad router MAC belongs to the "Only on this network" row.
      const field = (result.field === "home_gateway_mac" ? "home_gateway" : result.field) as FieldName | undefined;
      if (result.atEdited && field && FIELD_ORDER.includes(field)) {
        showErrors({ [field]: result.error }, EDITOR.fixFields);
      } else {
        setFormError(result.error);
      }
    } catch (e) {
      console.error("[Wake Dispatch] save_devices failed", e);
      setFormError(EDITOR.saveFailed);
    }
  };

  /** Wraps a control so a failed Save can scroll to and focus it. */
  const slot = (field: FieldName, children: ReactNode) => (
    <div
      ref={(el) => {
        fieldRefs.current[field] = el;
      }}
    >
      {children}
    </div>
  );

  const hasAuto = auto.length > 0;
  const needsHost = checkMode !== "none" && host.trim() === "";

  const macDescription = hintOrError(
    pickedIp ? EDITOR.foundAt(pickedIp) : mac.trim() === "" ? EDITOR.macHelp : undefined,
    errors.mac,
  );

  const checkDescription = hintOrError(
    needsHost ? EDITOR.checkNeedsHost : checkMode === "other" ? EDITOR.checkOtherHint : EDITOR.checkHint,
    errors.status_check,
  );

  const homeDescription = hintOrError(
    homeGateway === null ? EDITOR.homeOnlyOff : EDITOR.homeOnlyOn(homeGateway),
    errors.home_gateway,
  );

  const chevron = showMore ? <FaChevronDown size={12} /> : <FaChevronRight size={12} />;

  return (
    <ModalRoot onCancel={requestClose} closeModal={requestClose}>
      <DialogHeader>{device ? EDITOR.editTitle : EDITOR.addTitle}</DialogHeader>

      <Focusable style={{ margin: "0 0 8px" }}>
        <DialogButton onClick={() => showModal(<NetworkPicker onPick={pick} />)}>{EDITOR.pickFromNetwork}</DialogButton>
      </Focusable>

      {slot(
        "name",
        <TextField
          label={EDITOR.name}
          value={name}
          description={hintOrError(undefined, errors.name)}
          onChange={(e) => {
            setName(e.target.value);
            setError("name", undefined);
          }}
        />,
      )}

      {slot(
        "mac",
        <TextField
          label={EDITOR.mac}
          value={mac}
          description={macDescription}
          onChange={(e) => {
            setMac(e.target.value);
            setPickedIp(null);
            setError("mac", undefined);
          }}
          onBlur={() => {
            if (mac.trim() === "") return;
            void checkMac().then((r) => setError("mac", "error" in r ? r.error : undefined));
          }}
        />,
      )}

      {slot(
        "status_check",
        <DropdownItem
          label={EDITOR.checkLabel}
          description={checkDescription}
          rgOptions={CHECK_OPTIONS}
          selectedOption={checkMode}
          onChange={(opt) => changeCheckMode(opt.data as CheckMode)}
        />,
      )}

      <DropdownItem
        label={EDITOR.autoLabel}
        description={auto.includes("resume") ? EDITOR.autoResumeHint : EDITOR.autoHint}
        rgOptions={AUTO_OPTIONS}
        selectedOption={autoChoice(auto)}
        onChange={(opt) => changeAuto(opt.data as AutoChoice)}
      />
      {hasAuto &&
        slot(
          "home_gateway",
          <ToggleField
            label={EDITOR.homeOnly}
            description={homeDescription}
            indentLevel={1}
            checked={homeGateway !== null}
            onChange={toggleHome}
          />,
        )}

      <Focusable style={{ margin: "16px 0 8px" }}>
        <DialogButton
          onClick={() => setShowMore((v) => !v)}
          style={{ display: "flex", alignItems: "center", justifyContent: "flex-start", gap: "8px" }}
        >
          {chevron}
          {EDITOR.moreSettings}
        </DialogButton>
      </Focusable>
      {showMore && (
        <>
          {slot(
            "host",
            <TextField
              label={EDITOR.statusHost}
              value={host}
              description={hintOrError(EDITOR.statusHostHint, errors.host)}
              onChange={(e) => {
                setHost(e.target.value);
                setError("host", undefined);
                setError("status_check", undefined);
              }}
            />,
          )}
          {slot(
            "status_port",
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
            />,
          )}
          {slot(
            "port",
            <TextField
              label={EDITOR.port}
              value={port}
              mustBeNumeric
              description={hintOrError(EDITOR.portHint, errors.port)}
              onChange={(e) => {
                setPort(e.target.value);
                setError("port", undefined);
              }}
            />,
          )}
          {slot(
            "broadcast",
            <TextField
              label={EDITOR.broadcast}
              value={broadcast}
              description={hintOrError(EDITOR.broadcastHint, errors.broadcast)}
              onChange={(e) => {
                setBroadcast(e.target.value);
                setError("broadcast", undefined);
              }}
            />,
          )}
          {slot(
            "secureon",
            <TextField
              label={EDITOR.secureon}
              value={secureon}
              description={hintOrError(EDITOR.secureonHint, errors.secureon)}
              onChange={(e) => {
                setSecureon(e.target.value);
                setError("secureon", undefined);
              }}
            />,
          )}
        </>
      )}

      {formError && (formError !== EDITOR.fixFields || Object.values(errors).some(Boolean)) && (
        <div style={{ marginTop: "12px" }}>
          <InlineError>{formError}</InlineError>
        </div>
      )}

      <DialogFooter>
        <Focusable
          flow-children="horizontal"
          navEntryPreferPosition={NavEntryPositionPreferences.FIRST}
          style={{ display: "flex", gap: "8px", marginTop: "16px" }}
        >
          <DialogButtonPrimary onClick={() => void save()}>{saving ? EDITOR.saving : EDITOR.save}</DialogButtonPrimary>
          <DialogButtonSecondary onClick={requestClose}>{EDITOR.cancel}</DialogButtonSecondary>
        </Focusable>
      </DialogFooter>
    </ModalRoot>
  );
}
