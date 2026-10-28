#!/usr/bin/env python3
"""Build the alarm RCA Lambda package reproducibly (fixed timestamps and order)."""
import io
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'infra/terraform/modules/observability/lambda/alarm_rca'
TARGET = ROOT / 'infra/terraform/modules/observability/lambda/alarm-rca.zip'


def package():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(SOURCE.glob('*.py')):
            info = zipfile.ZipInfo(path.name, date_time=(2026, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    return buffer.getvalue()


if __name__ == '__main__':
    TARGET.write_bytes(package())
    print('Wrote', TARGET.relative_to(ROOT))
