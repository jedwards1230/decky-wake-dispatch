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
  wakeAllNoDevices: "Add a device below to get started.",
  addDevice: "Add device",
  wake: "Wake",
  waking: "Sending…",
  wakeLabel: (name: string) => `Wake ${name}`,
  editLabel: (name: string) => `Edit ${name}`,
  deleteLabel: (name: string) => `Delete ${name}`,
  wakeAllLabel: "Wake all devices",
  statusLabel: (name: string, state: string) => `${name}: ${state}`,
  edit: "Edit",
  delete: "Delete",
  devicesTitle: "Devices",
  backupTitle: "Backup",
  exportSettings: "Export settings",
  importSettings: "Import settings",
  loading: "Loading devices…",
  loadFailed: "Couldn't load your devices. Choose Try again, or restart Decky Loader.",
  tryAgain: "Try again",

  emptyTitle: "No devices yet",
  emptyBody:
    "Choose \"Add device\" and pick your PC from the network list, or type its MAC address.",
  emptyWolHint:
    "The PC needs Wake-on-LAN turned on in its BIOS/UEFI and in its network adapter settings, and usually a wired connection.",

  status: {
    awake: "Awake",
    asleep: "Asleep",
    unknown: "Unknown",
    checking: "Checking…",
    none: "No status check",
  },

  deleteTitle: (name: string) => `Delete ${name}?`,
  deleteBody: "This removes it from Wake Dispatch. Nothing on the PC is changed.",
  deleteFailed: "Couldn't delete the device",

  noAutomaticYet: "No automatic wakes yet.",

  backendError: "The plugin's background service didn't answer. Try again, or restart Decky Loader.",
};

export const TOAST = {
  woke: (name: string) => `Woke ${name}`,
  sentTo: (n: number) => `Sent wake to ${n} devices`,
  sentSome: (sent: number, total: number) => `Sent wake to ${sent} of ${total} devices`,
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
  boot: "Wakes on boot",
  resume: "Wakes on resume",
  both: "Wakes on boot and resume",
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
};

export const EDITOR = {
  addTitle: "Add device",
  editTitle: "Edit device",
  name: "Name",
  nameRequired: "Give this device a name.",
  mac: "MAC address",
  macHint: "Any format works, for example aa:bb:cc:dd:ee:01, aa-bb-cc-dd-ee-01 or aabbccddee01.",
  macRequired: "Enter the PC's MAC address, or pick it from the network.",
  macCheckFailed: "Couldn't check the MAC address right now. Try Save again.",
  pickFromNetwork: "Pick from network",
  orTypeMac: "Or type the MAC address below.",
  foundAtChooseCheck: (ip: string) => `Found at ${ip}. Choose how to check if it's awake below.`,
  foundAt: (ip: string) => `Found at ${ip}. Status checks will use this address.`,
  pcAt: (ip: string) => `PC at ${ip}`,

  checkLabel: "Check if it's awake",
  checkNone: "Don't check",
  checkSunshine: "Game streaming (Sunshine, 47989)",
  checkSsh: "SSH (22)",
  checkRdp: "Remote Desktop (3389)",
  checkOther: "Other port (set in Advanced)",
  checkHint: "Shows Awake or Asleep next to the device.",
  checkNeedsHost: "Needs the PC's address: use Pick from network, or set it under Advanced.",

  automationTitle: "Automatic wake",
  automationHint: "Off by default. Wakes are always sent when you press Wake.",
  onBoot: "When this Steam device starts up",
  onBootHint: "Sends a wake once each time this handheld or PC running Steam boots.",
  onResume: "When this Steam device wakes from sleep",
  onResumeHint: "Handhelds wake from sleep often, so this can send many wakes a day.",
  homeOnly: "Only on my home network",
  homeOnlyOff: "Off: automatic wakes are sent on any network.",
  homeOnlyOn: (gw: string) =>
    `Only when connected through router ${gw} (your current network). Other networks with the same router address also count.`,
  homeOnlyAutoOn: "Turned on for your current network. Turn off to wake on any network.",
  homeOnlyNeedsTrigger: "Turn on an automatic wake first.",
  homeOnlyNoNetwork: "Not connected to a network right now. Connect to your home network, then turn this on.",
  homeOnlyFailed: "Couldn't read the current network. Try again in a moment.",

  showAdvanced: "Show advanced settings",
  hideAdvanced: "Hide advanced settings",
  broadcast: "Broadcast address",
  broadcastHint:
    "Leave as 255.255.255.255 unless the wake doesn't arrive. A directed broadcast for your network, such as 192.168.1.255, can help.",
  port: "Wake port (UDP)",
  portHint: "Usually 9. Some PCs listen on 7.",
  portInvalid: "Use a number from 1 to 65535.",
  statusHost: "Status check address",
  statusHostHint: "IP address or hostname of the PC, for example 192.168.1.20. Used only to show Awake/Asleep.",
  statusPort: "Status check port (TCP)",
  statusPortHint: "47989 for Sunshine, 22 for SSH, 3389 for Remote Desktop. Leave empty to skip the check.",
  secureon: "SecureOn password",
  secureonHint: "Only if your network card asks for one. Six bytes, written like a MAC address.",

  fixName: "Give this device a name (at the top).",
  fixMac: "Check the MAC address above.",
  fixFields: "Check the highlighted fields above.",

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
  intro: "Devices this Steam device has talked to recently. Turn the PC on once so it shows up here.",
  loading: "Looking for devices…",
  empty:
    "No devices found. Make sure the PC is on and connected, then refresh, or type the MAC address instead.",
  failed: "Couldn't read the network list. Try refresh, or type the MAC address instead.",
  router: "(your router)",
  refresh: "Refresh",
  cancel: "Cancel",
};

export const BACKUP = {
  exportTitle: "Export settings",
  exportIntro:
    "Your devices are stored in Wake Dispatch's devices.json in Decky's settings folder. Back that file up in Desktop Mode, or copy this text and paste it into Import on another device.",
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
