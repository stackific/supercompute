#!/bin/sh
# Pick one public static WireGuard endpoint at random and make it the active
# dial/transit peer. Build-up conf pins the first hub; this runs post-up.
set -eu

IFACE="${SUPERCOMPUTE_WG_IFACE:-scwg0}"
LIST="${SUPERCOMPUTE_PUBLIC_ENDPOINTS:-/etc/supercompute/public-endpoints.list}"
TRANSIT_FILE="${SUPERCOMPUTE_TRANSIT_IPS:-/etc/supercompute/roaming-transit.ips}"

if [ ! -r "${LIST}" ]; then
  echo "missing dial list: ${LIST}" >&2
  exit 1
fi

if ! command -v shuf >/dev/null 2>&1; then
  echo "shuf (coreutils) is required" >&2
  exit 1
fi

if ! command -v wg >/dev/null 2>&1; then
  echo "wg (wireguard-tools) is required" >&2
  exit 1
fi

transit=""
if [ -r "${TRANSIT_FILE}" ]; then
  transit="$(tr -d ' \n\r\t' <"${TRANSIT_FILE}")"
fi

tmp="$(mktemp)"
trap 'rm -f "${tmp}"' EXIT INT TERM

grep -v '^[[:space:]]*#' "${LIST}" | grep -v '^[[:space:]]*$' >"${tmp}" || true
if [ ! -s "${tmp}" ]; then
  echo "no public static endpoints in ${LIST}" >&2
  exit 1
fi

chosen="$(shuf -n 1 "${tmp}")"
chosen_name="$(printf '%s\n' "${chosen}" | awk '{print $1}')"
chosen_pub="$(printf '%s\n' "${chosen}" | awk '{print $2}')"
chosen_ip="$(printf '%s\n' "${chosen}" | awk '{print $3}')"
chosen_ep="$(printf '%s\n' "${chosen}" | awk '{print $4}')"

while read -r name pubkey mesh_ip endpoint; do
  [ -n "${pubkey:-}" ] || continue
  allowed="${mesh_ip}/32"
  if [ "${pubkey}" = "${chosen_pub}" ]; then
    if [ -n "${transit}" ]; then
      allowed="${allowed},${transit}"
    fi
    wg set "${IFACE}" peer "${pubkey}" remove || true
    wg set "${IFACE}" peer "${pubkey}" \
      allowed-ips "${allowed}" \
      endpoint "${chosen_ep}" \
      persistent-keepalive 25
  else
    wg set "${IFACE}" peer "${pubkey}" remove || true
    wg set "${IFACE}" peer "${pubkey}" allowed-ips "${allowed}"
  fi
done <"${tmp}"

echo "roaming dial active: ${chosen_name} (${chosen_ep})"
