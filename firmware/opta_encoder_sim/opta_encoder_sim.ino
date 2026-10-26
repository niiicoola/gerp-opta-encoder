// Prova OPC UA senza encoder collegato. Non utilizzare per registrare produzione.
#include <Arduino_OPC_UA.h>
#include <PortentaEthernet.h>
#include <mbed_rtc_time.h>
#include <hal/trng_api.h>
#include <array>

REDIRECT_STDOUT_TO(Serial)

static constexpr char NAMESPACE_URI[] = "urn:gerp:encoder:v1";
static constexpr uint32_t COUNTS_PER_REVOLUTION = 600;
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
static UA_UInt64 simulationStartMs;
static UA_UInt32 sequence;

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
  const UA_UInt64 elapsed = uptimeMs - simulationStartMs;
  const UA_UInt64 cycle = elapsed / 60000;
  const uint32_t phase = elapsed % 60000;
  // 20 s avanti, 10 s fermo, 20 s indietro, 10 s fermo.
  UA_Int64 position = 0;
  UA_UInt64 partialTotal = 0;
  UA_Double rpm = 0;
  if (phase < 20000) {
    position = phase * UINT64_C(600) / 1000;
    partialTotal = position;
    rpm = 60;
  } else if (phase < 30000) {
    position = 12000;
    partialTotal = 12000;
  } else if (phase < 50000) {
    const UA_UInt64 reverse = (phase - 30000) * UINT64_C(600) / 1000;
    position = 12000 - reverse;
    partialTotal = 12000 + reverse;
    rpm = -60;
  } else {
    partialTotal = 24000;
  }
  const UA_UInt64 total = cycle * 24000 + partialTotal;
  ++sequence;
  writeScalar(server, "Encoder.SampleSequence", &sequence, &UA_TYPES[UA_TYPES_UINT32]);
  writeScalar(server, "Encoder.NetPosition", &position, &UA_TYPES[UA_TYPES_INT64]);
  writeScalar(server, "Encoder.TotalPulses", &total, &UA_TYPES[UA_TYPES_UINT64]);
  writeScalar(server, "Encoder.Rpm", &rpm, &UA_TYPES[UA_TYPES_DOUBLE]);
  writeScalar(server, "Device.UptimeMs", &uptimeMs, &UA_TYPES[UA_TYPES_UINT64]);
  ++sequence;
  writeScalar(server, "Encoder.SampleSequence", &sequence, &UA_TYPES[UA_TYPES_UINT32]);
  static uint32_t lastPrint = 0;
  if (static_cast<uint32_t>(now - lastPrint) >= 5000) {
    lastPrint = now;
    char message[140];
    snprintf(message, sizeof(message), "OPC UA campione %lu | posizione %lld | totale %llu | RPM %d",
      static_cast<unsigned long>(sequence), static_cast<long long>(position),
      static_cast<unsigned long long>(total), static_cast<int>(rpm));
    Serial.println(message);
  }
}

