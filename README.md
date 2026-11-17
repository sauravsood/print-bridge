# print-bridge

Print shipping label PDFs to a **TSC TA220** (or any TSPL label printer) from any
browser: an iPhone, or a locked-down laptop where nothing can be installed.

```
iPhone / laptop ──https──▶ print.sauravsood.com ──Cloudflare Tunnel──▶ Raspberry Pi ──TCP 9100──▶ TSC TA220
                           (Cloudflare Access login)                    (this app)
```

A web page can't talk to a printer on your home network by itself, so this app
runs on a Raspberry Pi next to the printer. It:

- takes a PDF upload (A4 courier sheets are cropped to the label and rotated automatically),
- turns each page into a 203 dpi black-and-white bitmap at the label size,
- shows a preview so you can skip pages and pick copies,
- sends the job to the printer in its own language (TSPL) on port 9100.

It needs only `python3` and `poppler-utils`. There's nothing to `pip install`.

## Setup (about 20 minutes, once)

Setup moves between the Cloudflare dashboard and the Pi. Follow the parts in order:

| Part | Where | What |
| --- | --- | --- |
| **A** | Cloudflare dashboard (browser) | Create the tunnel and copy its token |
| **B** | Raspberry Pi (terminal) | Run one install command with that token |
| **C** | Cloudflare dashboard (browser) | Point `print.sauravsood.com` at the tunnel and add an email login |
| **D** | Phone or laptop (browser) | Find the printer and do a test print |

Optional but recommended first: in your **router's** admin page, reserve a fixed IP for the
TSC printer (called "DHCP reservation" or "static lease") so it never changes after a power cut.

### Before you start: a working Pi

Skip this if your Pi already boots to a login prompt and you can log in.

If the Pi is new, or it stops at boot with **"Kernel panic … Unable to mount root fs"** (a corrupt
microSD card), put a fresh system on its microSD card:

1. On any computer that allows installs and has a card reader, install
   [Raspberry Pi Imager](https://www.raspberrypi.com/software/). (On a Pi 4 or newer you can skip
   the other computer: hold **Shift** while powering on to reinstall over the internet, with a
   keyboard, monitor and Ethernet attached.)
2. Choose your Pi model, then **Raspberry Pi OS Lite (64-bit)** (or 32-bit on a Pi 2), then the microSD card.
3. When asked to apply OS customisation, choose **Edit settings**:
   - Hostname: `printbridge`
   - Username and password: pick your own and note them down
   - **Services tab:** tick **Enable SSH** (password authentication)
4. Write the card, put it in the Pi, connect Ethernet to the **same router as the printer**, and power on.
   After a minute or two it's reachable as `ssh <username>@printbridge.local` (or by IP, see below).

**No other computer?** If the old Pi still boots (even on a very old system), it can write the new card
itself. Put a new microSD (8 GB or more) in a USB card reader, plug it into the Pi, log in, and run:

```sh
curl -fsSL https://raw.githubusercontent.com/sauravsood/print-bridge/main/tools/flash-new-card.sh | sudo bash
```

(If curl complains about a certificate, run it again with `-fsSLk` in place of `-fsSL`. The image itself
is still checked against its SHA-256.) It asks you to confirm the card, sets your username, password and SSH,
and never touches the card the Pi is running from. Then swap cards and power on.

You can also buy a microSD card with Raspberry Pi OS preinstalled. You'll then need a keyboard
and monitor once to set a password and turn on SSH (`sudo raspi-config` → Interface Options → SSH).

### Part A: Cloudflare, create the tunnel

