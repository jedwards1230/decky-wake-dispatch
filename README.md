# Wake Dispatch

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin that sends
Wake-on-LAN packets to your PCs from the Steam Quick Access menu, so the PC you stream
from or play on is awake by the time you need it.

- **Wake from the Quick Access menu**: a **Wake** button for each device, plus **Wake
  all** once you have two or more.
- **Optional automatic wakes**: per device, wake it when your handheld (or other Steam
  device) starts up, after it wakes from sleep, or both. Automation is off by default.
- **Awake / Asleep status** next to each device, from a quick TCP port check you choose
  (or none at all).
- **Pick devices from the network** instead of typing MAC addresses.
- **Export and import** your device list as text, to back it up or copy it to another
  device.

## Install

Wake Dispatch is distributed through
[GitHub Releases](https://github.com/jedwards1230/decky-wake-dispatch/releases) rather
than the Decky plugin store. You need [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) 3.0
or newer installed first.

1. In Game Mode, open the Quick Access menu, go to Decky, and open Decky's settings
   (the gear icon).
2. Under **General**, turn on **Developer mode**.
3. Open the new **Developer** section and choose **Install Plugin from URL**.
4. Enter this URL, choose **Install**, and confirm:

   ```text
   https://github.com/jedwards1230/decky-wake-dispatch/releases/latest/download/wake-dispatch.zip
   ```

Wake Dispatch then appears in Decky's plugin list.

### Updating and rolling back

Decky does not tell you about updates for plugins installed from a URL, so Wake
Dispatch can check for you. The panel's **Updates** section shows the installed version
and where things stand ("Up to date", "Update available", or "Automatic checks are off"
until you check). Press **Check for updates** to ask GitHub for the latest release right
away. If you'd rather be told automatically, turn on **Check daily** (it is off until you
do): then, at most once a day when you open the panel, it asks GitHub. When a newer
version is known, an **Update available** row appears under your devices; press
**Update** to open Decky's own install confirmation, and nothing is installed until you
confirm it there. If Decky's installer can't be opened, the panel shows the download URL
to copy and paste into Decky settings → Developer → **Install Plugin from URL** instead.

You can also update by hand: repeat the install steps (Decky settings → Developer →
**Install Plugin from URL**) with the same `latest` URL; it always points at the
newest release.

To install a specific version instead (for example, to roll back), use that release's
URL, replacing `vX.Y.Z` with the version you want:

```text
https://github.com/jedwards1230/decky-wake-dispatch/releases/download/vX.Y.Z/wake-dispatch.zip
```

Your devices and settings are kept when you update, reinstall or change versions.

## Using it

Open the Quick Access menu and choose Wake Dispatch. Press **Wake** next to a device, or
**Wake all** (shown below the list when you have two or more devices) to wake every
device. A notification says the wake was sent and, if the device has a status check,
that it is checking whether the PC came up; a second notification follows if it did, or
if it still hasn't after about 45 seconds. For about ten minutes the device's row shows
how that wake went ("Wake sent 1 min ago", "Checking…", "Awake", or "Didn't wake up"),
then goes back to its usual summary. The **⋯** button next to **Wake** opens **Edit**
and **Delete…** (which asks before removing the device).

