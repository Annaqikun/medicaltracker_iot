import re
from typing import Dict, Optional

class M5StickCNameParser:

    @staticmethod
    def parse_manufacturer(mfg_bytes: bytes, mac: str) -> dict | None:
        if len(mfg_bytes) < 16:
            return None

        temp_raw = int.from_bytes(mfg_bytes[6:8], 'big', signed=True)
        temperature = round(temp_raw / 100.0, 2)

        battery = mfg_bytes[8]
        moving = bool(mfg_bytes[9] & 0x01)
        sequence_number = int.from_bytes(mfg_bytes[10:12], 'big')
        hmac = mfg_bytes[12:16].hex()

        return {
            'mac': mac,
            'temperature': temperature,
            'battery': battery,
            'moving': moving,
            'sequence_number': sequence_number,
            'hmac': hmac,
        }

parser = M5StickCNameParser()