#pragma once
#include <Arduino_Portenta_OTA.h>
#include <mbedtls/pk.h>
#include <mbedtls/sha256.h>
#include <sys/stat.h>
#include <atomic>
#include "BuildInfo.h"
#include "OtaPublicKey.h"

// Push locale del BIN grezzo: usa la partizione e l'applicazione del bootloader
// ufficiale, senza download HTTPS né modifiche alla partizione certificati.
class LocalOtaStorage : public Arduino_Portenta_OTA_QSPI {
 public:
  uint32_t partitionType = 0, partitionStart = 0, partitionSectors = 0, sectorBytes = 0;
  LocalOtaStorage() : Arduino_Portenta_OTA_QSPI(QSPI_FLASH_FATFS_MBR, 2) {}
  int provisionIfBlank() {
    auto *root = mbed::BlockDevice::get_default_instance();
    if (!isOtaCapable() || root->init()) return -20;
    alignas(32) uint8_t buffer[4096];
    // Nessuna modifica se un singolo byte nell'area interessata contiene dati.
    for (uint32_t address = 0; address < 6 * 1024 * 1024; address += sizeof(buffer)) {
      if (root->read(buffer, address, sizeof(buffer))) return -21;
      for (auto byte : buffer) if (byte != 0xff) {
        Serial.print("OTA_INIT_REFUSED_NONEMPTY_AT="); Serial.println(address);
        return -22;
      }
    }
    int result = mbed::MBRBlockDevice::partition(root, 2, 0x0b, 1024 * 1024, 6 * 1024 * 1024);
    if (result) return -23;
    mbed::MBRBlockDevice partition(root, 2);
    mbed::FATFileSystem filesystem("provision");
    result = filesystem.reformat(&partition);
    filesystem.unmount();
    if (result) return -24;
    return beginLocal();
  }
  int beginLocal() {
    if (!isOtaCapable()) return -1;
    _bd_raw_qspi = mbed::BlockDevice::get_default_instance();
    if (_bd_raw_qspi->init()) return -2;
    alignas(32) uint8_t mbr[512];
    if (_bd_raw_qspi->read(mbr, 0, sizeof(mbr))) return -3;
    if (mbr[510] != 0x55 || mbr[511] != 0xaa) return -4;
    auto loadLE32 = [](const uint8_t *p) -> uint32_t {
      return uint32_t(p[0]) | uint32_t(p[1]) << 8 | uint32_t(p[2]) << 16 | uint32_t(p[3]) << 24;
    };
    const uint8_t *p = mbr + 446 + 16;
    partitionType = p[4]; partitionStart = loadLE32(p + 8); partitionSectors = loadLE32(p + 12);
    sectorBytes = max(uint32_t(512), max(uint32_t(_bd_raw_qspi->get_erase_size()),
                       max(uint32_t(_bd_raw_qspi->get_read_size()), uint32_t(_bd_raw_qspi->get_program_size()))));
    // Accetta solo la partizione OTA standard, non un'area dati arbitraria.
    const bool fatType = p[4] == 0x01 || p[4] == 0x04 || p[4] == 0x06 ||
                         p[4] == 0x0b || p[4] == 0x0c || p[4] == 0x0e;
    if (!fatType || uint64_t(partitionStart) * sectorBytes != 1024 * 1024 ||
        uint64_t(partitionSectors) * sectorBytes != 5 * 1024 * 1024) {
      Serial.print("OTA layout: type="); Serial.print(p[4]);
      Serial.print(" start="); Serial.print(loadLE32(p + 8));
      Serial.print(" sectors="); Serial.println(loadLE32(p + 12));
      return -5;
    }
    return init() ? 0 : -6;
  }
};

static constexpr uint32_t OTA_MAX_IMAGE = 0x1c0000; // flash 0x08040000..0x08200000
static const char OTA_PROTOCOL[] = "GERP_OPTA_OTA_V1";
static LocalOtaStorage otaStorage;
static EthernetServer maintenanceServer(8080);
static int otaStorageResult = -99;
static std::atomic<bool> maintenanceReady(false);
static char otaNonce[33];
static uint32_t nonceIssued;

