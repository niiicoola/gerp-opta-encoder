// Lettore A/B reale diagnostico: dati NON validati per la produzione.
#include <Arduino_OPC_UA.h>
#include <PortentaEthernet.h>
#include <mbed_rtc_time.h>
#include <hal/trng_api.h>
#include <array>
#include "Quadrature.h"
#include "EncoderProfile.h"

REDIRECT_STDOUT_TO(Serial)

static constexpr char NAMESPACE_URI[] = "urn:gerp:encoder:v1";
static constexpr uint32_t PULSES_PER_REVOLUTION = GERP_ENCODER_PPR;
static constexpr uint32_t COUNTS_PER_REVOLUTION = GERP_ENCODER_COUNTS_PER_REVOLUTION;
static constexpr pin_size_t ENCODER_A = A0; // morsetto I1: fase A del profilo selezionato
static constexpr pin_size_t ENCODER_B = A1; // morsetto I2: fase B del profilo selezionato
static volatile Quadrature decoder;

static uint8_t readAB() {
  return (digitalRead(ENCODER_A) == HIGH ? 2 : 0) |
         (digitalRead(ENCODER_B) == HIGH ? 1 : 0);
}

static void onEncoderChange() { decoder.observe(readAB()); }
static constexpr size_t STACK_SIZE = 16 * 1024;
static constexpr size_t HEAP_SIZE = 320 * 1024;
alignas(uint32_t) static std::array<uint8_t, STACK_SIZE> serverStack;
alignas(O1HEAP_ALIGNMENT) static std::array<uint8_t, HEAP_SIZE> serverHeap;
O1HeapInstance *o1heap_ins = nullptr;
// Nome globale richiesto dall'adattamento mbed della libreria Arduino_OPC_UA.
rtos::Thread opc_ua_server_thread(osPriorityNormal, STACK_SIZE, serverStack.data());
static UA_UInt16 encoderNamespace;
static char bootId[33];
static uint32_t previousMillis;
static UA_UInt64 uptimeMs;
static int64_t previousPosition = 0;
static UA_UInt64 previousSampleUptime = 0;
static UA_UInt32 sequence;
#include "LanUpdate.h"

static void fatal(const char *message) {
  for (;;) {
    Serial.print("ERRORE: ");
    Serial.println(message);
    delay(2000);
  }
}

static void check(UA_StatusCode result) {
  if (UA_StatusCode_isBad(result)) {
    Serial.print("Errore OPC UA: ");
    fatal(UA_StatusCode_name(result));
  }
}

static UA_NodeId node(const char *name) {
  return UA_NODEID_STRING(encoderNamespace, const_cast<char *>(name));
}

static void addScalar(UA_Server *server, const char *name,
                      const void *value, const UA_DataType *type) {
  UA_VariableAttributes attributes = UA_VariableAttributes_default;
  attributes.displayName = UA_LOCALIZEDTEXT("en-US", const_cast<char *>(name));
  attributes.dataType = type->typeId;
  attributes.accessLevel = UA_ACCESSLEVELMASK_READ;
  UA_Variant_setScalar(&attributes.value, const_cast<void *>(value), type);
  check(UA_Server_addVariableNode(server, node(name), node("Encoder"),
    UA_NODEID_NUMERIC(0, UA_NS0ID_HASCOMPONENT),
    UA_QUALIFIEDNAME(encoderNamespace, const_cast<char *>(name)),
    UA_NODEID_NUMERIC(0, UA_NS0ID_BASEDATAVARIABLETYPE), attributes, nullptr, nullptr));
}

static void writeScalar(UA_Server *server, const char *name,
                        const void *value, const UA_DataType *type) {
  UA_Variant variant;
  UA_Variant_init(&variant);
  UA_Variant_setScalar(&variant, const_cast<void *>(value), type);
  check(UA_Server_writeValue(server, node(name), variant));
}

