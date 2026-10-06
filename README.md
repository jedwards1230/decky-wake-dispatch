# Wake Dispatch

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin that sends
Wake-on-LAN packets to your PCs from the Steam Quick Access menu, so the PC you stream
from or play on is awake by the time you need it.

- **Wake from the Quick Access menu**: a **Wake all** button plus a **Wake** button for
  each device.
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

Decky does not tell you about updates for plugins installed from a URL. To update,
repeat the install steps with the same `latest` URL; it always points at the newest
release.

To install a specific version instead (for example, to roll back), use that release's
URL, replacing `vX.Y.Z` with the version you want:

```text
https://github.com/jedwards1230/decky-wake-dispatch/releases/download/vX.Y.Z/wake-dispatch.zip
```

Your devices and settings are kept when you reinstall or change versions.

## Using it

Open the Quick Access menu and choose Wake Dispatch. Press **Wake** next to a device, or
**Wake all** to wake every device. A notification tells you whether the wake was sent,
and, if the device has a status check, whether it came up.

A sent wake only means the packet left your device. Whether the PC wakes depends on how
the PC is set up; see [Preparing a PC to be woken](#preparing-a-pc-to-be-woken).

### Adding a device

Choose **Add device**, then either pick the PC from the network or type its MAC address,
and give it a name (for example "Gaming PC"):

- **Pick from network**: lists devices your Steam device has talked to recently, with
  their names where your network provides them. Turn the PC on once so it shows up.
  Picking a device fills in its MAC address, its address for status checks and, if you
  haven't typed one, a name.
- **Type the MAC address**: any common format works, for example `aa:bb:cc:dd:ee:01`,
  `aa-bb-cc-dd-ee-01` or `aabbccddee01`.

Under **Check if it's awake**, choose how the plugin should tell whether the PC is up:

| Choice | Port checked |
| --- | --- |
| Don't check | none; the device shows "No status check" |
| Game streaming (Sunshine) | TCP 47989, the port of the Sunshine game-stream host (used with Moonlight); Steam Remote Play itself is not checked |
| SSH | TCP 22 |
| Remote Desktop | TCP 3389 |
| Other port | any TCP port, set under advanced settings |

**Show advanced settings** has the broadcast address, the wake port (UDP 9 by default;
some PCs listen on 7), the status check address and port, and a SecureOn password for
the rare network card that asks for one.

### Automatic wakes

In a device's settings, under **Automatic wake**:

- **When this Steam device starts up** sends a wake once each time your handheld or PC
  running Steam boots. Restarting Decky or the plugin during the same boot does not send
  another (unless the first attempt found no network, in which case it tries again).
- **When this Steam device wakes from sleep** sends a wake each time it resumes from
  sleep. Very short sleeps (under about 20 seconds) are not detected.

Automatic wakes wait for a network connection before sending (up to 60 seconds after
boot, 20 seconds after resume) and send a short burst of packets over about 20 seconds
in case the network is still settling.

**Only on my home network** limits automatic wakes to the network you are on when you
turn it on. The plugin remembers your current router's address (the default gateway) and
only sends automatic wakes when you are connected through a router with that address. It
does not identify your network any other way, so a different network that happens to use
the same router address also counts. When it is off, automatic wakes are sent on any
network. If you are connected when you first enable an automatic wake, it is turned on
for your current network automatically.

Pressing **Wake** yourself always sends, whatever network you are on, as long as you are
connected to one.

The panel shows the result of the last automatic wake, for example "Last automatic wake:
on boot, 2 min ago — sent to Gaming PC", or why it was skipped.

Handhelds wake from sleep often, so a resume wake can wake the PC many times a day. Each
wake keeps the PC running, and using power, until it goes back to sleep on its own.

### Backup

**Export settings** shows your device list as text you can copy. **Import settings**
takes that text and either merges it into your list (adding new devices and updating
matching ones) or replaces your list. The list itself is stored in
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
  network, or try a directed broadcast for your network (for example `192.168.1.255`)
  as the broadcast address under advanced settings.
- **Try the other wake port.** Most PCs listen on UDP port 9; some only on 7 (**Wake
  port** under advanced settings).
- **The status says Unknown.** The status check address couldn't be looked up. Check
  the name, or use the PC's IP address under advanced settings. (A device with no status
  check shows "No status check" instead.)
- **The status says Asleep but the PC is on.** The status check only shows whether the
  chosen service answers on that port. The service may not be running, or a firewall on
  the PC may be blocking the port.
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
- reverse DNS lookups for the addresses in **Pick from network**, to show device names.

Nothing is sent anywhere else. Your settings stay on your device.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). To report a security issue, see
[SECURITY.md](SECURITY.md).

## License

[BSD-3-Clause](LICENSE). The project started from the Decky plugin template.
