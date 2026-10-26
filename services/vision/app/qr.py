"""Decode Stocklane product QR identities; never execute external QR contents."""
import uuid
import cv2
import numpy as np
from .encoder import decode

def product_qr(data):
    value, _, _ = cv2.QRCodeDetector().detectAndDecode(np.asarray(decode(data)))
    if not value or not value.startswith('stocklane:v1:'):
        return None
    identity = str(uuid.UUID(value.removeprefix('stocklane:v1:')))
    return 'stocklane:v1:' + identity
