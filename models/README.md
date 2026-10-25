# Image model

Run `python3 scripts/download_model.py` with the model preparation dependency
`onnx` installed. It downloads the 14 MB ONNX Model Zoo MobileNetV2, verifies its
published-in-this-repository checksum and exports the 1280-dimensional feature
encoder. It is served on CPU with OpenCV DNN. No Ollama model is needed.

This is an ImageNet-pretrained baseline, not a workshop-trained SKU recogniser.
It retrieves approved reference photos and always requires human confirmation.
Similarity is not a calibrated probability. Fine label differences can produce
very similar embeddings. A barcode or physically verified part number is useful
additional evidence. Do not use the baseline for unattended stock posting.

`mlops/train.py` trains a logistic same-SKU calibrator on reviewed real workshop
images while keeping the pretrained encoder fixed. Train/validation/test
sessions must be disjoint. Registration requires validation and independent
test gates. The release contains `encoder.onnx`, `model.json`, `metrics.json`.
The runtime still requires a person to confirm stock movements.

Source: https://github.com/onnx/models/tree/main/validated/vision/classification/mobilenet
Model Zoo licence: https://github.com/onnx/models/blob/main/LICENSE
