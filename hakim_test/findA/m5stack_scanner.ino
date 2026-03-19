// this is just to find A, flash to m5 
#include <M5StickCPlus.h>
#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>

const char* TARGET_NAME = "MedTracker_Pi4";
const int SCAN_DURATION = 1;  // seconds per scan cycle

BLEScan* pBLEScan;

// Rolling average for smoother readings
const int AVG_WINDOW = 10;
int rssiBuffer[AVG_WINDOW];
int bufferIndex = 0;
int sampleCount = 0;

int getAverageRSSI() {
    int sum = 0;
    int count = min(sampleCount, AVG_WINDOW);
    for (int i = 0; i < count; i++) {
        sum += rssiBuffer[i];
    }
    return count > 0 ? sum / count : 0;
}

class ScanCallback : public BLEAdvertisedDeviceCallbacks {
    void onResult(BLEAdvertisedDevice device) {
        if (device.haveName() && String(device.getName().c_str()) == TARGET_NAME) {
            int rssi = device.getRSSI();

            // Store in rolling buffer
            rssiBuffer[bufferIndex] = rssi;
            bufferIndex = (bufferIndex + 1) % AVG_WINDOW;
            sampleCount++;

            int avgRSSI = getAverageRSSI();

            // Display on M5StickC screen
            M5.Lcd.fillScreen(BLACK);
            M5.Lcd.setCursor(5, 5);
            M5.Lcd.setTextSize(2);
            M5.Lcd.printf("RSSI: %d", rssi);

            M5.Lcd.setCursor(5, 50);
            M5.Lcd.setTextSize(3);
            M5.Lcd.printf("Avg:%d", avgRSSI);

            M5.Lcd.setCursor(5, 105);
            M5.Lcd.setTextSize(2);
            M5.Lcd.printf("n=%d", sampleCount);

            // Also print to serial for logging
            Serial.printf("RSSI: %d  Avg: %d  Samples: %d\n", rssi, avgRSSI, sampleCount);
        }
    }
};

void setup() {
    M5.begin();
    Serial.begin(115200);

    M5.Lcd.setRotation(3);
    M5.Lcd.fillScreen(BLACK);
    M5.Lcd.setTextColor(WHITE);
    M5.Lcd.setCursor(5, 10);
    M5.Lcd.setTextSize(1);
    M5.Lcd.printf("Scanning for:\n %s", TARGET_NAME);

    BLEDevice::init("");
    pBLEScan = BLEDevice::getScan();
    pBLEScan->setAdvertisedDeviceCallbacks(new ScanCallback());
    pBLEScan->setActiveScan(true);
    pBLEScan->setInterval(100);
    pBLEScan->setWindow(99);

    memset(rssiBuffer, 0, sizeof(rssiBuffer));
}

void loop() {
    pBLEScan->start(SCAN_DURATION, false);
    pBLEScan->clearResults();
}
