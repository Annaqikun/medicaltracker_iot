import re
from typing import Dict, Optional

class M5StickCNameParser:

    @staticmethod
    def parse_manufacturer(mfg_bytes: bytes, mac: str) -> dict | None:
        if len(mfg_bytes) <21:
            return None
      
        medicine = mfg_bytes[6:18].decode('ascii',errors = 'ignore').rstrip()


        temp_raw = int.from_bytes(mfg_bytes[18:20], 'big', signed = True)
        temperature = round(temp_raw / 100.0 , 2)

        battery = mfg_bytes[20]
        moving = bool(mfg_bytes[21] & 0x01) if len(mfg_bytes) >=22 else False
        sequence_number = int.from_bytes(mfg_bytes[22:24], 'big') if len(mfg_bytes) >= 24 else 0
        return {
            'mac':mac,
            'medicine': medicine,
            'temperature': temperature,
            'battery': battery,
            'moving':moving,
            'sequence_number': sequence_number,
        }

parser = M5StickCNameParser()