static bool rotateNonce() {
  trng_t source;
  trng_init(&source);
  unsigned char bytes[16];
  size_t received = 0;
  const int result = trng_get_bytes(&source, bytes, sizeof(bytes), &received);
  trng_free(&source);
  if (result || received != sizeof(bytes)) { otaNonce[0] = 0; return false; }
  for (size_t i = 0; i < sizeof(bytes); ++i) snprintf(otaNonce + i * 2, 3, "%02x", bytes[i]);
  nonceIssued = millis();
  return true;
}

static bool readHttpLine(EthernetClient &c, char *line, size_t capacity, uint32_t start) {
  size_t length = 0;
  while (millis() - start < 5000) {
    if (c.available()) {
      int ch = c.read();
      if (ch == '\n') { line[length] = 0; return true; }
      if (ch != '\r') {
        if (length + 1 >= capacity) return false;
        line[length++] = char(ch);
      }
    } else if (!c.connected()) return false;
    else delay(1);
  }
  return false;
}

static void httpReply(EthernetClient &c, int code, const char *body) {
  c.print("HTTP/1.1 "); c.print(code); c.println(" Result");
  c.println("Content-Type: application/json");
  c.println("Cache-Control: no-store");
  c.println("Connection: close");
  c.print("Content-Length: "); c.println(strlen(body)); c.println();
  c.print(body);
}

static int fromHex(char ch) {
  if (ch >= '0' && ch <= '9') return ch - '0';
  if (ch >= 'a' && ch <= 'f') return ch - 'a' + 10;
  return -1;
}

static bool decodeHex(const char *s, uint8_t *out, size_t bytes) {
  if (strlen(s) != bytes * 2) return false;
  for (size_t i = 0; i < bytes; ++i) {
    int a = fromHex(s[i * 2]), b = fromHex(s[i * 2 + 1]);
    if (a < 0 || b < 0) return false;
    out[i] = uint8_t(a * 16 + b);
  }
  return true;
}

static bool verifySignature(uint32_t length, const char *sha, const char *nonce, const char *signature) {
  if (!otaNonce[0] || strcmp(nonce, otaNonce) || millis() - nonceIssued > 60000) return false;
  uint8_t expected[32], sig[80], digest[32];
  size_t sigLength = strlen(signature) / 2;
  if (!decodeHex(sha, expected, sizeof(expected)) || sigLength < 64 || sigLength > sizeof(sig) ||
      !decodeHex(signature, sig, sigLength)) return false;
  char message[180];
  const int n = snprintf(message, sizeof(message), "%s\n%s\n%lu\n%s\n",
                         OTA_PROTOCOL, nonce, static_cast<unsigned long>(length), sha);
  if (mbedtls_sha256_ret(reinterpret_cast<const unsigned char *>(message), n, digest, 0)) return false;
  mbedtls_pk_context key;
  mbedtls_pk_init(&key);
  int result = mbedtls_pk_parse_public_key(&key, reinterpret_cast<const unsigned char *>(OTA_PUBLIC_KEY),
                                          sizeof(OTA_PUBLIC_KEY));
  if (!result) result = mbedtls_pk_verify(&key, MBEDTLS_MD_SHA256, digest, sizeof(digest), sig, sigLength);
  mbedtls_pk_free(&key);
  return result == 0;
}

static bool validVector(const uint8_t *bytes, uint32_t length) {
  uint32_t sp, reset;
  memcpy(&sp, bytes, 4); memcpy(&reset, bytes + 4, 4);
  return (sp & 7) == 0 && sp > 0x24000000 && sp <= 0x24080000 &&
         (reset & 1) && reset >= 0x08040001 && reset < 0x08040000 + length;
}

