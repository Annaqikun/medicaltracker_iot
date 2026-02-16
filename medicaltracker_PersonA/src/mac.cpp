#include "mac.h"
#include <esp_bt_device.h>

void getMacBytes(uint8_t out[6]) {
  const uint8_t* mac = esp_bt_dev_get_address();
  for (int i = 0; i < 6; i++) out[i] = mac[i];
}

String getMacString() {
  uint8_t mac[6];
  getMacBytes(mac);

  char buf[18];
  sprintf(buf, "%02X:%02X:%02X:%02X:%02X:%02X",
          mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
  return String(buf);
}
