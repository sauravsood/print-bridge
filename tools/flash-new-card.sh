#!/usr/bin/env bash
# Write a fresh Raspberry Pi OS Lite onto a NEW microSD card in a USB card reader,
# using the Pi you're logged in to (even a very old one). No other computer needed.
#
#   curl -fsSL https://raw.githubusercontent.com/sauravsood/print-bridge/main/tools/flash-new-card.sh | sudo bash
#
# It never touches the card the Pi is running from (mmcblk0), asks before erasing,
# checks the download's SHA-256, and pre-sets your username, password and SSH.
set -eu

IMG_LATEST="${IMG_LATEST:-https://downloads.raspberrypi.com/raspios_oldstable_lite_armhf_latest}"
MNT=/tmp/newcard-boot
TTY=/dev/tty

say()  { printf '\n==> %s\n' "$*"; }
die()  { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
ask()  { local a; printf '%s' "$1" > "$TTY"; read -r a < "$TTY"; printf '%s' "$a"; }
asks() { local a; printf '%s' "$1" > "$TTY"; stty -echo < "$TTY"; read -r a < "$TTY"; stty echo < "$TTY"; printf '\n' > "$TTY"; printf '%s' "$a"; }

[ "$(id -u)" -eq 0 ] || die "Run it with sudo."
for c in curl xz dd sha256sum mount blockdev; do
  command -v "$c" >/dev/null 2>&1 || die "Missing '$c' on this Pi."
done

# ---- pick the target card ---------------------------------------------------
if [ -n "${TARGET_DEV:-}" ]; then
  DEV="$TARGET_DEV"
else
  root_disk=$(awk '$2=="/"{print $1}' /proc/mounts)
  cands=()
  for b in /sys/block/sd?; do
    [ -e "$b" ] || continue
    d=/dev/$(basename "$b")
    case "$root_disk" in "$d"*) continue ;; esac
    cands+=("$d")
  done
  [ ${#cands[@]} -gt 0 ] || die "No card reader found. Plug the USB card reader (with the NEW card in it) into the Pi, wait 5 seconds and run this again."
  [ ${#cands[@]} -eq 1 ] || die "More than one USB drive is plugged in (${cands[*]}). Unplug everything except the card reader and try again."
  DEV=${cands[0]}
fi
case "$DEV" in /dev/mmcblk0*) die "Refusing to write to the card the Pi is running from." ;; esac
name=$(basename "$DEV")
bytes=$(( $(cat /sys/block/"$name"/size 2>/dev/null || echo 0) * 512 ))
[ -n "${TARGET_DEV:-}" ] && bytes=$(blockdev --getsize64 "$DEV")
gb=$(( bytes / 1000000000 ))
model=$(cat /sys/block/"$name"/device/model 2>/dev/null | tr -s ' ' || true)
[ "$bytes" -ge 3500000000 ] || [ -n "${TARGET_DEV:-}" ] || die "$DEV is only ${gb} GB. Use a card of 8 GB or more."
[ "$bytes" -le 260000000000 ] || die "$DEV is ${gb} GB, which looks like a hard drive, not a microSD card. Stopping."

say "New card found: $DEV  (${gb} GB ${model})"
echo "EVERYTHING on $DEV will be erased. The Pi's own card is not touched."
[ "$(ask 'Type yes to continue: ')" = "yes" ] || die "Cancelled."

# ---- login for the new system --------------------------------------------------
say "Choose the login for the new system"
user=$(ask 'New username (lowercase, e.g. saurav): ')
echo "$user" | grep -Eq '^[a-z][a-z0-9_-]{0,30}$' || die "Use lowercase letters and digits only."
[ "$user" != "root" ] || die "Pick a different username."
pw1=$(asks 'New password: ')
pw2=$(asks 'Same password again: ')
[ -n "$pw1" ] && [ "$pw1" = "$pw2" ] || die "Passwords didn't match."
salt=$(head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n' | cut -c1-16)
hash=$(printf '%s' "$pw1" | openssl passwd -6 -salt "$salt" -stdin 2>/dev/null || true)
case "$hash" in '$6$'*) ;; *)  # old OpenSSL (e.g. 2015 Raspbian) has no -6; Python 2's crypt does SHA-512
  hash=$(PW="$pw1" SALT="$salt" python -c 'import crypt,os; print(crypt.crypt(os.environ["PW"], "$6$" + os.environ["SALT"]))' 2>/dev/null || true) ;;
esac
case "$hash" in '$6$'*) ;; *) die "Couldn't create the password hash." ;; esac

# ---- download + write -----------------------------------------------------------
CURL="curl -fL --retry 3"
if ! $CURL -s -r 0-0 -o /dev/null "$IMG_LATEST" 2>/dev/null; then
  echo "(This old system's certificates are out of date, so the download skips the certificate check."
  echo " The image is still checked against its SHA-256 before it's used.)"
  CURL="$CURL -k"
fi
url=$($CURL -s -r 0-0 -o /dev/null -w '%{url_effective}' "$IMG_LATEST")
case "$url" in
  *.img.xz) ;;
  "") die "Couldn't reach downloads.raspberrypi.com from this Pi. Check its Ethernet cable; if that's fine, this Pi's software is too old to talk to the site." ;;
  *) die "Couldn't find the latest image (got: $url)." ;;
esac
want=$($CURL -s "$url.sha256" | awk '{print $1}')
echo "$want" | grep -Eq '^[0-9a-f]{64}$' || die "Couldn't fetch the image checksum."

say "Unmounting $DEV"
for p in $(awk -v d="$DEV" 'index($1,d)==1{print $1}' /proc/mounts); do umount "$p"; done

say "Downloading and writing $(basename "$url")"
echo "About 500 MB. On a Pi 2 this takes 15-30 minutes; the bar shows the download."
fifo=$(mktemp -u); mkfifo "$fifo"
sha256sum < "$fifo" | awk '{print $1}' > "$fifo.sum" &
sumpid=$!
$CURL -# "$url" | tee "$fifo" | xz -dc | dd of="$DEV" bs=4M 2>/dev/null
wait "$sumpid"
got=$(cat "$fifo.sum"); rm -f "$fifo" "$fifo.sum"
sync
[ "$got" = "$want" ] || die "Checksum mismatch: the download was corrupted. Run the command again."
echo "Checksum OK."

# ---- pre-configure login + SSH ----------------------------------------------------
say "Setting up your login and SSH on the new card"
blockdev --rereadpt "$DEV" 2>/dev/null || true
sleep 3
part1="${DEV}1"; [ -b "$part1" ] || part1="${DEV}p1"
[ -b "$part1" ] || die "Couldn't see the new card's partitions. Unplug and replug the reader, then ask for help."
mkdir -p "$MNT"
mount -t vfat "$part1" "$MNT"
: > "$MNT/ssh"
printf '%s:%s\n' "$user" "$hash" > "$MNT/userconf.txt"
sync
umount "$MNT"

say "Done. The new card is ready."
cat <<MSG

Next:
  1. Type:  sudo poweroff     and wait for the green light to stop.
  2. Unplug the power. Swap the Pi's microSD for the NEW card (take it out of the reader).
  3. Keep Ethernet plugged into the same router as the printer, and power on.
  4. Log in as '$user' with the password you just chose (the screen shows the Pi's IP above the login).
  5. Carry on with Part A of the print-bridge README.
MSG