static void runServer() {
  UA_Server *server = UA_Server_new();
  if (!server) fatal("Creazione server fallita");
  encoderNamespace = UA_Server_addNamespace(server, NAMESPACE_URI);
  UA_ObjectAttributes object = UA_ObjectAttributes_default;
  object.displayName = UA_LOCALIZEDTEXT("en-US", "GERP Encoder SIMULATION");
  check(UA_Server_addObjectNode(server, node("Encoder"),
    UA_NODEID_NUMERIC(0, UA_NS0ID_OBJECTSFOLDER),
    UA_NODEID_NUMERIC(0, UA_NS0ID_ORGANIZES),
    UA_QUALIFIEDNAME(encoderNamespace, "Encoder"),
    UA_NODEID_NUMERIC(0, UA_NS0ID_BASEOBJECTTYPE), object, nullptr, nullptr));

  UA_UInt64 zero64 = 0;
  UA_Int64 zeroSigned = 0;
  UA_UInt32 zero32 = 0;
  UA_Double zeroDouble = 0;
  UA_Boolean simulation = true;
  UA_Boolean testMode = true;
  UA_Boolean measurementValid = false;
  UA_Boolean timeSynchronized = false;
  UA_UInt32 countsPerRev = COUNTS_PER_REVOLUTION;
  UA_String profile = UA_STRING("simulation-600-x1-v1");
  UA_String boot = UA_STRING(bootId);
  addScalar(server, "Encoder.TotalPulses", &zero64, &UA_TYPES[UA_TYPES_UINT64]);
  addScalar(server, "Encoder.NetPosition", &zeroSigned, &UA_TYPES[UA_TYPES_INT64]);
  addScalar(server, "Encoder.Rpm", &zeroDouble, &UA_TYPES[UA_TYPES_DOUBLE]);
  addScalar(server, "Encoder.SampleSequence", &zero32, &UA_TYPES[UA_TYPES_UINT32]);
  addScalar(server, "Encoder.CountsPerRevolution", &countsPerRev, &UA_TYPES[UA_TYPES_UINT32]);
  addScalar(server, "Encoder.ProfileId", &profile, &UA_TYPES[UA_TYPES_STRING]);
  addScalar(server, "Encoder.Simulation", &simulation, &UA_TYPES[UA_TYPES_BOOLEAN]);
  addScalar(server, "Encoder.TestMode", &testMode, &UA_TYPES[UA_TYPES_BOOLEAN]);
  addScalar(server, "Encoder.MeasurementValid", &measurementValid, &UA_TYPES[UA_TYPES_BOOLEAN]);
  addScalar(server, "Device.BootId", &boot, &UA_TYPES[UA_TYPES_STRING]);
  addScalar(server, "Device.UptimeMs", &zero64, &UA_TYPES[UA_TYPES_UINT64]);
  addScalar(server, "Device.TimeSynchronized", &timeSynchronized, &UA_TYPES[UA_TYPES_BOOLEAN]);
  previousMillis = millis();
  uptimeMs = previousMillis;
  simulationStartMs = uptimeMs;
  sample(server, nullptr);
  check(UA_Server_addRepeatedCallback(server, sample, nullptr, 250.0, nullptr));
  check(UA_Server_run_startup(server));
  Serial.print("PRONTO opc.tcp://");
  Serial.print(Ethernet.localIP());
  Serial.println(":4840 | SIMULAZIONE | nessun encoder collegato");
  for (;;) UA_Server_run_iterate(server, true);
}

void setup() {
  Serial.begin(115200);
  const uint32_t start = millis();
  while (!Serial && millis() - start < 1500) delay(10);
  Serial.println("GERP OPC UA - TEST SIMULATO v0.1.0");
  for (auto relay : {RELAY1, RELAY2, RELAY3, RELAY4}) {
    digitalWrite(relay, LOW);
    pinMode(relay, OUTPUT);
  }
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
  while (!Ethernet.begin(nullptr, 10000)) {
    Serial.println("Attendo Ethernet e DHCP: controllare cavo e router.");
    Ethernet.end();
    delay(2000);
  }
  o1heap_ins = o1heapInit(serverHeap.data(), serverHeap.size());
  if (!o1heap_ins) fatal("Memoria OPC UA insufficiente");
  UA_mallocSingleton = o1heap_malloc;
  UA_freeSingleton = o1heap_free;
  UA_callocSingleton = o1heap_calloc;
  UA_reallocSingleton = o1heap_realloc;
  if (opc_ua_server_thread.start(runServer) != osOK) fatal("Avvio thread OPC UA fallito");
}

void loop() {
  delay(5000);
  Serial.print("SIMULAZIONE | IP ");
  Serial.print(Ethernet.localIP());
  Serial.print(" | rete ");
  Serial.println(Ethernet.linkStatus() == LinkON ? "collegata" : "assente");
}
