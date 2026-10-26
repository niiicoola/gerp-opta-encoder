# Encoder Opta → OPC UA → GERP

## Stato

- Hardware USB rilevato: Arduino Opta, /dev/cu.usbmodem1101.
- Variante dichiarata AFX00003: Opta Lite.
- Core installato: arduino:mbed_opta 4.5.0.
- Firmware diagnostico OPC UA con encoder simulato compilato e caricato in
  firmware/opta_encoder_sim. Prima lettura OPC UA reale riuscita dal Mac.
- Endpoint DHCP osservato: opc.tcp://192.168.1.112:4840.
- Caricato anche lettore reale A/B diagnostico v0.2.0 in firmware/opta_encoder_reader:
  avvio USB verificato; il collaudo fisico dei segnali e la versione operativa
  con persistenza e connettore GERP dedicato restano da completare.
- Encoder di prova dichiarato: E38S6G5-600B-G24N, 5–24 V DC.
- Colori confermati dalla foto originale: rosso VCC, nero 0V, bianco A,
  verde B, schermatura GND. Circuito di uscita da confermare prima del cablaggio.
- Movimento inverso: deve sottrarre dalla posizione netta. Velocità massima ignota.

## Architettura prevista

Encoder → interfaccia elettrica compatibile → ingressi Opta → conteggio locale
→ server OPC UA Ethernet → lettura periodica cron GERP → rilevazioni produzione.

Il conteggio deve continuare indipendentemente dalla rete. Il cron legge il
totale, non i singoli impulsi. Gli intervalli senza comunicazione possono essere
recuperati come quantità cumulativa solo se il contatore non viene perso o
azzerato. Non è possibile ricostruire automaticamente la distribuzione della
produzione tra lavori diversi durante un intervallo senza rilevazioni.

## Profili encoder

Separare due configurazioni:

1. Elettrica: tensione, NPN/PNP, push-pull, differenziale, interfaccia esterna.
2. Logica: impulsi/giro, canale singolo o A/B, fattore di decodifica, direzione,
   inversione A/B, impulsi per metro.

Il firmware configurabile non rende compatibili elettricamente tutti gli encoder.
Encoder assoluti SSI/BiSS, bus o sin/cos richiedono interfacce e driver dedicati.

## Contratto OPC UA proposto, non ancora implementato

Namespace URI stabile: urn:gerp:encoder:v1. Il client risolve l'indice del namespace
all'apertura della sessione, senza presumere che sia sempre ns=2.

| Identificativo stringa | Tipo | Significato |
| --- | --- | --- |
| Encoder.TotalPulses | UInt64 | Fronti conteggiati complessivamente, mai decrementati |
| Encoder.NetPosition | Int64 | Posizione con segno, solo con direzione disponibile |
| Encoder.Rpm | Double | Velocità; convenzione di segno documentata nel profilo |
| Encoder.SampleSequence | UInt32 | Versione del campione pubblicato |
| Encoder.CountsPerRevolution | UInt32 | Conteggi effettivi/giro, incluso fattore di decodifica |
| Encoder.ProfileId | String | Identificativo configurazione |
| Encoder.Simulation | Boolean | Vero per il firmware di prova, escluso dalla produzione |
| Device.BootId | String | Identificativo diverso a ogni avvio |
| Device.UptimeMs | UInt64 | Tempo monotono dall'avvio |
| Device.TimeSynchronized | Boolean | Se falso, non usare i timestamp del dispositivo per contabilizzare tempi |
| Device.MeasurementStatus | UInt32 | Stato misura, codici da definire |

Snapshot coerente: leggere sequenza prima e dopo i valori e accettare solo la
stessa sequenza pari; il firmware usa una sequenza dispari durante l'aggiornamento.
I dati pubblicati sono una copia atomica del contatore, non letture parziali
del contatore modificato dagli interrupt.

Usare StatusCode OPC UA per gli errori di lettura. Non sostituire valori mancanti
con zero. Conservare UInt64 come intero o stringa decimale lungo l'intera catena,
evitando conversioni a float che perdono precisione oltre 2^53.

## Connettore GERP

Creare un connettore dedicato senza modificare il comportamento del driver URL.
Riutilizzare gli strumenti OPC UA esistenti solo dopo verifica: readopc.py
attualmente converte i valori in stringhe e può restituire un valore vuoto per
una lettura fallita; il nuovo percorso deve distinguere errore, zero e dato valido.

Il cron apre una sessione, legge uno snapshot e chiude la connessione. Impedire
esecuzioni concorrenti sulla stessa risorsa. Configurare timeout e retry limitati
rispetto alla frequenza effettiva del cron.

Persistenza per risorsa: ultimo conteggio valido, BootId, ProfileId e momento di
ricezione. Riavvio, cambio profilo e regressione del contatore richiedono gestione
esplicita; non imputare delta negativi o salti a una produzione ordinaria.

Separare conteggio totale e quantità netta; definire prima del collaudo se il
movimento inverso deve aumentare, diminuire o non influire sui metri prodotti.

## Percorso di realizzazione

1. Confermare colori dei cavi, uscita encoder, alimentatore, velocità massima,
   rete Ethernet, frequenza cron e politica del movimento inverso.
2. Definire circuito di interfaccia e ingressi utilizzabili dopo verifica dei
   vincoli di interrupt Opta. Ingressi dichiarati fino a 4,5 kHz: verificare
   frequenza per canale e collaudare con margine, senza assumere tale frequenza
   come prestazione garantita del firmware.
3. Firmware diagnostico: solo conteggio e lettura seriale, relè inattivi.
   Verificare impulsi per giro e direzione con rotazioni manuali note.
4. Aggiungere server OPC UA e variabili di sola lettura del progetto.
   Verificare anche quali nodi scrivibili espone l'esempio ufficiale prima di
   usarlo: include funzioni di comando dei relè non necessarie a questo progetto.
5. Realizzare connettore GERP e provare errori, riavvii e letture ripetute.
6. Collaudo con velocità massima, rete assente, riavvio GERP e interruzione
   alimentazione Opta. Definire perdita ammessa e strategia di persistenza
   (checkpoint, memoria dedicata o alimentazione di continuità).
7. Distribuire con configurazione di rete e sicurezza verificata. Non presumere
   cifratura disponibile: controllare le SecurityPolicy della build Arduino.
   Evitare esposizione diretta del servizio su Internet.

## Fonti ufficiali

- https://github.com/arduino-libraries/Arduino_OPC_UA
- https://docs.arduino.cc/hardware/opta/
- https://docs.arduino.cc/tutorials/opta/getting-started-with-interrupts/
- Datasheet, pinout e schemi scaricati in questa cartella.