static bool receiveImage(EthernetClient &c, uint32_t length, const char *expectedHex) {
  FILE *file = fopen("/fs/INCOMING.BIN", "wb");
  if (!file) return false;
  mbedtls_sha256_context hash;
  mbedtls_sha256_init(&hash);
  bool ok = mbedtls_sha256_starts_ret(&hash, 0) == 0;
  uint8_t chunk[1024], first[8], actual[32], expected[32];
  uint32_t received = 0, start = millis(), last = start;
  while (ok && received < length && millis() - start < 120000 && millis() - last < 10000) {
    int available = c.available();
    if (!available) {
      if (!c.connected()) break;
      delay(1); continue;
    }
    size_t count = min(size_t(available), min(sizeof(chunk), size_t(length - received)));
    int n = c.read(chunk, count);
    if (n <= 0) break;
    if (received < sizeof(first)) memcpy(first + received, chunk, min(size_t(n), sizeof(first) - received));
    ok = fwrite(chunk, 1, n, file) == size_t(n) && mbedtls_sha256_update_ret(&hash, chunk, n) == 0;
    received += n; last = millis();
  }
  ok = ok && received == length && mbedtls_sha256_finish_ret(&hash, actual) == 0;
  mbedtls_sha256_free(&hash);
  if (fflush(file)) ok = false;
  if (fclose(file)) ok = false;
  ok = ok && decodeHex(expectedHex, expected, sizeof(expected)) &&
       !memcmp(actual, expected, sizeof(actual)) && validVector(first, length);
  // Rileggi anche il contenuto realmente memorizzato, prima di armare il bootloader.
  if (ok) {
    file = fopen("/fs/INCOMING.BIN", "rb");
    if (!file) ok = false;
    else {
      mbedtls_sha256_init(&hash);
      ok = mbedtls_sha256_starts_ret(&hash, 0) == 0;
      uint32_t readBack = 0;
      size_t n;
      while (ok && (n = fread(chunk, 1, sizeof(chunk), file))) {
        ok = mbedtls_sha256_update_ret(&hash, chunk, n) == 0; readBack += n;
      }
      ok = ok && !ferror(file) && readBack == length && mbedtls_sha256_finish_ret(&hash, actual) == 0;
      mbedtls_sha256_free(&hash); fclose(file);
      ok = ok && !memcmp(actual, expected, sizeof(actual));
    }
  }
  if (!ok) { remove("/fs/INCOMING.BIN"); return false; }
  remove("/fs/UPDATE.BIN");
  if (rename("/fs/INCOMING.BIN", "/fs/UPDATE.BIN")) return false;
  return true;
}

static void maintenanceBegin() {
  otaStorageResult = otaStorage.beginLocal();
  rotateNonce();
  maintenanceServer.begin();
  maintenanceReady = true;
  Serial.print("Manutenzione LAN: http://"); Serial.print(Ethernet.localIP());
  Serial.print(":8080/status | OTA storage="); Serial.println(otaStorageResult);
}

