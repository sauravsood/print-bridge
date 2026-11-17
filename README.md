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

### 1. Give the printer a fixed IP

In your router's admin page, find the TSC printer in the connected devices list and
reserve its IP address (it's often called "DHCP reservation" or "static lease").
This stops the address changing after a power cut.

### 2. Create the Cloudflare Tunnel

1. Go to [one.dash.cloudflare.com](https://one.dash.cloudflare.com) and open **Networks → Connectors → Cloudflare Tunnels → Create a tunnel**.
   (Or type `tunnel` in the dashboard search, or use **Networking → Tunnels** on dash.cloudflare.com.
   If it asks you to set up Zero Trust first, pick any team name and the **Free** plan.)
2. Pick **Cloudflared**, and name it `print-bridge`.
3. On the "Install connector" screen, copy the long token from any of the commands
   shown (the text after `--token` or `service install`). Don't run their command.
4. Click Next. Under **Public hostname**, set subdomain `print`, domain
   `sauravsood.com`, service type **HTTP**, URL `localhost:8080`. Then save.

### 3. Put a login in front of it (do this before using it)

1. In the same dashboard: **Access → Applications → Add an application → Self-hosted**.
2. Name it `Print`, set the domain to `print.sauravsood.com`.
3. Add a policy: Action **Allow**, Include **Emails**, then add your email
   (and anyone else who prints labels).
4. Save. Visitors now get a one-time code by email before they see the page.
   It works in any browser, with nothing to install.

### 4. Install on the Pi

Log in to the Pi (SSH, or a keyboard and monitor) and run this, pasting your token at the end:

```sh
curl -fsSL https://raw.githubusercontent.com/sauravsood/print-bridge/main/install.sh | sudo bash -s -- PASTE_TOKEN_HERE
```

### 5. First print

1. Open **https://print.sauravsood.com** and log in.
2. Under **Printer settings**, tap **Find** (or type the printer's IP), check the
   label size, then tap **Save**.
3. Tap **Calibrate** once so the printer learns the label gap, then **Test print**.
4. On iPhone, tap Share → **Add to Home Screen** for a one-tap app icon.

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
