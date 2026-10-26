# Lettore reale A/B diagnostico

Aggiornamento 24 ottobre 2026: sull'Opta è ora caricato il derivato
`firmware/opta_encoder_lan`, versione 0.3.1-lan, con lettura A/B invariata
e aggiornamenti LAN firmati. Vedi [collaudo aggiornamenti LAN](aggiornamenti-lan.md).
Con i pull-up sono stati osservati cambiamenti su entrambi i canali; la prova
manuale riferita dall'utente (12259 -> 9586 -> 12365) non ha ancora convalidato
i 2400 conteggi/giro. L'esito seguente descrive la precedente prova senza pull-up.

Firmware: firmware/opta_encoder_reader, versione 0.2.0.
Firmware compilato e caricato sull'Opta via USB il 23 ottobre 2026.
Avvio verificato dalla console: A=0, B=0, fronti e conteggi a zero; rete
Ethernet assente al momento della lettura. L'utente ha confermato il cablaggio
A/B e il ripristino di alimentazione e USB. In una successiva finestra USB di
25 secondi, durante la quale e' stato richiesto di ruotare la ruota nei due
versi, A/B sono rimasti 00 e fronti, posizione e totale sono rimasti a zero.
La rotazione effettiva nella finestra non e' stata confermata separatamente.
Esito: nessun fronte osservato, prova elettrica inconcludente senza pull-up o
strumento di misura; non attribuire il risultato a guasto dell'encoder.
Successivamente verificata anche la LAN a opc.tcp://192.168.1.112:4840:
sessione OPC UA e lettura diagnostica riuscite, profilo reale x4 e conteggi
a zero. Il blocco diagnostico da 16 nodi ha causato timeout, mentre letture
singole e blocchi da 2/4/10 nodi sono riusciti. Il client legge ora al massimo
8 nodi per richiesta e verifica la sequenza prima/dopo l'intero campione.
La causa del timeout sul blocco piu' grande resta da approfondire.
Nessun impulso viene simulato. I1/A0 legge il filo bianco (A), I2/A1 legge
il verde (B). Il programma legge soltanto questi morsetti e mantiene i relè
disattivati. La console USB funziona indipendentemente dalla rete Ethernet.

## Prova manuale senza resistenze esterne

Questa prova è una verifica esplorativa degli ingressi, non un collaudo completo
dell'encoder. Con uscite NPN open collector prive di pull-up esterni adatti,
entrambi gli ingressi possono restare bassi anche con encoder perfettamente
funzionante. Non è possibile certificare il guasto o il corretto funzionamento
da una lettura fissa. Il firmware non può sostituire il circuito di interfaccia.

1. A caricamento completato, scollegare alimentatore e USB prima di cablare.
2. Conservare rosso a +19 V e nero a 0 V, comuni all'alimentazione Opta.
3. Collegare bianco a I1 e verde a I2. Sono ingressi configurati come digitali,
   non letture analogiche. Non collegare A/B direttamente al positivo.
4. Lasciare la schermatura isolata per la prova da banco, senza trefoli liberi.
5. Ripristinare alimentatore e USB; aprire il monitor seriale a 115200 baud.
6. Lasciare ferma la ruota per circa 5 secondi, poi ruotarla lentamente a mano
   in una direzione, fermarla e ruotarla nell'altra. Non usare un motore.

## Lettura della console

Il programma stampa una riga al secondo:

```text
REALE TEST | A=0 B=0 | frontiA=0 frontiB=0 | posizione=0 totale=0 | errori=0 | SEGNALE_NON_VERIFICABILE_O_FERMO
```

- A/B: livelli digitali attuali.
- frontiA/frontiB: transizioni rilevate per canale dall'avvio.
- posizione: conteggio con segno, avanti e indietro si compensano.
- totale: numero delle transizioni quadratura valide, in entrambe le direzioni.
- errori: transizioni con entrambi i bit cambiati, che non permettono di
  ricostruire una direzione; non contribuiscono al conteggio.

Per il modello dichiarato 600 impulsi/giro è configurata decodifica x4:
**2400 conteggi/giro** se l'intero segnale arriva correttamente agli ingressi.
Un giro in una direzione e uno nella direzione opposta devono compensarsi.
Il segno iniziale dipende dall'ordine A/B e dal punto di vista sull'albero.
Una sola fase attiva non basta a ricostruire correttamente la direzione.

ATTIVITA_RILEVATA_NON_VALIDATA significa che sono stati osservati cambiamenti
su entrambi i canali, ma non costituisce certificazione della misura: rumore,
fronti mancanti o livelli inadeguati possono ancora produrre conteggi errati.
Non attribuire a un guasto encoder lo stato 00 o 11 fisso durante la rotazione.

## OPC UA

Resta lo stesso namespace urn:gerp:encoder:v1 e il server sulla porta 4840.
Con rete e DHCP disponibili, il lettore aggiunge:

- Encoder.LevelA, Encoder.LevelB (Boolean)
- Encoder.EdgesA, Encoder.EdgesB (UInt32)
- Encoder.InvalidTransitions (UInt32)
- Device.MeasurementStatus: 0 = nessuna attivita' completa osservata;
  1 = fronti osservati su entrambi i canali, non validati; 2 = transizioni illegali.
- Encoder.Simulation = false
- Encoder.TestMode = true
- Encoder.MeasurementValid = false
- Encoder.CountsPerRevolution = 2400
- Encoder.ProfileId = real-ab-600-x4-diagnostic-v1

Il client esclude questa diagnostica dalla produzione per impostazione
predefinita. Per leggere i dati esplicitamente come prova:

```sh
.venv/bin/python tools/read_encoder_opcua.py opc.tcp://IP_OPTA:4840 --allow-test --diagnostics --samples 10
```

Nessun dato viene inserito in GERP. I contatori si azzerano a ogni avvio;
BootId cambia a ogni avvio. I timestamp del dispositivo non sono sincronizzati.

## Compilazione e caricamento

```sh
'/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli' compile --fqbn arduino:mbed_opta:opta --config-file arduino-cli.yaml --build-path .build/opta_encoder_reader firmware/opta_encoder_reader
'/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli' upload --fqbn arduino:mbed_opta:opta --config-file arduino-cli.yaml --port /dev/cu.usbmodem1101 --input-dir .build/opta_encoder_reader
```

Il simulatore resta conservato separatamente in firmware/opta_encoder_sim.
Verifiche software: test del client OPC UA e test nativo del
decoder (giro avanti/indietro, posizione negativa, salto illegale, stato fermo,
conteggi oltre il limite a 32 bit). Queste verifiche non sostituiscono il
collaudo dei livelli elettrici o della frequenza effettiva sull'encoder reale.
Al termine del cablaggio e della prova esplorativa sarà necessario completare
l'interfaccia elettrica prima di validare i conteggi.
