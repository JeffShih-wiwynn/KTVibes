# KTVibes

An independently maintained fork of [KTVibes by Andrew Lee](https://github.com/andyleenz/KTVibes). This fork keeps the KTVibes name and MIT license. For features and instructions shared with the original project, see the [upstream README](https://github.com/andyleenz/KTVibes#readme).

### Japanese furigana alignment

Furigana stays aligned with its kanji as lyrics highlight during playback.

![Japanese karaoke lyrics with furigana aligned above the sung kanji](docs/screenshots/fork/fork-japanese-furigana.png)

### Mobile lyrics

Open a dedicated lyrics viewer from the phone remote. Search LRCLIB with parsed title terms or your own query, preview results, and choose synced or plain lyrics. Mark a song as having no suitable lyrics when lookup finds no match.

<img src="docs/screenshots/fork/fork-remote-queue-overview.gif" width="800" alt="Remote showing song search, Recent, playback controls, and Queue">

### Remote queue management

See each queued song's lyrics status, change the song order, insert a song to play next, and remove songs from the queue.

![Queue interactions: adding songs, reordering, and queue actions](docs/screenshots/fork/fork-queue-interactions.gif)

### Wide-screen remote

On wide screens, the remote uses a two-column layout for song lists and playback controls.

<img src="docs/screenshots/fork/fork-wide-screen-remote.gif" width="800" alt="KTVibes remote in a wide-screen two-column layout">

## Install this fork

### Windows

Download `KTVibes-Setup-x64.exe` from the [latest KTVibes release](https://github.com/JeffShih-wiwynn/KTVibes/releases/latest) and run it. The unsigned installer may trigger a Windows SmartScreen warning.

Choose an install folder during setup. The application, its private runtimes, songs, lyrics, queue and models are stored there. Reinstalling preserves `cache/`; uninstall asks whether to remove it.

### macOS

Download `KTVibes-<version>-AppleSilicon.dmg` from the [latest KTVibes release](https://github.com/JeffShih-wiwynn/KTVibes/releases/latest), open it, and drag KTVibes to Applications. This build supports Apple silicon Macs only and uses ad-hoc signing; it has no Developer ID signature or notarization, so macOS may still require you to approve it in Privacy & Security. The app downloads its private Python, Node.js, FFmpeg and Python packages when it starts; this first setup can take several minutes.

The app is installed in Applications; its private runtime, songs, lyrics, queue and models stay in `~/Library/Application Support/KTVibes`. Replacing the app during an update preserves that folder. Removing KTVibes from Applications leaves it in place; remove it separately if you want to delete the cache.

### Desktop network settings

On macOS and Windows, choose **Network Settings…** from the menu bar or system tray. The window shows the current Remote address and a copy icon. Expand **Advanced settings** to select an active IPv4 network adapter or change the port. Automatic network selection and port `8765` are the defaults; Reset restores them.

Apply restarts the server. On macOS, it opens the player at the new address; on Windows, the settings window closes after the server restarts and the settings are saved. Playback is interrupted and the saved queue is restored; phones may need to scan the new QR code. If the preferred port is unavailable, KTVibes tries the next four ports, followed by five ports starting 10000 above the preferred port, within the valid port range. If all candidates fail, the desktop menu shows Port conflict and links to Network Settings. A failed restart restores the previous configuration. When the automatically detected IP changes, the TV address and QR refresh within about five seconds.

Settings are stored in `~/Library/Application Support/KTVibes/network.json` on macOS and `%LOCALAPPDATA%\KTVibes\network.json` on Windows. Saved desktop settings take precedence over `KTVIBES_PORT` and `KTVIBES_ADVERTISE_IP`; source launches continue to use environment variables. `KTVIBES_REMOTE_URL` remains available for source/self-hosted deployments with a custom external URL. Selecting an IP changes the advertised Remote address; the server continues listening on all IPv4 interfaces.

### Linux

The Linux TUI requires a systemd user session, Git, FFmpeg, Node.js 22 or later, and the `ip` command (iproute2). It installs uv if needed, installs KTVibes under `~/.local/share/ktvibes`, and adds a `ktvibes` command under `~/.local/bin`. Application data, including the song library and queue, is kept under the XDG data directory; model downloads use the XDG cache directory. XDG directory environment variables are respected. The installer only updates its own installation and leaves `~/KTVibes` source checkouts alone:

```bash
curl -LsSf https://raw.githubusercontent.com/JeffShih-wiwynn/KTVibes/dev/install.sh | bash
```

The installer defaults to the latest stable GitHub Release and saves its channel in `${XDG_CONFIG_HOME:-~/.config}/ktvibes/installation.json`. To install the development branch instead, pass the channel option:

```bash
curl -LsSf https://raw.githubusercontent.com/JeffShih-wiwynn/KTVibes/dev/install.sh | bash -s -- --channel dev
```

Run `ktvibes` to open the terminal menu. The menu starts `ktvibes.service` if needed, connects to an already running service, and opens Player once the server is ready. The Remote address appears above the version/update item. Open Player, Show Logs, Network Settings, Launch at Login, Detach and Quit are available from the menu.

- **Detach / Ctrl+C:** close the terminal menu and leave the server running.
- **Quit:** stop the server and close the menu. The Launch at Login setting remains unchanged.
- **Launch at Login:** enable or disable the systemd user service for future logins. Login startup runs in the background without a terminal or browser.
- **Version:** check for updates in the installed channel and confirm installation. Updating stops the service and hands control to an independent installer. Success restarts the service and TUI; failure leaves the service stopped and displays the error in the terminal.
- **Show Logs:** view the service journal; left/right arrows scroll long messages horizontally. `q`, Esc or Ctrl+C returns to the menu.
- **Network Settings:** select an IPv4 adapter, edit the port, or enable an external HTTPS address with a PIN. Apply restarts the service without opening another browser; failed settings are restored. Reset edits the form; Apply saves it.

Settings and private runtime credentials are stored under `${XDG_CONFIG_HOME:-~/.config}/ktvibes/`. The unit is installed under the XDG config directory's `systemd/user/` folder and is initially disabled for login startup. No root privileges or lingering are configured. You can also use `systemctl --user start|stop|status ktvibes` and `journalctl --user -u ktvibes` directly. SSH/headless sessions can use these commands; automatic browser opening requires a desktop browser.

If you prefer to install from source (including on non-systemd systems):

```bash
git clone --branch dev https://github.com/JeffShih-wiwynn/KTVibes.git
cd KTVibes
uv sync
uv run ktvibes
```

For Python and Remote browser test commands, see [Testing](docs/testing.md).
For module responsibilities and dependency boundaries, see [Code structure](docs/architecture.md).

## Updates

- When a newer stable release is available, the Remote shows an update icon. Open it to see the version and the GitHub Release page; downloading and installing remain manual.
- **Windows:** Download and run the newer installer. It updates the application in the selected folder and keeps `cache/`.
- **macOS:** Replace KTVibes in Applications with the newer app. Your songs, lyrics, queue and models remain in Application Support.
- **Linux:** Stop the service with Quit or `systemctl --user stop ktvibes`, then rerun the install command to update the managed installation. Your songs, lyrics and queue remain in the XDG data directory.

## Upstream and license

This project is based on [andyleenz/KTVibes](https://github.com/andyleenz/KTVibes). The upstream MIT license and copyright notice are retained in [`LICENSE`](LICENSE). Changes in this fork are maintained independently.

### External address and access password

In desktop **Network Settings → Advanced settings**, enable **External address**,
enter the public HTTPS address supplied by your tunnel (for example,
`https://ktv.example.com`), and set a PIN of at least 6 digits. **Apply**
restarts the server; failure restores the previous settings. Leave PIN blank
when editing settings to keep the existing PIN. Disabling External address
or Reset clears the external address/password when applied.

Open Player and enter the PIN. Its QR code lets guests join Remote without
entering that PIN. Anyone with the current QR can control Remote, but cannot
use that credential to take over Player. QR codes and browser sessions expire on
server restart; scan the new QR to reconnect. Inner-network mode keeps direct,
password-free access to `/remote`.

The External address setting advertises a URL; it does not create a Cloudflare
Tunnel or configure Cloudflare Access. Tunnel and HTTPS setup are managed
separately. An additional Cloudflare Access login would still apply before the
request reaches KTVibes. Application login attempts are rate limited; Cloudflare
rate limiting can provide another layer.

External mode keeps the configured port fixed: a conflict is reported instead of
switching ports and breaking the tunnel route. LAN mode retains automatic port
recovery. Player shows a short URL with copy/share actions that include the same
per-run key as its QR. Manually typing the short URL requires the PIN. Legacy
passwords continue working until the next external-settings Apply, which requires
a new numeric PIN.