static void sample(UA_Server *server, void *) {
  const uint32_t now = millis();
  uptimeMs += static_cast<uint32_t>(now - previousMillis);
  previousMillis = now;
  core_util_critical_section_enter();
  const UA_Int64 position = decoder.position;
  const UA_UInt64 total = decoder.total;
  const UA_UInt32 edgesA = decoder.edgesA;
  const UA_UInt32 edgesB = decoder.edgesB;
  const UA_UInt32 invalid = decoder.invalid;
  const uint8_t ab = readAB();
  core_util_critical_section_exit();
  const UA_Boolean levelA = (ab & 2) != 0;
  const UA_Boolean levelB = (ab & 1) != 0;
  const UA_UInt64 elapsed = uptimeMs - previousSampleUptime;
  const UA_Double rpm = previousSampleUptime && elapsed
    ? (position - previousPosition) * 60000.0 / (COUNTS_PER_REVOLUTION * static_cast<double>(elapsed))
    : 0;
  previousPosition = position;
  previousSampleUptime = uptimeMs;
  const UA_UInt32 diagnostic = invalid ? 2 : (edgesA && edgesB ? 1 : 0);
  ++sequence;
  writeScalar(server, "Encoder.SampleSequence", &sequence, &UA_TYPES[UA_TYPES_UINT32]);
  writeScalar(server, "Encoder.NetPosition", &position, &UA_TYPES[UA_TYPES_INT64]);
  writeScalar(server, "Encoder.TotalPulses", &total, &UA_TYPES[UA_TYPES_UINT64]);
  writeScalar(server, "Encoder.Rpm", &rpm, &UA_TYPES[UA_TYPES_DOUBLE]);
  writeScalar(server, "Encoder.LevelA", &levelA, &UA_TYPES[UA_TYPES_BOOLEAN]);
  writeScalar(server, "Encoder.LevelB", &levelB, &UA_TYPES[UA_TYPES_BOOLEAN]);
  writeScalar(server, "Encoder.EdgesA", &edgesA, &UA_TYPES[UA_TYPES_UINT32]);
  writeScalar(server, "Encoder.EdgesB", &edgesB, &UA_TYPES[UA_TYPES_UINT32]);
  writeScalar(server, "Encoder.InvalidTransitions", &invalid, &UA_TYPES[UA_TYPES_UINT32]);
  writeScalar(server, "Device.MeasurementStatus", &diagnostic, &UA_TYPES[UA_TYPES_UINT32]);
  writeScalar(server, "Device.UptimeMs", &uptimeMs, &UA_TYPES[UA_TYPES_UINT64]);
  ++sequence;
  writeScalar(server, "Encoder.SampleSequence", &sequence, &UA_TYPES[UA_TYPES_UINT32]);

}

