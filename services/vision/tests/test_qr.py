import io
import uuid
import cv2
import numpy as np
from PIL import Image
import pytest
from app.qr import product_qr


def qr_image(value):
    matrix = cv2.QRCodeEncoder_create().encode(value)
    matrix = np.pad(matrix, 4, constant_values=255)
    image = Image.fromarray(matrix).resize((512, 512), Image.Resampling.NEAREST)
    data = io.BytesIO()
    image.save(data, format='PNG')
    return data.getvalue()


def test_stocklane_qr_retains_stable_product_identity():
    identity = str(uuid.uuid4())
    assert product_qr(qr_image('stocklane:v1:' + identity)) == 'stocklane:v1:' + identity


def test_foreign_qr_is_not_a_product_or_executed_link():
    assert product_qr(qr_image('https://example.com/not-a-product')) is None


def test_malformed_product_identity_is_rejected():
    with pytest.raises(ValueError):
        product_qr(qr_image('stocklane:v1:not-a-uuid'))
