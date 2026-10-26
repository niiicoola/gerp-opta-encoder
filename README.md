# Encoder OPC UA su Arduino Opta Lite

## Preparare la serie

Scheda prevista: **Opta Lite AFX00003**. Encoder della serie:
**Lika IR65-H402500-BCP-08-ST-A con uscita push-pull**, confermato dall'operatore.
Il vecchio E38S6G5 resta un profilo separato per il prototipo.

La procedura completa è in [Preparazione della serie](docs/opta/preparazione-serie.md).
I comandi seguenti controllano soltanto la postazione e il registro di esempio:

```sh
python3 tools/setup_opta.py
python3 tools/provision_opta.py validate devices/example.json
```

`tools/provision_opta.py` permette di registrare i dispositivi, identificarli
via seriale USB, mostrare il piano di installazione e verificare le letture
HTTP/OPC UA. L'upload USB richiede `--apply`. Nessun dato viene scritto in GERP.
Le release nuove sono compilate con core/librerie fissati in `sketch.yaml` e
non sovrascrivono quelle esistenti. Configurazioni reali, rapporti, chiavi e
cache sono locali ed esclusi da Git; conservarne backup separati.

Il profilo Lika usa **2500 PPR nominali, 10000 conteggi/giro in x4**, da
confermare fisicamente. Cambiare profilo richiede oggi una nuova release:
non è ancora disponibile una configurazione persistente modificabile a runtime.
Le misure restano diagnostiche; precisione, velocità massima e persistenza
dei contatori devono essere collaudate prima della produzione.

## Storico delle prove del prototipo

Le sezioni seguenti descrivono le prove precedenti con E38/simulatore.
Le versioni e i percorsi riportati appartengono alla relativa sessione;
per preparare nuovi dispositivi seguire la guida della serie sopra.

## Lettore con aggiornamenti LAN

Il firmware `firmware/opta_encoder_lan` aggiunge al lettore reale un servizio
di manutenzione sulla porta 8080 con aggiornamenti firmati ECDSA. La prima
installazione avviene via USB; i successivi aggiornamenti possono passare
dalla LAN. **Versione caricata e verificata: 0.3.1-lan**, applicata via LAN
il 24 ottobre 2026; server OPC UA verificato dopo il riavvio. La configurazione per l'accesso attraverso VPN da un'altra rete
è stata rimandata dall'utente. Vedi la [guida aggiornamenti LAN](docs/opta/aggiornamenti-lan.md).

I sorgenti `opta_encoder_reader` e `opta_encoder_sim` restano disponibili
separatamente per il recupero e per le prove precedenti. L'aggiunta del
servizio di aggiornamento non convalida la precisione del conteggio fisico.

## Lettore reale diagnostico

