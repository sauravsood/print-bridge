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
# Size via blockdev/awk: bash arithmetic on old 32-bit systems can overflow above 2 GB.
bytes=$(blockdev --getsize64 "$DEV" 2>/dev/null || awk '{printf "%.0f", $1*512}' /sys/block/"$name"/size)
gb=$(awk -v b="$bytes" 'BEGIN{printf "%.1f", b/1e9}')
model=$(cat /sys/block/"$name"/device/model 2>/dev/null | tr -s ' ' || true)
if [ -z "${TARGET_DEV:-}" ] && awk -v b="$bytes" 'BEGIN{exit !(b < 3.5e9)}'; then
  echo
  echo "$DEV ($model) reports only ${gb} GB."
  echo "If your card is bigger than that, the card reader can't read it properly. Cards over 32 GB"
  echo "(SDXC) don't work in many older readers. Try a different reader, or a card of 8-32 GB."
  echo "Details for troubleshooting:"
  lsblk 2>/dev/null || cat /proc/partitions
  dmesg 2>/dev/null | grep -iE 'sd[a-z]|usb-storage' | tail -8
  die "Card size check failed."
fi
awk -v b="$bytes" 'BEGIN{exit !(b > 2.6e11)}' && die "$DEV is ${gb} GB, which looks like a hard drive, not a microSD card. Stopping."

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

# The connection can drop on a long download, so fetch it in 8 MB pieces: each piece is
# saved to a small temp file, retried until complete, then fed to xz | dd in order.
total=$($CURL -s -r 0-0 -D - -o /dev/null "$url" | tr -d '\r' \
        | awk 'tolower($1)=="content-range:"{n=split($NF,a,"/"); print a[n]}' | tail -1)
echo "$total" | grep -Eq '^[0-9]+$' || die "Couldn't get the image size from the server."

fetch_pieces() {
  local off=0 piece=8388608 end want_len got_len tries tmp
  tmp=$(mktemp)
  while [ "$off" -lt "$total" ]; do
    end=$(( off + piece - 1 )); [ "$end" -lt "$total" ] || end=$(( total - 1 ))
    want_len=$(( end - off + 1 ))
    tries=0
    while :; do
      if $CURL -s --connect-timeout 20 --speed-time 60 --speed-limit 1000 -r "$off-$end" -o "$tmp" "$url"; then
        got_len=$(stat -c %s "$tmp" 2>/dev/null || echo 0)
        [ "$got_len" -eq "$want_len" ] && break
      fi
      tries=$(( tries + 1 ))
      [ "$tries" -lt 20 ] || { echo "Download kept failing at $(( off / 1048576 )) MB." >&2; rm -f "$tmp"; return 1; }
      printf '\n  (connection dropped, retrying piece in 5s, attempt %d)\n' "$tries" >&2
      sleep 5
    done
    cat "$tmp"
    off=$(( end + 1 ))
    printf '\r  %d / %d MB' $(( off / 1048576 )) $(( total / 1048576 )) >&2
  done
  rm -f "$tmp"
  printf '\n' >&2
}

say "Downloading and writing $(basename "$url")"
echo "About $(( total / 1048576 )) MB. On a Pi 2 this takes 20-40 minutes. Dropped connections are retried automatically."
fifo=$(mktemp -u); mkfifo "$fifo"
sha256sum < "$fifo" | awk '{print $1}' > "$fifo.sum" &
sumpid=$!
fetch_pieces | tee "$fifo" | xz -dc | dd of="$DEV" bs=4M 2>/dev/null || true
wait "$sumpid" || true
got=$(cat "$fifo.sum" 2>/dev/null); rm -f "$fifo" "$fifo.sum"
sync
[ "$got" = "$want" ] || die "The download didn't complete correctly. Check the Ethernet cable and run the same command again."
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
