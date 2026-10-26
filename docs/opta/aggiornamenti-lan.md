# Aggiornamenti firmware tramite LAN

Lettore dedicato Arduino/C++, non progetto Arduino PLC IDE. Il programma conserva
lettura encoder su I1/I2, diagnostica seriale e server OPC UA sulla porta 4840.
Il servizio manutenzione HTTP usa la porta 8080, esclusivamente su LAN o VPN.

## Uso dal Mac

Stato e versione:

```sh
python3 /Users/nicola/Workspace/Sites/arduino/tools/opta_lan.py 192.168.1.112 status
```

Modificare i sorgenti in `firmware/opta_encoder_lan/`. Per compilare una nuova
versione e applicarla, scegliendo un numero versione nuovo:

```sh
python3 /Users/nicola/Workspace/Sites/arduino/tools/build_opta_lan.py --version 0.3.4-lan --encoder-profile e38s6g5-600b-g24n-x4 --upload 192.168.1.112
```

Il comando compila, archivia BIN e manifesto in `.build/releases/`, firma
l'aggiornamento e controlla versione, nuovo BootId e disponibilità OTA dopo il
riavvio. Per compilare soltanto, omettere `--upload`. Usare sempre il BIN di
questo progetto: caricare un altro programma potrebbe rimuovere l'accesso LAN.

Il profilo nell'esempio conserva l'E38 del prototipo. Per la serie Lika usare
`--encoder-profile lika-ir65-2500-x4` e un registro coerente. La versione
deve essere nuova: lo script rifiuta di sovrascrivere una release esistente.
La prima compilazione con profilo scarica le dipendenze fissate in sketch.yaml.

Per un BIN già compilato:

```sh
python3 /Users/nicola/Workspace/Sites/arduino/tools/opta_lan.py 192.168.1.112 upload /percorso/firmware.bin --expect-version 0.3.2-lan
```

## Firma e memoria

- Chiave privata ECDSA P-256: `.secrets/opta-ota-private.pem`, permessi 0600,
  esclusa dal controllo versione. Conservarne una copia sicura: senza questa
  chiave il dispositivo rifiuta gli aggiornamenti e occorre ripartire dalla USB.
- Sul dispositivo viene inclusa solo la chiave pubblica `OtaPublicKey.h`.
- Una sfida casuale con scadenza 60 secondi e una firma vincolano dimensione e
  SHA-256 dell'immagine. La sfida viene consumata prima della ricezione.
- Il firmware controlla dimensione, firma, hash ricevuto, vettori Opta M7 e hash
  riletto dal file prima di armare il bootloader ufficiale Arduino.
- I dati vengono trasferiti in chiaro su HTTP; il firmware e le chiavi pubbliche
  non sono segreti. La firma impedisce l'applicazione di modifiche non firmate.
  Non inoltrare la porta 8080 o OPC UA su Internet: usare la VPN.
- Partizione OTA: numero 2, da 1 MiB a 6 MiB, FAT. La predisposizione USB iniziale
  rifiuta ogni modifica se trova un byte non cancellato nei primi 6 MiB.
- Non sono stati formattati firmware Wi-Fi, certificati, KVStore o dati utente.
- Un trasferimento incompleto o un hash errato non arma il bootloader. Non
  interrompere l'alimentazione durante l'applicazione del firmware. Questo
  meccanismo non offre un ripristino automatico se il nuovo programma non avvia
  più la rete: mantenere disponibile il recupero USB.

## Accesso da un'altra rete

Lettura remota verificata il 26 ottobre 2026 attraverso un tunnel SSH verso
un server Linux dell'ufficio raggiungibile via VPN: porta locale 14840 verso
Opta:4840 e 18080 verso Opta:8080. Lo username SSH resta noto solo all'operatore.
La VPN già presente su
Mac/server deve fornire un percorso verso la LAN dell'Opta. Non basta installare
un certificato sull'Opta: qui non è installato un client VPN. Verificare in seguito
instradamento o un host di passaggio nella rete dell'Opta; eventuali sottoreti
192.168.1.0/24 sovrapposte vanno gestite nella VPN. Riservare al MAC dell'Opta
l'indirizzo DHCP sul router oppure usare il nuovo indirizzo assegnato.

## Limiti della misura

Le misure rimangono diagnostiche e non validate: con il cablaggio provvisorio è
stata osservata attività su entrambi i canali, ma la prima prova manuale di un
giro ha restituito -2673 e +2779 conteggi anziché +/-2400, con ritorno +106.
La precisione deve essere verificata con riferimenti meccanici e cablaggio stabile.
Ogni aggiornamento/riavvio azzera ancora i contatori: non utilizzare questo
firmware per contabilizzare produzione senza persistenza e collaudo.

## Collaudo LAN

Eseguito il 24 ottobre 2026 su Opta Lite AFX00003, IP 192.168.1.112,
bootloader 25, core Arduino Mbed Opta 4.6.0:

- Prima installazione e predisposizione della partizione via USB. Scansione dei
  primi 6 MiB: interamente cancellati (0xff) prima delle modifiche. Creata e
  formattata solo la partizione OTA numero 2.
- Geometria verificata usando settori Mbed da 4096 byte: inizio 256 settori,
  lunghezza 1280 settori, cioè intervallo 1..6 MiB; tipo FAT 0x0b.
- Sei prove negative sul dispositivo: senza firma 403, firma errata 403,
  dimensione eccessiva 400, hash alterato 422, sfida già consumata 403,
  vettori di un'altra scheda 422. Nessun riavvio durante queste prove.
- Aggiornamento **esclusivamente HTTP/LAN** da 0.3.0-lan a **0.3.1-lan**:
  inviati 613888 byte, risposta 202, riavvio verificato da nuovo BootId e
  nuova versione. `ota_ready=true` dopo il riavvio.
- Server OPC UA nuovamente leggibile dopo OTA: tre campioni diagnostici reali,
  profilo x4 da 2400 conteggi/giro. Ruota ferma, nessuna nuova verifica di
  precisione meccanica effettuata in questa sessione.
- Undici test Python locali e test C++ del decoder superati.

La compilazione usa 438400 byte di RAM statica (83%), con 85224 byte rimanenti:
il collaudo funzionale OTA è riuscito, ma serve ancora un collaudo prolungato
di stabilità per l'impiego operativo. Nessun dato è stato registrato in GERP.

Fonti: libreria ufficiale Arduino_Portenta_OTA 1.2.1 e relativo protocollo del
bootloader per UPDATE.BIN in FAT/MBR; core Arduino Mbed Opta 4.6.0.
https://github.com/arduino-libraries/Arduino_Portenta_OTA