A sent wake only means the packet left your device. Whether the PC wakes depends on how
the PC is set up; see [Preparing a PC to be woken](#preparing-a-pc-to-be-woken).

### Adding a device

Choose **Add device**, then either pick the PC from the network or type its MAC address,
and give it a name (for example "Gaming PC"). Adding and editing use the same screen:

- **Pick from network**: lists devices your Steam device has talked to recently, with
  their names where your network provides them. Picking a device fills in its MAC
  address, its address for status checks and, if you haven't typed one, a name.
  Devices you've already added are marked **Already added**.
  If your PC isn't listed, choose **Scan network**: the plugin briefly checks every
  address on your home network so devices that haven't talked to your Steam device yet
  show up too, then shows how many it found. It usually takes about 10 seconds (at most
  15), you can cancel it, and it asks first if you're not on your home network. Nothing
  it finds is remembered.
  If you know the PC's IP address or name, type it under **Find by IP or name** and
  press **Find**: the plugin checks just that one address and fills in its MAC address.
  Only PCs that are on can be found this way. If yours is asleep or off, wake it once by
  hand, or type its MAC address.
- **Type the MAC address**: any common format works, for example `aa:bb:cc:dd:ee:01`,
  `aa-bb-cc-dd-ee-01` or `aabbccddee01`. On Windows run `getmac /v` (or open Settings →
  Network & internet → your adapter → Hardware properties); on Linux run `ip link` and
  use the `link/ether` value.

Under **Check if it's awake**, choose how the plugin should tell whether the PC is up:

| Choice | Port checked |
| --- | --- |
| Don't check | none; the device shows no status |
| Game streaming (Sunshine) | TCP 47989, the port of the Sunshine game-stream host (used with Moonlight); Steam Remote Play itself is not checked |
| SSH | TCP 22 |
| Remote Desktop | TCP 3389 |
| Another port… | any TCP port, set under More settings |

A status check needs the PC's address. Pick from network fills it in; otherwise set it
under More settings, or Save asks you to.

**More settings** (folded by default) has the status check address and port, the wake
port (UDP 9 by default; some PCs listen on 7), the address the wake is sent to (leave it
as is unless wakes don't arrive), and a Wake password (SecureOn) for the rare network
card that asks for one.

### Automatic wakes

In a device's settings, **Wake automatically** is **Never** by default. The other
choices are:

- **When this Deck starts** sends a wake once each time your handheld or PC running
  Steam boots. Restarting Decky or the plugin during the same boot does not send
  another (unless the first attempt found no network, in which case it tries again).
- **When it wakes from sleep** sends a wake each time it resumes from sleep. Very short
  sleeps (under about 20 seconds) are not detected.
- **Both**.

Automatic wakes wait for a network connection before sending (up to 60 seconds after
boot, 20 seconds after resume) and send a short burst of packets over about 20 seconds
in case the network is still settling.

**Only on this network** (shown once an automatic wake is chosen) limits automatic wakes
to the network you are on when you turn it on; its description shows the router address
it remembered. The plugin remembers your current router's address (the default gateway)
and, when it can see it, the router's hardware (MAC) address, and only sends automatic
wakes when you are connected through a router that matches. If the router's hardware
address can't be read at the time of a wake (for example just after waking from sleep),
only its address is checked, so a different network that happens to use the same router
address can still count as home then. When it is off, automatic wakes are sent on any
network. The first time you choose an automatic wake for a device, **Only on this
network** turns on by itself and records the router you are connected through right
then (if you are connected); turn it off if you want automatic wakes on any network.

Pressing **Wake** yourself always sends, whatever network you are on, as long as you are
connected to one.

The panel shows the result of the last automatic wake, for example "Last automatic wake:
on boot, 2 min ago — sent to Gaming PC", or why it was skipped. Until one has happened
it says what comes next, for example "Automatic wake is on. Next: when this Deck starts
or wakes from sleep."

Handhelds wake from sleep often, so a resume wake can wake the PC many times a day. Each
wake keeps the PC running, and using power, until it goes back to sleep on its own. To
soften that, once a wake from sleep has sent, the plugin ignores further wakes from sleep
for 10 minutes. A wake from sleep that was skipped (for example because you weren't
home), failed or found no network doesn't start that pause.

### Backup

Your devices are kept when you update or reinstall Wake Dispatch. **Back up or
restore** opens **Export settings** and **Import settings**. **Export settings** shows
your device list as text you can copy. **Import settings**
takes that text and either merges it into your list (adding new devices and updating
matching ones) or replaces your list. A list holds up to 64 devices, and an import can be up to
256 KB of text. The list itself is stored in
`~/homebrew/settings/wake-dispatch/devices.json`, which you can also back up from
Desktop Mode.

## Preparing a PC to be woken

Wake-on-LAN has to be enabled on the PC itself, usually in more than one place. A wired
Ethernet connection is the most reliable; waking a PC over Wi-Fi rarely works.

**Firmware (BIOS/UEFI).** Enable the Wake-on-LAN option. Depending on the board it may
be called "Wake on LAN", "Power on by PCI-E", "Resume by PCI-E device" or similar. Some
boards also need an "ErP" or deep-sleep power saving option turned off.

**Windows.**

1. Open Device Manager, expand **Network adapters**, and open your wired adapter's
   properties.
2. On the **Power Management** tab, tick **Allow this device to wake the computer** and
   **Only allow a magic packet to wake the computer**.
3. On the **Advanced** tab, set **Wake on Magic Packet** to Enabled.
4. If waking still fails, set **Energy-Efficient Ethernet** (or **Green Ethernet**) to
   Disabled on the same tab.
5. Waking a PC that is shut down often fails while **Fast Startup** is on (Control
   Panel → Power Options → Choose what the power buttons do). Waking from sleep or
   hibernate is more reliable. Turn Fast Startup off if you need wake from shutdown.

**Linux.** Enable magic-packet wake on the wired interface:

```bash
sudo ethtool -s <iface> wol g
```

That setting is lost on reboot. With NetworkManager, make it permanent for the
connection:

```bash
nmcli connection modify <conn> 802-3-ethernet.wake-on-lan magic
```

**macOS.** Turn on **Wake for network access** in System Settings (under Energy or
Battery, depending on the Mac and macOS version).

## Troubleshooting

- **The wake is sent but the PC doesn't wake.** Check the PC settings above first.
  Wake-on-LAN packets are broadcasts: they only reach PCs on the same network segment as
  your Steam device. They do not cross subnets or VLANs, and guest Wi-Fi networks or
  access points with client isolation usually drop them. Connect both to the same
  network, or try a directed broadcast for your network (for example `192.0.2.255`)
  as **Send to address** under More settings.
- **Try the other wake port.** Most PCs listen on UDP port 9; some only on 7 (**Wake
  port** under More settings).
- **The status says Unknown.** The status check address couldn't be looked up in time,
  or your Steam device has no route to it right now (for example it isn't on the PC's
  network). Check the name, or use the PC's IP address under More settings. (A
  device with no status check shows no status at all.)
- **The status says Asleep but the PC is on.** The status check shows Awake when the PC
  answers on that port at all, even to refuse the connection. Asleep means nothing
  answered within a second, which usually means a firewall on the PC silently drops
  connections to that port; allow it, or pick a port the PC answers on.
- **Logs.** The plugin writes its log to `~/homebrew/logs/wake-dispatch/` on your Steam
  device. Include the relevant lines when reporting a problem.
- **Desktop Mode.** The Wake Dispatch panel is only available in Game Mode, but
  automatic wakes run in the plugin's background service and work in Desktop Mode too.

## Privacy

Wake Dispatch makes no network connections except:

- the Wake-on-LAN packets you trigger, by pressing Wake or through the automatic wakes
  you turn on;
- TCP status checks to the addresses and ports you configure (and, if you enter a
  hostname rather than an IP address, the DNS lookup for it);
- reverse DNS lookups for the addresses in **Pick from network**, to show device names;
- only when you press **Scan network**: one empty UDP packet to each address on your
  local network (its /24 or smaller, home address ranges only, never over a VPN),
  mDNS name queries on the local network, and reverse DNS lookups for the devices
  found;
- only when you press **Find**: one empty UDP packet to the one address you typed,
  and only if it is on your local network, plus a DNS lookup if you typed a name
  (and a reverse DNS lookup if you typed an address);
- the update check: one HTTPS request to `api.github.com` for the latest release of this
  plugin, only when you press **Check for updates**, or at most once a day when you
  open the panel if you turned on the daily check (it is off by default). Like any web
  request it shows GitHub your IP address, with a `wake-dispatch/<version>` user agent.

When you press **Update** and confirm, Decky downloads the zip from GitHub and, as it
does for every install from a URL, sends an install-counter request to its plugin
store (`plugins.deckbrew.xyz`).

Scan and find traffic never leaves your local network, apart from the DNS lookups.
Nothing is sent anywhere else. Your settings stay on your device; devices found by a
scan or a find are not saved.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). To report a security issue, see
[SECURITY.md](SECURITY.md).

## License

[BSD-3-Clause](LICENSE). The project started from the Decky plugin template.
