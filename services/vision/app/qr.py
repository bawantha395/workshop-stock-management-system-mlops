"""Decode Stocklane product QR identities; never execute external QR contents."""
import uuid
import cv2
import numpy as np
from .encoder import decode

SCALES = (1.0, 0.5, 0.75, 1.5, 2.0)


def _read_qr(image):
    """OpenCV's detector sometimes misses a valid code at one size, so retry at a few scales."""
    detector = cv2.QRCodeDetector()
    for scale in SCALES:
        candidate = image if scale == 1.0 else cv2.resize(
            image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
        value, _, _ = detector.detectAndDecode(candidate)
        if value:
            return value
    return ''


def product_qr(data):
    value = _read_qr(np.asarray(decode(data)))
    if not value or not value.startswith('stocklane:v1:'):
        return None
    identity = str(uuid.UUID(value.removeprefix('stocklane:v1:')))
    return 'stocklane:v1:' + identity
