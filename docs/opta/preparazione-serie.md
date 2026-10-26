# Preparazione di più Opta Lite

## Stato e perimetro

Repository dedicato a firmware, profili encoder, strumenti e collaudi.
Il connettore applicativo resta nel repository GERP. La versione attuale
gestisce Opta Lite AFX00003. La serie prevista usa Lika IR65-H402500-BCP-08-ST-A
con uscita push-pull, confermata dall'operatore; il profilo E38S6G5 resta per
il prototipo. Ogni dispositivo con lo stesso profilo riceve lo stesso BIN
diagnostico, compilato una volta per release.

I JSON in `devices/local/` sono il registro di installazione sul computer
dell'operatore: **non vengono scritti nella memoria dell'Opta**. Il profilo
selezionato in compilazione imposta realmente nel BIN il conteggio per giro,
la conversione RPM, il nome del profilo OPC UA e la diagnostica seriale.
Configurazione persistente modificabile a runtime, calibrazione, identità hardware remota, persistenza
dei contatori e abilitazione alla produzione sono una fase successiva.

Non associare una nuova combinazione elettrica solo cambiando un JSON:
uscite NPN, PNP e differenziali richiedono verifica dell'interfaccia e del cablaggio.
I dati diagnostici richiedono sempre `--allow-test`; nessuno strumento inserisce dati in GERP.

## 1. Preparare la postazione una volta

Postazione supportata: macOS o Linux, Python >= 3.9, OpenSSL e Arduino CLI.
Su macOS viene cercato anche il CLI incluso nell'IDE. Su Linux usare il CLI
nel PATH o impostare ARDUINO_CLI al percorso completo. Windows non è ancora
collaudato e gli strumenti seriali usano termios.

Dalla cartella del progetto:

```sh
python3 tools/setup_opta.py
python3 tools/setup_opta.py --install
```

Il primo comando controlla e mostra il piano. Il secondo installa il core
Opta richiesto dal riconoscimento USB, prepara `.venv` e installa il client OPC UA.
Core e librerie sono fissati nel file
`firmware/opta_encoder_lan/sketch.yaml`; alla prima compilazione Arduino CLI
scarica la toolchain e le librerie del profilo in una cache isolata.
Il primo download richiede una connessione Internet e spazio su disco.
Il file `arduino-cli.yaml` è locale: se assente viene creato con percorsi
basati sulla cartella del progetto; se presente viene conservato.

## 2. Preparare e conservare la chiave di firma

Sulla postazione che firma i firmware:

```sh
python3 tools/provision_ota_key.py
```

Il comando riusa la chiave privata esistente, senza sostituirla. In una copia
nuova crea una nuova identità di firma: per aggiornare dispositivi già installati
occorre ripristinare la loro chiave da un backup protetto. La chiave privata
non va condivisa in Git. La chiave pubblica viene inclusa nel firmware.
Questa prima versione usa una sola identità di firma per questa serie;
separazione per cliente e rotazione chiavi sono da progettare prima di ampliare
l'installazione a clienti indipendenti.

## 3. Compilare una release una volta

Esempio di versione nuova (scegliere un numero non ancora presente):

```sh
python3 tools/build_opta_lan.py --version 0.3.3-lan \
  --encoder-profile lika-ir65-2500-x4
```

Nessun caricamento avviene senza `--upload`. Il risultato è in
`.build/releases/0.3.3-lan/`: `firmware.bin`, `manifest.json` con hash SHA-256,
modello, profilo e stato diagnostico, più copia del profilo di compilazione.
Una release esistente non viene sovrascritta. Conservare gli artefatti approvati
in un archivio privato insieme al relativo commit/tag dei sorgenti. `.build/`
è una cartella locale esclusa da Git, non un archivio di backup.

Le vecchie release precedenti a questa procedura possono avere manifesti
incompleti: il nuovo installatore USB le rifiuta. Restano utilizzabili con
lo strumento OTA precedente secondo la relativa guida, senza rigenerarle
con lo stesso numero di versione.

## 4. Registrare ogni Opta

Collegare una sola unità nuova via USB dati e leggere seriale e porta:

```sh
python3 tools/provision_opta.py discover
```

Nell'output cercare `port.address`, `port.properties.serialNumber` e
`matching_boards[].fqbn`. Sono richiesti seriale e riconoscimento Opta:
non è disponibile un'opzione per saltare questi controlli.
Il FQBN identifica la famiglia Opta; la variante Lite AFX00003 va verificata
anche sull'etichetta del dispositivo.

