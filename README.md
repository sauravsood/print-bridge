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

### Part A: Cloudflare, create the tunnel

1. On [dash.cloudflare.com](https://dash.cloudflare.com), open **Networking → Tunnels** in the left
   menu, then **Create a tunnel**. (If it asks you to set up Zero Trust first, pick any team name and the **Free** plan.)
2. Name it `print-bridge` and continue.
3. Under **Operating System**, click **Debian** (Raspberry Pi OS is Debian). Leave 64-bit.
4. Under **Install as service**, click the copy icon. That copies
   `sudo cloudflared service install eyJhIjoi...`. Paste it into a note and keep **only the part
   starting with `eyJ`**. That's your tunnel token. Keep it private, and **don't run Cloudflare's commands**.
5. **Leave this tab open.** **Continue** stays greyed out until the Pi connects in Part B.

### Part B: Raspberry Pi, install

1. Open a terminal on the Pi (see [Getting into the Pi](#getting-into-the-pi) below).
2. Paste this one line, replacing `eyJ...` with your token from A4:

   ```sh
   curl -fsSL https://raw.githubusercontent.com/sauravsood/print-bridge/main/install.sh | sudo bash -s -- eyJ...
   ```

3. Wait until it prints **Done. The print bridge is running.**

#### Getting into the Pi

You need a terminal on the Pi, using the username and password chosen when it was first set up
(often `pi`; very old images used password `raspberry`). Pick whichever route works:

- **Laptop:** open PowerShell (Windows) or Terminal (Mac) and run `ssh pi@raspberrypi.local`.
  If the host isn't found, use the Pi's IP: `ssh pi@192.168.x.x`.
- **iPhone:** install a free SSH app such as **Termius**, then add a host with the Pi's IP
  (or `raspberrypi.local`), the username and the password.
- **Keyboard and monitor:** plug them into the Pi and log in directly.

**Finding the Pi's IP:** open your router's admin page (usually `192.168.1.1` or `192.168.0.1`)
and look in the connected or DHCP clients list for `raspberrypi`.

**"Connection refused"** means SSH is switched off. Log in once with a keyboard and monitor, run
`sudo raspi-config`, go to **Interface Options → SSH → Enable**, and then SSH will work.

### Part C: Cloudflare, publish and protect

**C1. Point print.sauravsood.com at the tunnel**

1. Back in the tab from Part A, **Connection Status** should now say **Connected**. Click **Continue**.
   (If you closed the tab, go to **Networking → Tunnels**, click `print-bridge`, and add a
   public hostname / published application route there.)
2. Fill in:

   | Field | Value |
   | --- | --- |
   | Subdomain | `print` |
   | Domain | `sauravsood.com` |
   | Path | *(leave empty)* |
   | Service type | `HTTP` |
   | URL | `localhost:8080` |

3. Save.

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
