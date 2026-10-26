#!/bin/bash
# Monitor di sola lettura via HTTP/LAN, con curl di macOS e nessun accesso USB.
set -u
set -o pipefail
opta_host=${1:-192.168.1.112}
opta_samples=${2:-600}
if [[ ! "$opta_host" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || [[ ! "$opta_samples" =~ ^[1-9][0-9]*$ ]]; then
  printf 'Uso: bash watch_opta_lan.sh IP_OPTA NUMERO_LETTURE\n' >&2
  exit 1
fi
printf 'Monitor LAN http://%s:8080/status - sola lettura, nessuna USB. Ctrl+C per terminare.\n' "$opta_host"
for ((opta_sample=0; opta_sample<opta_samples; opta_sample++)); do
  if ! /usr/bin/curl --silent --show-error --fail --noproxy '*' --connect-timeout 3 --max-time 5 \
    --write-out '\n' "http://$opta_host:8080/status" |
    /usr/bin/perl -MJSON::PP -ne '
      eval {
        $d = decode_json($_);
        die "Protocollo inatteso" unless $d->{protocol} eq "GERP_OPTA_OTA_V1";
        printf "LAN | versione=%s | posizione=%s | totale=%s | errori=%s | OTA=%s | avvio=%s\n",
          $d->{firmware}, $d->{position}, $d->{total}, $d->{errors},
          $d->{ota_ready} ? "pronta" : "non pronta", substr($d->{boot_id}, 0, 8);
        1;
      } or do { print STDERR "Risposta LAN non valida: $@\n"; exit 1; };
    '; then
      printf 'LAN | lettura non riuscita; riprovo.\n' >&2
  fi
  /bin/sleep 1
done