1. On [dash.cloudflare.com](https://dash.cloudflare.com), open **Networking → Tunnels** in the left
   menu, then **Create a tunnel**. (If it asks you to set up Zero Trust first, pick any team name and the **Free** plan.)
2. Name it `print-bridge` and continue.
3. Under **Operating System**, click **Debian** (Raspberry Pi OS is Debian). Leave 64-bit.
4. Under **Install as service**, click the **copy icon**. Don't select the text with the mouse: the screen masks most of the token with `****`, and a masked token won't work. That copies
   `sudo cloudflared service install eyJhIjoi...`. Paste it into a note and keep **only the part
   starting with `eyJ`**. That's your tunnel token. Keep it private, and **don't run Cloudflare's commands**.
5. **Leave this tab open.** **Continue** stays greyed out until the Pi connects in Part B.

### Part B: Raspberry Pi, install

1. Open a terminal on the Pi (see [Getting into the Pi](#getting-into-the-pi) below).
2. Paste this one line, replacing `eyJ...` with your token from A4.
   **Don't type it by hand.** Do this step over SSH so you can paste. On the Pi's own keyboard, run
   `hostname -I` to see its IP. Then, on a laptop, run `ssh <username>@<that IP>` in PowerShell or
   Terminal (or use an SSH app like Termius on your phone), and right-click or paste the command there:

   ```sh
   curl -fsSL https://raw.githubusercontent.com/sauravsood/print-bridge/main/install.sh | sudo bash -s -- eyJ...
   ```

3. Wait until it prints **Done. The print bridge is running.**

#### Getting into the Pi

You need a terminal on the Pi, using the username and password chosen when it was first set up
(often `pi`; very old images used password `raspberry`). Pick whichever route works:

- **Laptop:** open PowerShell (Windows) or Terminal (Mac) and run `ssh <username>@printbridge.local`
  (or `ssh pi@raspberrypi.local` on an older setup).
  If the host isn't found, use the Pi's IP: `ssh pi@192.168.x.x`.
- **iPhone:** install a free SSH app such as **Termius**, then add a host with the Pi's IP
  (or `raspberrypi.local`), the username and the password.
- **Keyboard and monitor:** plug them into the Pi and log in directly.

**Finding the Pi's IP** (needed if `raspberrypi.local` says "Could not resolve hostname"):

- **Router:** open the admin page (usually `https://192.168.1.1` or `192.168.0.1`) and find the
  connected-devices / DHCP clients table. On Airtel fibre routers it's **Device Information → LAN Status**
  (or **Home Networking**). Look for `raspberrypi`.
- **No name shown?** Look for a MAC address starting with a Raspberry Pi prefix:
  `B8:27:EB`, `DC:A6:32`, `E4:5F:01`, `D8:3A:DD`, `2C:CF:67`, `28:CD:C1`.
- **From a Windows laptop:** run `arp -a` in PowerShell and look for those prefixes written with
  dashes (e.g. `dc-a6-32-…`). The IP on that line is the Pi.

**"Connection refused"** means SSH is switched off. Log in once with a keyboard and monitor, run
`sudo raspi-config`, go to **Interface Options → SSH → Enable**, and then SSH will work.

### Part C: Cloudflare, publish and protect

**C1. Point print.sauravsood.com at the tunnel**

When Part B finishes, the tunnel is connected but has no web address yet. In the tunnel list it
shows **Healthy** with **No routes**. You add the address here.

1. Go to **Networking → Tunnels** on dash.cloudflare.com. Your `print-bridge` tunnel should show
   **Healthy** and **No routes**. (If you still have the Part A tab open showing **Connected**,
   you can click **Continue** there instead and skip to step 4.)
2. Click the name **print-bridge**. (Or use the **⋯** menu at the end of its row → *Configure* / *Edit*.)
3. Open the **Routes** tab (sometimes called *Published application routes* or *Public hostnames*)
   and click **Add route**. If it asks what kind, choose **Published application**.
4. Fill in:

   | Field | Value |
   | --- | --- |
   | Subdomain | `print` |
   | Domain | `sauravsood.com` (pick it from the list) |
   | Path | *(leave empty)* |
   | Service type | `HTTP` |
   | URL | `localhost:8080` |

   If the form has a single **Service URL** box instead of type + URL, enter `http://localhost:8080`.
5. Save. Back in the tunnel list, **Routes** should now show `print.sauravsood.com`.
6. **Do C2 straight away, before opening the page**, so nobody else can reach your printer.

**C2. Add the email login**

1. Go to **Zero Trust** in the left menu, then **Access** (or **Access controls**) → **Applications** →
   **Add an application** → **Self-hosted**.
2. Name it `Print`. Set Subdomain `print` and Domain `sauravsood.com`.
3. Add a policy named `Me`: Action **Allow**, Include **Emails**, then your email address
   (add anyone else who prints labels).
4. Save. Visitors now get a one-time code by email before they see the page.

### Part D: first print (phone or laptop browser)

1. Open **https://print.sauravsood.com**, enter your email, then enter the code Cloudflare emails you.
2. Open **Printer settings**. Tap **Find** (or type the printer's IP), check the label size, and tap **Save**.
3. Tap **Calibrate** once so the printer learns the label gap, then tap **Test print**.
4. On iPhone, tap Share → **Add to Home Screen** for a one-tap icon.

## Everyday use

Download the label PDF from Shiprocket or your courier portal, open
print.sauravsood.com, choose the file, check the preview, then tap **Print**.

## Settings

| Setting | What it does |
| --- | --- |
| Label size | 4×6 in by default. The upload is scaled to fit. |
| Label stock | Die-cut labels with gaps (most common), black-mark, or continuous roll. |
| Darkness / speed | Raise darkness if the print is faint, and lower speed if barcodes smudge. |
| Black threshold | How dark a grey pixel must be to print. Raise it if thin text drops out. |
| Crop white space | Finds the label on a larger page (like A4) and enlarges just that part. |
| Rotate | Turns sideways labels so they fill the portrait label. |

## Updating

Run the same install command again (without the token) to pull the latest version.

## Troubleshooting

- **Bridge offline** on the page: on the Pi, run `sudo systemctl status print-bridge` and `sudo journalctl -u print-bridge -n 50`.
- **"Can't reach printer"**: check the printer's IP under Printer settings, and that the printer is on the same network as the Pi.
- **Labels print across the gap or skip a label**: tap **Calibrate**.
- **The page won't load at all**: run `sudo systemctl status cloudflared` on the Pi, and check that the tunnel shows *Healthy* in the Cloudflare dashboard.

## Development

```sh
PRINT_BRIDGE_DATA=./data LISTEN=127.0.0.1:8080 python3 -m print_bridge.server
python3 -m unittest discover tests
python3 tests/fake_printer.py 9199 /tmp/jobs   # pretend printer on port 9199 for local testing
```
