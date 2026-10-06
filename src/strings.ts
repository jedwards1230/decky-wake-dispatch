// User-facing copy. Plain language, no jargon beyond "Wake-on-LAN".

export const PLUGIN_NAME = "Wake Dispatch";

export const DEFAULT_BROADCAST = "255.255.255.255";
export const DEFAULT_PORT = 9;

export const S = {
  wakeAll: "Wake all",
  wakeAllNoDevices: "Add a device below to get started.",
  addDevice: "Add device",
  wake: "Wake",
  waking: "Waking…",
  edit: "Edit",
  delete: "Delete",
  devicesTitle: "Devices",
  backupTitle: "Backup",
  exportSettings: "Export settings",
  importSettings: "Import settings",
  loading: "Loading devices…",
  loadFailed: "Couldn't load your devices. Close and reopen this menu to try again.",

  emptyTitle: "No devices yet",
  emptyBody:
    "Choose \"Add device\" and pick your PC from the network list, or type its MAC address.",
  emptyWolHint:
    "The PC needs Wake-on-LAN turned on in its BIOS/UEFI and in its network adapter settings, and usually a wired connection.",

  status: { awake: "Awake", asleep: "Asleep", unknown: "Unknown", checking: "Checking…" },

  deleteTitle: (name: string) => `Delete ${name}?`,
  deleteBody: "This removes it from Wake Dispatch. Nothing on the PC is changed.",

  backendError: "The plugin's background service didn't answer. Try again, or restart Decky Loader.",
};

export const EDITOR = {
  addTitle: "Add device",
  editTitle: "Edit device",
  name: "Name",
  nameRequired: "Give this device a name.",
  mac: "MAC address",
  macHint: "Any format works, for example aa:bb:cc:dd:ee:01, aa-bb-cc-dd-ee-01 or aabbccddee01.",
  macRequired: "Enter the PC's MAC address, or pick it from the network.",
  pickFromNetwork: "Pick from network",
  pickedHostHint: (ip: string) =>
    `Status checks will use ${ip}. Set a status port under Advanced to see Awake/Asleep.`,

  automationTitle: "Automatic wake",
  automationHint: "Off by default. Wakes are always sent when you press Wake.",
  onBoot: "When this Steam device starts up",
  onBootHint: "Sends a wake once each time this handheld or PC running Steam boots.",
  onResume: "When this Steam device wakes from sleep",
  onResumeHint: "Handhelds wake from sleep often, so this can send many wakes a day.",
  homeOnly: "Only on this network",
  homeOnlyOff: "Off: automatic wakes are sent on any network.",
  homeOnlyOn: (gw: string) => `Automatic wakes are only sent on the network whose router is ${gw}.`,
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
  refresh: "Refresh",
  cancel: "Cancel",
};

export const BACKUP = {
  exportTitle: "Export settings",
  exportIntro:
    "Your device list as text. Use the copy button in the field, or write it down, then keep it somewhere safe.",
  exportLoading: "Preparing…",
  exportFailed: "Couldn't read your settings. Try again, or restart Decky Loader.",
  exportField: "Settings text",
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
  importButton: "Import",
  importing: "Importing…",
  importConfirmTitle: "Replace your devices?",
  importConfirmBody: (n: number) =>
    `Your ${n === 1 ? "1 device" : `${n} devices`} will be replaced by the pasted list.`,
  importConfirmOk: "Replace",
  imported: (n: number) => `Imported settings: ${n === 1 ? "1 device" : `${n} devices`}`,
  cancel: "Cancel",
};
