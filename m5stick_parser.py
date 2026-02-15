import re
from typing import Dict, Optional

class M5StickCNameParser:

    @staticmethod
    def parse_device_name(name: str, mac: str) -> Optional[Dict]:
        pattern = r'MT(\d+)_(\d+)_(\d+)'
        match = re.match(pattern, name)

        if not match:
            return None

        temp_raw = int(match.group(1))
        battery = int(match.group(2))
        seq = int(match.group(3))

        return {
            'mac': mac,
            'temperature': round(temp_raw / 100.0, 2),
            'battery': battery,
            'status_flags_raw': 0,
            'status': {
                'moving': False,
                'temperature_alert': False,
                'wifi_active': False
            },
            'sequence_number': seq,
            'device_name': name
        }

parser = M5StickCNameParser()