static void maintenancePoll() {
  // Provisioning iniziale esplicito, solo dalla USB e solo su memoria vuota.
  static char serialCommand[40];
  static size_t serialLength = 0;
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n') {
      serialCommand[serialLength] = 0;
      if (!strcmp(serialCommand, "INIT_OTA_IF_EMPTY") && maintenanceReady && otaStorageResult == -4) {
        otaStorageResult = otaStorage.provisionIfBlank();
        Serial.print("OTA_INIT_RESULT="); Serial.println(otaStorageResult);
      }
      serialLength = 0;
    } else if (ch != '\r') {
      if (serialLength + 1 < sizeof(serialCommand)) serialCommand[serialLength++] = ch;
      else serialLength = 0;
    }
  }
  if (!maintenanceReady) return;
  EthernetClient c = maintenanceServer.accept();
  if (!c) return;
  const uint32_t start = millis();
  char line[256];
  if (!readHttpLine(c, line, sizeof(line), start)) { c.stop(); return; }
  bool status = !strcmp(line, "GET /status HTTP/1.1");
  bool update = !strcmp(line, "POST /update HTTP/1.1");
  uint32_t length = 0;
  char sha[65] = {}, nonce[33] = {}, signature[161] = {};
  bool malformed = false, hasLength = false, endHeaders = false;
  size_t headerBytes = 0;
  while (headerBytes < 4096 && readHttpLine(c, line, sizeof(line), start)) {
    headerBytes += strlen(line) + 2;
    if (!line[0]) { endHeaders = true; break; }
    char *colon = strchr(line, ':');
    if (!colon) { malformed = true; break; }
    *colon++ = 0;
    while (*colon == ' ' || *colon == '\t') ++colon;
    if (!strcasecmp(line, "Content-Length")) {
      char *end;
      unsigned long parsed = strtoul(colon, &end, 10);
      if (hasLength || !*colon || *colon < '0' || *colon > '9' || *end || parsed > OTA_MAX_IMAGE) malformed = true;
      length = parsed; hasLength = true;
    } else if (!strcasecmp(line, "Transfer-Encoding")) malformed = true;
    else if (!strcasecmp(line, "X-Firmware-SHA256")) {
      if (sha[0] || strlen(colon) != 64) malformed = true;
      else strcpy(sha, colon);
    } else if (!strcasecmp(line, "X-OTA-Nonce")) {
      if (nonce[0] || strlen(colon) != 32) malformed = true;
      else strcpy(nonce, colon);
    } else if (!strcasecmp(line, "X-OTA-Signature")) {
      if (signature[0] || strlen(colon) >= sizeof(signature)) malformed = true;
      else strcpy(signature, colon);
    }
  }
  if (malformed || !endHeaders) httpReply(c, 400, "{\"error\":\"invalid_headers\"}");
  else if (status) {
    if (!otaNonce[0] || millis() - nonceIssued > 60000) rotateNonce();
    core_util_critical_section_enter();
    int64_t position = decoder.position;
    uint64_t total = decoder.total;
    uint32_t errors = decoder.invalid;
    core_util_critical_section_exit();
    char body[768];
    snprintf(body, sizeof(body),
      "{\"protocol\":\"%s\",\"firmware\":\"%s\",\"boot_id\":\"%s\",\"nonce\":\"%s\","
      "\"ota_ready\":%s,\"storage_result\":%d,\"bootloader\":%u,\"position\":\"%lld\","
      "\"total\":\"%llu\",\"errors\":%lu,\"test_mode\":true,\"uptime_ms\":%lu,"
      "\"partition_type\":%lu,\"partition_start\":%lu,\"partition_sectors\":%lu,\"sector_bytes\":%lu}",
      OTA_PROTOCOL, GERP_FIRMWARE_VERSION, bootId, otaNonce, otaStorageResult == 0 ? "true" : "false",
      otaStorageResult, *reinterpret_cast<const uint8_t *>(0x0801f001), position, total,
      static_cast<unsigned long>(errors), static_cast<unsigned long>(millis()),
      static_cast<unsigned long>(otaStorage.partitionType), static_cast<unsigned long>(otaStorage.partitionStart),
      static_cast<unsigned long>(otaStorage.partitionSectors), static_cast<unsigned long>(otaStorage.sectorBytes));
    httpReply(c, 200, body);
  } else if (!update) httpReply(c, 404, "{\"error\":\"not_found\"}");
  else if (!hasLength || length < 256) httpReply(c, 400, "{\"error\":\"invalid_length\"}");
  else if (!verifySignature(length, sha, nonce, signature)) httpReply(c, 403, "{\"error\":\"signature_rejected\"}");
  else if (otaStorageResult) httpReply(c, 503, "{\"error\":\"ota_storage_not_ready\"}");
  else {
    rotateNonce(); // consuma la sfida anche se il trasferimento fallisce
    Serial.println("OTA: firma accettata, ricezione firmware.");
    if (!receiveImage(c, length, sha)) httpReply(c, 422, "{\"error\":\"image_rejected\"}");
    else if (otaStorage.update() != Arduino_Portenta_OTA::Error::None)
      httpReply(c, 500, "{\"error\":\"bootloader_update_failed\"}");
    else {
      httpReply(c, 202, "{\"accepted\":true,\"rebooting\":true}");
      c.stop(); Serial.println("OTA: immagine verificata, riavvio.");
      delay(500); otaStorage.reset();
    }
  }
  c.stop();
}