static void runServer() {
  while (!Ethernet.begin(nullptr, 10000)) {
    Serial.println("Attendo Ethernet e DHCP: controllare cavo e router.");
    Ethernet.end();
    delay(2000);
  }
  UA_Server *server = UA_Server_new();
  if (!server) fatal("Creazione server fallita");
  encoderNamespace = UA_Server_addNamespace(server, NAMESPACE_URI);
  UA_ObjectAttributes object = UA_ObjectAttributes_default;
  object.displayName = UA_LOCALIZEDTEXT("en-US", "GERP Encoder REAL DIAGNOSTIC");
  check(UA_Server_addObjectNode(server, node("Encoder"),
    UA_NODEID_NUMERIC(0, UA_NS0ID_OBJECTSFOLDER),
    UA_NODEID_NUMERIC(0, UA_NS0ID_ORGANIZES),
    UA_QUALIFIEDNAME(encoderNamespace, "Encoder"),
    UA_NODEID_NUMERIC(0, UA_NS0ID_BASEOBJECTTYPE), object, nullptr, nullptr));

  UA_UInt64 zero64 = 0;
  UA_Int64 zeroSigned = 0;
  UA_UInt32 zero32 = 0;
  UA_Double zeroDouble = 0;
  UA_Boolean simulation = false;
  UA_Boolean testMode = true;
  UA_Boolean measurementValid = false;
  UA_Boolean timeSynchronized = false;
  UA_UInt32 countsPerRev = COUNTS_PER_REVOLUTION;
  UA_String profile = UA_STRING(GERP_ENCODER_PROFILE_ID);
  UA_String boot = UA_STRING(bootId);
  UA_String firmwareVersion = UA_STRING(GERP_FIRMWARE_VERSION);
  addScalar(server, "Device.FirmwareVersion", &firmwareVersion, &UA_TYPES[UA_TYPES_STRING]);
  addScalar(server, "Encoder.TotalPulses", &zero64, &UA_TYPES[UA_TYPES_UINT64]);
  addScalar(server, "Encoder.NetPosition", &zeroSigned, &UA_TYPES[UA_TYPES_INT64]);
  addScalar(server, "Encoder.Rpm", &zeroDouble, &UA_TYPES[UA_TYPES_DOUBLE]);
  addScalar(server, "Encoder.SampleSequence", &zero32, &UA_TYPES[UA_TYPES_UINT32]);
  addScalar(server, "Encoder.CountsPerRevolution", &countsPerRev, &UA_TYPES[UA_TYPES_UINT32]);
  addScalar(server, "Encoder.ProfileId", &profile, &UA_TYPES[UA_TYPES_STRING]);
  addScalar(server, "Encoder.Simulation", &simulation, &UA_TYPES[UA_TYPES_BOOLEAN]);
  addScalar(server, "Encoder.TestMode", &testMode, &UA_TYPES[UA_TYPES_BOOLEAN]);
  addScalar(server, "Encoder.MeasurementValid", &measurementValid, &UA_TYPES[UA_TYPES_BOOLEAN]);
  UA_Boolean initialLevel = false;
  addScalar(server, "Encoder.LevelA", &initialLevel, &UA_TYPES[UA_TYPES_BOOLEAN]);
  addScalar(server, "Encoder.LevelB", &initialLevel, &UA_TYPES[UA_TYPES_BOOLEAN]);
  addScalar(server, "Encoder.EdgesA", &zero32, &UA_TYPES[UA_TYPES_UINT32]);
  addScalar(server, "Encoder.EdgesB", &zero32, &UA_TYPES[UA_TYPES_UINT32]);
  addScalar(server, "Encoder.InvalidTransitions", &zero32, &UA_TYPES[UA_TYPES_UINT32]);
  addScalar(server, "Device.MeasurementStatus", &zero32, &UA_TYPES[UA_TYPES_UINT32]);
  addScalar(server, "Device.BootId", &boot, &UA_TYPES[UA_TYPES_STRING]);
  addScalar(server, "Device.UptimeMs", &zero64, &UA_TYPES[UA_TYPES_UINT64]);
  addScalar(server, "Device.TimeSynchronized", &timeSynchronized, &UA_TYPES[UA_TYPES_BOOLEAN]);
  previousMillis = millis();
  uptimeMs = previousMillis;
  sample(server, nullptr);
  check(UA_Server_addRepeatedCallback(server, sample, nullptr, 250.0, nullptr));
  check(UA_Server_run_startup(server));
  maintenanceBegin();
  Serial.print("PRONTO opc.tcp://");
  Serial.print(Ethernet.localIP());
  Serial.println(":4840 | LETTORE REALE A/B | DIAGNOSTICA NON VALIDATA");
  for (;;) UA_Server_run_iterate(server, true);
}

