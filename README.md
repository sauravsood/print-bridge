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

There are three parts, and each one happens in a different place:

| Part | Where | What |
| --- | --- | --- |
| **A** | Cloudflare dashboard, in a browser | Create the tunnel, point `print.sauravsood.com` at it, add an email login |
| **B** | On the Raspberry Pi (terminal) | Run one install command |
| **C** | On your phone or laptop (browser) | Find the printer and do a test print |

Optional but recommended first: in your **router's** admin page, reserve a fixed IP for the
TSC printer (called "DHCP reservation" or "static lease") so it never changes after a power cut.

### Part A: Cloudflare (browser)

**A1. Create the tunnel**

1. Go to [one.dash.cloudflare.com](https://one.dash.cloudflare.com). If it asks you to set up
   Zero Trust first, pick any team name and the **Free** plan.
2. Open **Networks → Connectors → Cloudflare Tunnels → Create a tunnel**. (If you can't find it,
   type `tunnel` in the dashboard search, or use **Networking → Tunnels** on dash.cloudflare.com.)
3. Choose **Cloudflared**, name it `print-bridge`, and save.

**A2. Copy the token**

1. Under **Operating System**, click **Debian** (Raspberry Pi OS is Debian). Leave 64-bit.
2. Scroll to **Install and Run**. The last command looks like
   `sudo cloudflared service install eyJhIjoi...` (very long).
3. Copy **only the part starting with `eyJ`** into a note. That's your tunnel token, which
   you'll need in Part B. Keep it private, and **don't run Cloudflare's commands** anywhere.
4. Scroll to the bottom and click **Next**.

**A3. Point print.sauravsood.com at the tunnel**

The next screen may be called *Route tunnel*, *Published application routes* or *Public hostname*. Fill in:

| Field | Value |
| --- | --- |
| Subdomain | `print` |
| Domain | `sauravsood.com` |
| Path | *(leave empty)* |
| Service type | `HTTP` |
| URL | `localhost:8080` |

Then click **Save** or **Complete setup**.

**A4. Add the email login**

1. In the left menu: **Access** (or **Access controls**) → **Applications** → **Add an application** → **Self-hosted**.
2. Name it `Print`. Set Subdomain `print` and Domain `sauravsood.com`.
3. Add a policy named `Me`: Action **Allow**, Include **Emails**, then your email address
   (add anyone else who prints labels).
4. Save. Visitors now get a one-time code by email before they see the page.

### Part B: Raspberry Pi (terminal)

**B1. Open a terminal on the Pi.** Either plug in a keyboard and monitor, or from another
computer on the same network run `ssh pi@<Pi's IP address>`. Windows has `ssh` built into PowerShell.

**B2. Run the installer.** Paste this one line, replacing `eyJ...` with your token from A2:

```sh
curl -fsSL https://raw.githubusercontent.com/sauravsood/print-bridge/main/install.sh | sudo bash -s -- eyJ...
```

**B3.** Wait until it prints **Done. The print bridge is running.** In the Cloudflare
dashboard, the tunnel should now show **Healthy**.

### Part C: first print (phone or laptop browser)

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