Disponibile anche il firmware **opta_encoder_reader v0.2.0**, che legge
realmente I1/I2 senza generare impulsi simulati. Vedi la
[procedura di prova dell'encoder fisico](docs/opta/test-encoder-reale.md).
I suoi dati sono marcati come test non validato e vengono rifiutati dal client
senza l'opzione esplicita --allow-test. Un ingresso fisso durante una prova
senza pull-up esterni non dimostra che l'encoder sia guasto.

## Simulatore conservato separatamente

Questa prima versione pubblica un encoder **simulato**. L'encoder fisico rimane
scollegato; Opta è alimentato via USB e collegato al router/switch via Ethernet.
Il Mac deve raggiungere la stessa rete. È necessario un server DHCP sul router.

## Comportamento della prova

- 20 secondi avanti a 60 RPM (600 conteggi/giro).
- 10 secondi fermo.
- 20 secondi indietro a -60 RPM.
- 10 secondi fermo, poi ripete.
- La posizione sale da 0 a 12000 e torna a 0.
- Il totale degli impulsi sale di 24000 per ciclo.
- Ogni avvio genera un nuovo BootId e azzera i conteggi.
- I valori del progetto sono di sola lettura; i relè restano disattivati.

Non usare questi dati per contabilizzare produzione. Il client rifiuta i valori
simulati a meno che si indichi esplicitamente `--allow-simulation`.

## Ambiente di compilazione

Core installato: Arduino Mbed OS Opta Boards 4.5.0.
Librerie scaricate nel progetto: Arduino_OPC_UA 0.1.2,
Arduino_Opta_Blueprint 0.2.8, Arduino_SerialUpdater 0.0.1,
Arduino_DebugUtils 1.5.0. Il file arduino-cli.yaml contiene i percorsi di questo Mac.
Il compilatore Intel del core richiede Rosetta su Apple Silicon.

```sh
'/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli' compile --fqbn arduino:mbed_opta:opta --config-file arduino-cli.yaml --build-path .build/opta_encoder_sim firmware/opta_encoder_sim
```

Caricamento (sostituisce il programma attualmente presente sull'Opta):

```sh
'/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli' upload --fqbn arduino:mbed_opta:opta --config-file arduino-cli.yaml --port /dev/cu.usbmodem1101 --input-dir .build/opta_encoder_sim
```

## Lettura dei valori

Il monitor seriale a 115200 baud mostra l'indirizzo ottenuto dal router e
l'endpoint `opc.tcp://IP_OPTA:4840`. L'IP viene ristampato ogni 5 secondi.
Al primo collegamento di prova il router ha assegnato **192.168.1.112**:
`opc.tcp://192.168.1.112:4840`. DHCP può assegnare un indirizzo diverso in futuro.
L'operatore può eseguire i comandi direttamente dal proprio Terminale.
Non sono necessari permessi di lettura dello schermo o Accessibilità per
questa procedura; i consensi privacy ChatGPT/Codex sono stati azzerati su richiesta.
Il namespace del progetto è `urn:gerp:encoder:v1`; il client ne risolve l'indice
dinamicamente. Gli identificativi stringa dei nodi sono descritti nella guida.

```sh
.venv/bin/python tools/read_encoder_opcua.py opc.tcp://IP_OPTA:4840 --allow-simulation --samples 10
```

Questa è una prova su rete locale: la build ufficiale usata non include cifratura
OPC UA. La data del dispositivo è inizializzata alla compilazione e non è
sincronizzata: usare UptimeMs per gli intervalli, non i timestamp del dispositivo.
Questi limiti sono esposti anche da Encoder.Simulation e Device.TimeSynchronized.
Prima dell'impiego operativo occorrono configurazione di rete, politica di
sicurezza, persistenza dei conteggi e collaudi dell'encoder reale.
La compilazione segnala 433016 byte di memoria globale su 523624 disponibili
(82%, inclusa l'area statica di 320 KiB riservata al server OPC UA). Le prime
letture sul dispositivo sono riuscite; resta necessario un collaudo prolungato
di memoria e riconnessioni prima della versione operativa.

## Verifiche eseguite

- Firmware compilato e caricato sull'Opta via USB.
- Console USB: DHCP ottenuto, rete collegata e campioni aggiornati.
- Connessione OPC UA reale dal Mac: letture riuscite.
- Ciclo completo verificato sul dispositivo: 17 campioni in oltre un minuto,
  RPM +60/0/-60, posizione crescente/ferma/decrescente e totale monotono.
- Confermato sul dispositivo il rifiuto dei dati simulati quando il client
  non riceve l'opzione --allow-simulation.
- Cinque test di protocollo su server locale: segno e precisione oltre 2^53,
  namespace dinamico, rifiuto della simulazione senza consenso esplicito,
  rifiuto di campioni incompleti, errori di qualità e scritture da client.
- Nessun dato di prova inserito in GERP.

Per ripetere i test locali:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

## Hardware confermato

Opta AFX00003. Etichetta originale encoder fotografata:
rosso VCC, nero 0V, bianco A, verde B, schermatura GND.
Il circuito di uscita dell'encoder deve ancora essere verificato.
Conteggio richiesto: avanti somma, indietro sottrae. Velocità massima da misurare.

Guida: [realizzazione OPC UA](docs/opta/realizzazione-opcua.md).
Fonte libreria: https://github.com/arduino-libraries/Arduino_OPC_UA
