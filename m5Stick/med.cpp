#include "med.h"

static String g_medicineName = "PANADOL";

const String& getMedicineName() {
  return g_medicineName;
}

void setMedicineName(const String& name) {
  g_medicineName = name;
}

void toggleMedicine() {
  g_medicineName = (g_medicineName == "PANADOL") ? "AMOXICILLIN" : "PANADOL";
}