Creare il registro sostituendo seriale, indirizzo e sede con quelli reali:

```sh
python3 tools/provision_opta.py new opta-001 \
  --serial SERIALE_USB_REALE \
  --site officina \
  --encoder-profile lika-ir65-2500-x4 \
  --version 0.3.3-lan \
  --maintenance-url http://192.168.1.112:8080 \
  --opcua-endpoint opc.tcp://192.168.1.112:4840
python3 tools/provision_opta.py validate devices/local/opta-001.json
python3 tools/provision_opta.py validate devices/local/opta-001.json \
  --release .build/releases/0.3.3-lan
```

L'indirizzo nell'esempio appartiene al prototipo; **ogni nuovo Opta deve avere
un indirizzo proprio**. Preferire DHCP con prenotazione sul router per il MAC
del dispositivo. Il comando `new` rifiuta ID e seriali già registrati.
L'eventuale `--machine-id` registra l'associazione alla macchina GERP senza
scrivere nel database. Il registro locale va incluso nei backup operativi.

## 5. Installare via USB

Mostrare prima il piano, con la porta reale rilevata da `discover`:

```sh
python3 tools/provision_opta.py install-usb devices/local/opta-001.json \
  --release .build/releases/0.3.3-lan --port /dev/cu.usbmodem101 --init-ota
```

Per applicare il piano aggiungere `--apply` allo stesso comando. Il programma
verifica hash/versione/profilo del BIN e controlla nuovamente seriale e modello
prima dell'upload. Nessun collegamento seriale avviene nel piano senza `--apply`.
Il caricamento riavvia l'Opta e **azzera i contatori diagnostici**.

`--init-ota` va usato solo per la prima preparazione su memoria vuota.
Il firmware esistente rifiuta l'inizializzazione se trova dati nei primi 6 MiB;
non viene forzata alcuna formattazione. Su un Opta già predisposto omettere
`--init-ota`. Dopo il riavvio l'installatore cerca nuovamente la scheda tramite
lo stesso seriale, senza assumere che la porta sia rimasta identica.

Il rapporto USB indica `uploaded_not_yet_verified`: completare la verifica
via rete. La procedura non riconosce automaticamente se un generico Opta
contiene un'applicazione di produzione: usarla sulle unità destinate a questa serie.

## 6. Verificare via rete e salvare il rapporto

Con alimentazione esterna corretta ed Ethernet collegate:

```sh
.venv/bin/python tools/provision_opta.py verify devices/local/opta-001.json \
  --allow-test --samples 10
```

Da casa, con il tunnel SSH già aperto sulle porte 14840/18080:

```sh
.venv/bin/python tools/provision_opta.py verify devices/local/opta-001.json \
  --maintenance-url http://127.0.0.1:18080 \
  --opcua-endpoint opc.tcp://127.0.0.1:14840 \
  --allow-test --samples 10
```

Il programma confronta versione, profilo, conteggi/giro e BootId tra HTTP e
OPC UA; verifica campioni aggiornati, totale non decrescente e assenza di nuovi
errori di transizione. `reports/ID/` conserva il rapporto JSON. Un contatore di
errori storico viene riportato anche se non cambia durante la prova.

`diagnostic_read_ok` significa comunicazione diagnostica riuscita. Non convalida
precisione o cablaggio e non certifica l'identità hardware remota: il firmware
attuale non espone il seriale USB/MAC attraverso questi servizi. Il percorso
di rete/tunnel deve puntare al dispositivo registrato. Il rapporto mantiene
sempre `production_qualified=false`.

## 7. Qualificare il primo esemplare e poi replicare

Verificare con riferimento meccanico il conteggio di più giri avanti e indietro,
quindi provare la velocità massima prevista e i disturbi reali dell'installazione.
Implementare e collaudare persistenza dei contatori e gestione del riavvio in
GERP prima di contabilizzare produzione. Anche l'aggiornamento OTA va verificato
sull'esemplare pilota prima di applicare una release alle altre unità.

## Repository e verifica locale

Versionare sorgenti, profili non segreti, esempi, test e documentazione.
Sono esclusi chiavi, inventario reale, rapporti, toolchain, cache e binari.
Per pubblicare il repository scegliere un repository **privato** e controllare
il contenuto prima del primo commit/push. Non è stato creato un remoto automaticamente.

```sh
.venv/bin/python -m unittest discover -s tests -v
git status --short
git check-ignore .secrets/opta-ota-private.pem devices/local/opta-001.json reports/opta-001/prova.json
```