void setup() {
  Serial.begin(115200);
  const uint32_t start = millis();
  while (!Serial && millis() - start < 1500) delay(10);
  Serial.print("GERP OPC UA - LETTORE REALE + OTA LAN v");
  Serial.println(GERP_FIRMWARE_VERSION);
  for (auto relay : {RELAY1, RELAY2, RELAY3, RELAY4}) {
    digitalWrite(relay, LOW);
    pinMode(relay, OUTPUT);
  }
  // I1/I2 restano ingressi, mai uscite. Nessun pull-up industriale via software.
  pinMode(ENCODER_A, INPUT);
  pinMode(ENCODER_B, INPUT);
  decoder.begin(readAB());
  attachInterrupt(digitalPinToInterrupt(ENCODER_A), onEncoderChange, CHANGE);
  attachInterrupt(digitalPinToInterrupt(ENCODER_B), onEncoderChange, CHANGE);
  Serial.print("Profilo encoder: ");
  Serial.println(GERP_ENCODER_PROFILE_ID);
  Serial.print("I1=fase A, I2=fase B; conteggi/giro x4: ");
  Serial.println(COUNTS_PER_REVOLUTION);
  Serial.println("Verificare pinout e interfaccia elettrica del profilo; livelli fissi non provano un guasto encoder.");
  // Identificativo casuale per riconoscere i riavvii, senza scrivere la flash.
  trng_t randomSource;
  trng_init(&randomSource);
  unsigned char randomBytes[16];
  size_t received = 0;
  const int randomResult = trng_get_bytes(&randomSource, randomBytes, sizeof(randomBytes), &received);
  trng_free(&randomSource);
  if (randomResult || received != sizeof(randomBytes)) fatal("Generazione BootId fallita");
  for (size_t i = 0; i < sizeof(randomBytes); ++i)
    snprintf(bootId + i * 2, 3, "%02x", randomBytes[i]);

  // Ora locale di compilazione: i timestamp OPC UA non sono sincronizzati in questa prova.
  set_time(opcua::timeToStr(__DATE__));
  o1heap_ins = o1heapInit(serverHeap.data(), serverHeap.size());
  if (!o1heap_ins) fatal("Memoria OPC UA insufficiente");
  UA_mallocSingleton = o1heap_malloc;
  UA_freeSingleton = o1heap_free;
  UA_callocSingleton = o1heap_calloc;
  UA_reallocSingleton = o1heap_realloc;
  if (opc_ua_server_thread.start(runServer) != osOK) fatal("Avvio thread OPC UA fallito");
}

void loop() {
  maintenancePoll();
  core_util_critical_section_enter();
  const int64_t position = decoder.position;
  const uint64_t total = decoder.total;
  const uint32_t edgesA = decoder.edgesA;
  const uint32_t edgesB = decoder.edgesB;
  const uint32_t invalid = decoder.invalid;
  const uint8_t ab = readAB();
  core_util_critical_section_exit();
  char message[240];
  snprintf(message, sizeof(message),
    "REALE TEST | A=%d B=%d | frontiA=%lu frontiB=%lu | posizione=%lld totale=%llu | errori=%lu | %s",
    (ab & 2) != 0, (ab & 1) != 0, static_cast<unsigned long>(edgesA), static_cast<unsigned long>(edgesB),
    static_cast<long long>(position), static_cast<unsigned long long>(total),
    static_cast<unsigned long>(invalid),
    invalid ? "ERRORI_CUMULATIVI_DALL_AVVIO" :
    edgesA && edgesB ? "ATTIVITA_RILEVATA_NON_VALIDATA" : "SEGNALE_NON_VERIFICABILE_O_FERMO");
  Serial.println(message);
  static uint32_t lastNetworkPrint = 0;
  if (static_cast<uint32_t>(millis() - lastNetworkPrint) >= 5000) {
    lastNetworkPrint = millis();
    Serial.print("LETTORE REALE TEST | IP ");
    Serial.print(Ethernet.localIP());
    Serial.print(" | rete ");
    Serial.println(Ethernet.linkStatus() == LinkON ? "collegata" : "assente");
  }
  // Il server manutenzione deve accettare connessioni senza attese di un secondo.
  const uint32_t until = millis();
  while (millis() - until < 1000) { maintenancePoll(); delay(2); }
}
