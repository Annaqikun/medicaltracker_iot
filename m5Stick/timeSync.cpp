#include "timeSync.h"
#include <Arduino.h>
#include <time.h>
#include <sys/time.h>

static const long NTP_GMT_OFFSET_SECONDS = 8 * 3600;   // Singapore
static const int  NTP_DAYLIGHT_OFFSET_SECONDS = 0;

bool syncTimeWithNtp() {
    Serial.println("[TIME] Syncing time with NTP...");
    configTime(NTP_GMT_OFFSET_SECONDS, NTP_DAYLIGHT_OFFSET_SECONDS, "pool.ntp.org", "time.nist.gov");

    struct tm timeinfo;
    for (int i = 0; i < 20; ++i) {
        if (getLocalTime(&timeinfo, 500)) {
            char buf[64];
            strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", &timeinfo);
            Serial.printf("[TIME] Time synced: %s\n", buf);
            return true;
        }

        Serial.print(".");
        delay(500);
    }

    Serial.println();
    Serial.println("[TIME] NTP sync failed");
    return false;
}