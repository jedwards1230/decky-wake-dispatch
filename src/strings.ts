// User-facing copy. Plain language, no jargon beyond "Wake-on-LAN".

export const PLUGIN_NAME = "Wake Dispatch";

export const DEFAULT_BROADCAST = "255.255.255.255";
export const DEFAULT_PORT = 9;

/** "Gaming PC", "Gaming PC and Office PC", "3 devices". */
export function names(list: readonly string[]): string {
  if (list.length === 1) return list[0];
  if (list.length === 2) return `${list[0]} and ${list[1]}`;
  return `${list.length} devices`;
}

export const S = {
  wakeAll: "Wake all",
  addDevice: "Add device",
  wake: "Wake",
  waking: "Sending…",
  wakeLabel: (name: string) => `Wake ${name}`,
  wakingLabel: (name: string) => `Sending wake to ${name}`,
  moreLabel: (name: string) => `More options for ${name}`,
  wakeAllLabel: "Wake all devices",
  edit: "Edit",
  devicesTitle: "Devices",
  backupTitle: "Backup",
  backupEntry: "Back up or restore",
  loading: "Loading devices…",
  loadFailed: "Couldn't load your devices. Choose Try again, or restart Decky Loader.",
  tryAgain: "Try again",

  emptyTitle: "Add the PC you want to wake",
  emptySteps: [
    "Turn the PC on, on the same network as this Deck.",
    "Choose Add device, then Pick from network.",
    "Put the PC to sleep and press Wake to test it.",
  ],
  emptyWolHint:
    "The PC needs Wake-on-LAN turned on in its BIOS/UEFI and network adapter, and usually a wired connection.",

  status: {
    awake: "Awake",
    asleep: "Asleep",
    unknown: "Unknown",
    checking: "Checking…",
  },

  deleteTitle: (name: string) => `Delete ${name}?`,
  deleteBody: "This removes it from Wake Dispatch. Nothing on the PC is changed.",
  delete: "Delete",
  deleteEllipsis: "Delete…",
  cancel: "Cancel",
  deleteFailed: "Couldn't delete the device",

  backendError: "The plugin's background service didn't answer. Try again, or restart Decky Loader.",
};

/** Per-device result of the last manual wake, shown in the row for a few minutes. */
export const ROW = {
  sent: (ago: string) => `Wake sent ${ago}`,
  checking: "Checking…",
  awake: "Awake",
  notWoken: "Didn't wake up. Check Wake-on-LAN on the PC.",
};

export const TOAST = {
  sentToOne: (name: string) => `Wake sent to ${name}`,
  sentTo: (n: number) => `Wake sent to ${n} devices`,
  sentSome: (sent: number, total: number) => `Wake sent to ${sent} of ${total} devices`,
  checkingAwake: "Checking if it's awake…",
  checkingAwakeMany: "Checking if they're awake…",
  mayTakeAMinute: "It may take up to a minute to start.",
  couldntSendTo: (who: string, error?: string) => `Couldn't send to ${who}${error ? `: ${error}` : ""}`,
  couldntWake: (name: string) => `Couldn't wake ${name}`,
  couldntSend: "Couldn't send the wake",
  checkConnected: "Check that this device is connected to the network.",
  noNetwork: "Couldn't reach the network",
  noNetworkBody: "Connect to your network and try again.",
  nothingSent: "Nothing was sent",
  nothingToWake: "No devices to wake.",
  automaticContext: (when: string) => `Automatic wake ${when}`,
  offHomeNetwork: "You're not on your home network, so it probably won't arrive.",

  isAwake: (who: string, many: boolean) => `${who} ${many ? "are" : "is"} awake`,
  isAwakeBody: "Ready to connect.",
  notWoken: (who: string, many: boolean) => `${who} ${many ? "haven't" : "hasn't"} woken up`,
  notWokenBody: "If it stays asleep, check that Wake-on-LAN is on in its BIOS/UEFI and network adapter settings.",

  added: (name: string) => `Added ${name}`,
  addedBody: "Press Wake to test it.",
};

export const AUTOMATION = {
  manual: "Manual only",
  boot: "Wakes when this Deck starts",
  resume: "Wakes when this Deck wakes from sleep",
  both: "Wakes when this Deck starts or wakes from sleep",
};

