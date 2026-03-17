#include "hmac.h"

#include <Preferences.h>
#include <M5Unified.h>
#include "mbedtls/md.h"
#include <esp_mac.h>

static uint8_t hmacKey[32];
static bool keyLoaded = false;

// Forward declaration
static void handleProvisioning();

void checkSerialProvisioning() {
  // No-op — provisioning is handled inside hmacInit()'s cat loop
}

void hmacInit() {
  Preferences prefs;
  prefs.begin("ble_sec", true);  // read-only

  size_t len = prefs.getBytesLength("hmac_key");
  if (len != 32) {
    prefs.end();
    Serial.println("HMAC key not found or wrong size in NVS!");

    // No key — show animated cat while listening for provisioning on serial
    uint8_t frame = 0;
    String serialBuf = "";

    while (true) {
      // Check serial for provisioning ping
      while (Serial.available()) {
        char c = Serial.read();
        serialBuf += c;
      }
      if (serialBuf.indexOf("PROV_PING") >= 0) {
        handleProvisioning();
        // handleProvisioning reboots on success, so we only get here on failure
        serialBuf = "";
      }
      // Keep buffer from growing forever
      if (serialBuf.length() > 100) {
        serialBuf = serialBuf.substring(serialBuf.length() - 20);
      }

      // Draw animated cat
      M5.Display.clearDisplay();
      M5.Display.setCursor(0, 0);

      M5.Display.setTextSize(2);
      M5.Display.setTextColor(TFT_RED);
      M5.Display.println(" NO KEY!");
      M5.Display.println();

      M5.Display.setTextColor(TFT_WHITE);
      M5.Display.setTextSize(2);

      switch (frame % 4) {
        case 0:
          M5.Display.println(" /\\_/\\");
          M5.Display.println("( o.o )");
          M5.Display.println(" > ^ <");
          M5.Display.println("  |_/");
          break;
        case 1:
          M5.Display.println(" /\\_/\\");
          M5.Display.println("( -.- )");
          M5.Display.println(" > ^ <");
          M5.Display.println("  |/");
          break;
        case 2:
          M5.Display.println(" /\\_/\\");
          M5.Display.println("( o.o )");
          M5.Display.println(" > ^ <");
          M5.Display.println("  \\_|");
          break;
        case 3:
          M5.Display.println(" /\\_/\\");
          M5.Display.println("( -.- )  z");
          M5.Display.println(" > ^ < z");
          M5.Display.println("  |/  z");
          break;
      }

      M5.Display.println();
      M5.Display.setTextSize(1);
      M5.Display.setTextColor(TFT_YELLOW);
      M5.Display.println(" Plug in USB & run:");
      M5.Display.println(" provision.py flash");

      frame++;
      delay(800);
    }
  }

  prefs.getBytes("hmac_key", hmacKey, 32);
  prefs.end();
  keyLoaded = true;

  Serial.println("HMAC key loaded from NVS.");
}

// --- Serial provisioning handler (called from cat loop) ---

static void handleProvisioning() {
  // === Step 1: Show cat with "CONNECTING..." ===
  M5.Display.clearDisplay();
  M5.Display.setCursor(0, 0);
  M5.Display.setTextSize(2);
  M5.Display.setTextColor(TFT_GREEN);
  M5.Display.println("  /\\_/\\");
  M5.Display.println(" ( ^.^ )");
  M5.Display.println("  > ^ <");
  M5.Display.println();
  M5.Display.setTextColor(TFT_CYAN);
  M5.Display.println("CONNECTED!");
  M5.Display.setTextSize(1);
  M5.Display.setTextColor(TFT_WHITE);
  M5.Display.println();
  M5.Display.println("Sending MAC...");

  // === Step 2: Send MAC ===
  uint8_t macBytes[6];
  esp_read_mac(macBytes, ESP_MAC_BT);
  char macStr[18];
  sprintf(macStr, "%02X:%02X:%02X:%02X:%02X:%02X",
          macBytes[0], macBytes[1], macBytes[2],
          macBytes[3], macBytes[4], macBytes[5]);
  String mac = String(macStr);

  Serial.print("PROV_MAC:");
  Serial.println(mac);

  M5.Display.printf("MAC: %s\n", macStr);
  M5.Display.println();
  M5.Display.println("Waiting for key...");

  // === Step 3: Wait for key ===
  String keyLine = "";
  unsigned long keyStart = millis();
  while (millis() - keyStart < 30000) {
    while (Serial.available()) {
      char c = Serial.read();
      if (c == '\n' || c == '\r') {
        if (keyLine.startsWith("PROV_KEY:")) {
          goto got_key;
        }
        keyLine = "";
      } else {
        keyLine += c;
      }
    }
    delay(10);
  }

  // Timeout
  M5.Display.setTextColor(TFT_RED);
  M5.Display.println("Timeout! No key.");
  delay(2000);
  return;  // back to cat loop

got_key:
  String hexKey = keyLine.substring(9);
  hexKey.trim();

  if (hexKey.length() != 64) {
    Serial.println("PROV_ERR:Invalid key length");
    M5.Display.setTextColor(TFT_RED);
    M5.Display.println("Bad key length!");
    delay(2000);
    return;  // back to cat loop
  }

  M5.Display.println("Key received!");
  M5.Display.println("Writing to NVS...");

  // === Step 4: Parse and save key ===
  uint8_t newKey[32];
  for (int i = 0; i < 32; i++) {
    String byteStr = hexKey.substring(i * 2, i * 2 + 2);
    newKey[i] = (uint8_t)strtol(byteStr.c_str(), NULL, 16);
  }

  Preferences prefs;
  prefs.begin("ble_sec", false);
  prefs.putBytes("hmac_key", newKey, 32);
  prefs.end();

  Serial.println("PROV_OK");

  // === Step 5: Happy cat! ===
  M5.Display.clearDisplay();
  M5.Display.setCursor(0, 0);
  M5.Display.setTextSize(2);
  M5.Display.setTextColor(TFT_GREEN);
  M5.Display.println("  /\\_/\\");
  M5.Display.println(" ( ^o^ )");
  M5.Display.println("  > ^ <");
  M5.Display.println();
  M5.Display.println("KEY SAVED!");
  M5.Display.setTextSize(1);
  M5.Display.setTextColor(TFT_WHITE);
  M5.Display.println();
  M5.Display.printf("MAC: %s\n", macStr);
  M5.Display.println();
  M5.Display.println("Rebooting...");
  delay(3000);
  ESP.restart();
}

void computeHmac(const uint8_t* data, size_t len, uint8_t* out4bytes) {
  if (!keyLoaded) {
    memset(out4bytes, 0, 4);
    return;
  }

  uint8_t fullHmac[32];

  mbedtls_md_context_t ctx;
  mbedtls_md_init(&ctx);

  const mbedtls_md_info_t* info = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  mbedtls_md_setup(&ctx, info, 1);  // 1 = HMAC mode
  mbedtls_md_hmac_starts(&ctx, hmacKey, 32);
  mbedtls_md_hmac_update(&ctx, data, len);
  mbedtls_md_hmac_finish(&ctx, fullHmac);
  mbedtls_md_free(&ctx);

  // Truncate to first 4 bytes
  memcpy(out4bytes, fullHmac, 4);

  // Zero full HMAC from stack
  memset(fullHmac, 0, 32);
}