export const LAST = {
  sent: (when: string, ago: string, outcome: string) => `Last automatic wake: ${when}, ${ago} — ${outcome}`,
  skipped: (when: string, ago: string, reason: string) => `Automatic wake ${when} was skipped, ${ago}: ${reason}`,
  failed: (when: string, ago: string, reason: string) => `Automatic wake ${when} failed, ${ago}: ${reason}`,
  sentTo: (who: string) => `sent to ${who}`,
  sentPartial: (who: string, failed: number) => `sent to ${who}; ${failed} couldn't be sent`,
  sentBare: "sent",
  noNetwork: "no network connection",
  nothingToWake: "nothing to wake",
  unknownError: "couldn't send",
  onNext: (next: string) => `Automatic wake is on. Next: ${next}.`,
  nextBoot: "when this Deck starts",
  nextResume: "when this Deck wakes from sleep",
  nextBoth: "when this Deck starts or wakes from sleep",
};

export const EDITOR = {
  addTitle: "Add device",
  editTitle: "Edit device",
  name: "Name",
  nameRequired: "Give this device a name.",
  mac: "MAC address",
  macHelp:
    "Don't know it? Turn the PC on and use Pick from network. On Windows run getmac /v; on Linux, the link/ether line of ip link.",
  macBadChar: (ch: string) => `A MAC address uses only 0–9 and A–F (found "${ch}").`,
  macRequired: "Enter the PC's MAC address, or pick it from the network.",
  macCheckFailed: "Couldn't check the MAC address right now. Try Save again.",
  pickFromNetwork: "Pick from network",
  foundAt: (ip: string) => `Found at ${ip}.`,
  pcAt: (ip: string) => `PC at ${ip}`,

  checkLabel: "Check if it's awake",
  checkNone: "Don't check",
  checkSunshine: "Game streaming (Sunshine)",
  checkRemotePlay: "Steam Remote Play",
  checkSsh: "SSH",
  checkRdp: "Remote Desktop",
  checkOther: "Another port…",
  checkHint: "Pick the app you stream or connect with: Awake then means that app is ready, not just the PC.",
  checkOtherHint: "Set the port under More settings.",
  checkNeedsHost: "Pick the PC from the network, or turn this off.",

  autoLabel: "Wake automatically",
  autoHint: "Pressing Wake always sends, whatever this is set to.",
  autoNever: "Never",
  autoBoot: "When this Deck starts",
  autoResume: "When it wakes from sleep",
  autoBoth: "Both",
  autoResumeHint: "Handhelds wake from sleep often, so this can wake the PC many times a day.",
  homeOnly: "Only on this network",
  homeOnlyOff: "Off: automatic wakes are sent on any network.",
  homeOnlyOn: (gw: string) =>
    `Home network: router ${gw}. The router's hardware address is checked too when it's known.`,
  homeOnlyNoNetwork: "Not connected to a network right now. Connect to your home network, then turn this on.",
  homeOnlyFailed: "Couldn't read the current network. Try again in a moment.",

  moreSettings: "More settings",
  broadcast: "Send to address",
  broadcastHint: "Leave as is unless wakes don't arrive.",
  port: "Wake port (UDP)",
  portHint: "Usually 9. Some PCs listen on 7.",
  portInvalid: "Use a number from 1 to 65535.",
  statusHost: "Status check address",
  statusHostHint: "The PC's IP address or hostname, for example 192.0.2.20. Used only for Awake/Asleep.",
  statusPort: "Status check port (TCP)",
  statusPortHint: "Leave empty to skip the check.",
  secureon: "Wake password (SecureOn) — rarely needed",
  secureonHint: "Only if your network card asks for one. Six bytes, written like a MAC address.",

  fixFields: "Check the highlighted field.",

  discardTitle: "Discard changes?",
  discardBody: "Your changes to this device haven't been saved.",
  discard: "Discard",
  keepEditing: "Keep editing",

  cancel: "Cancel",
  save: "Save",
  saving: "Saving…",
  saveFailed: "Couldn't save. Try again, or restart Decky Loader.",
};

export const PICKER = {
  title: "Pick from network",
  intro: "Devices this Deck has talked to recently.",
  loading: "Looking for devices…",
  empty: "No PCs found. Turn the PC on, make sure it's on the same network, then Scan network.",
  asleepHint: "A PC that's asleep or off can't be found. Wake it once by hand, or type its MAC address instead.",
  macHowTo:
    "Finding the MAC: on Windows run getmac /v, or open Settings → Network & internet → your adapter → Hardware properties. On Linux run ip link and use the link/ether line.",
  failed: "Couldn't read the network list. Try Refresh or Scan network, or type the MAC address instead.",
  router: "(your router)",
  alreadyAdded: "Already added",
  refresh: "Refresh",
  cancel: "Cancel",

  scan: "Scan network",
  scanHint: "Takes about 10 seconds. Finds PCs that are on right now.",
  scanning: "Scanning…",
  cancelScan: "Cancel scan",
  scanFound: (found: number, named: number) => (named > 0 ? `Found ${found} (${named} named)` : `Found ${found}`),
  scanNone: "No PCs found",
  scanBusy: "A scan is already running. Wait for it to finish.",
  scanRetryIn: (seconds: number) => `Try again in ${seconds} s`,
  awayTitle: "Scan this network?",
  awayBody: "This doesn't look like your home network. Scan it anyway?",
  awayOk: "Scan",

  find: "Find by IP or name",
  findHint: "Type the PC's IP address or hostname, for example 192.0.2.20.",
  findButton: "Find",
  finding: "Finding…",
  findEmpty: "Type an IP address or a name first.",
};

export const BACKUP = {
  title: "Back up or restore",
  intro: "Your devices are kept when you update or reinstall Wake Dispatch.",
  introMore: "To copy them to another device, or keep a copy, export them as text and import it there.",
  exportTitle: "Export settings",
  exportIntro:
    "Copy this text and paste it into Import on another device. The list is also stored in Wake Dispatch's devices.json in Decky's settings folder.",
  exportLoading: "Preparing…",
  exportFailed: "Couldn't read your settings. Try again, or restart Decky Loader.",
  exportField: "Settings text",
  exportFieldHint: "Read-only. Use the copy button to copy it.",
  close: "Close",

  importTitle: "Import settings",
  importIntro: "Paste text you exported from Wake Dispatch.",
  importField: "Settings text",
  importReplace: "Replace my current devices",
  importReplaceOn: "Your current device list is replaced by the pasted one.",
  importReplaceOff:
    "Merge: devices in the pasted text are added, or update the matching device. Others are kept.",
  importEmpty: "Paste the exported text first.",
  importNotJson:
    "That doesn't look like exported settings. Paste the whole text, starting with { and ending with }.",
  importFailed: "Couldn't import. Try again, or restart Decky Loader.",
  importButton: "Import",
  importing: "Importing…",
  importConfirmTitle: "Replace your devices?",
  importConfirmBody: (n: number) =>
    `Your ${n === 1 ? "1 device" : `${n} devices`} will be replaced by the pasted list.`,
  importConfirmOk: "Replace",
  imported: "Settings imported",
  importedMerge: (n: number) => `Your list now has ${n === 1 ? "1 device" : `${n} devices`}.`,
  importedReplace: (n: number) => `Replaced your list with ${n === 1 ? "1 device" : `${n} devices`}.`,
  cancel: "Cancel",
};

export const UPDATE = {
  title: "Updates",
  available: (version: string) => `Update available: v${version}`,
  current: (installed: string) => `Up to date (v${installed})`,
  checking: "Checking for updates…",
  unavailable: "Update check unavailable",
  off: "Update checks are off",
  installed: (installed: string) => `Installed version v${installed}`,
  throttled: "Checked less than a minute ago",
  update: "Update",
  checkNow: "Check for updates",
  toggle: "Check daily",
  toggleHint:
    "Off by default. When on, asks GitHub for the latest release at most once a day, when you open this panel. Nothing is installed without your confirmation.",
  manual: "Install from URL: Decky settings → Developer → Install Plugin from URL, then paste:",
  installFailed: "Couldn't open Decky's installer. Install from the URL below instead.",
  autoOff: "Automatic checks are off",
  notChecked: "Not checked yet",
  unavailableWith: (error: string) => `Update check unavailable: ${error}`,
  manualTitle: "Update Wake Dispatch",
  manualField: "Download URL",
  manualFieldHint: "Read-only. Use the copy button to copy it.",
  close: "Close",
};
