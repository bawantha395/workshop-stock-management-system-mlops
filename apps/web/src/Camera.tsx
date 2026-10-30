import { useEffect, useRef, useState } from "react";
import jsQR from "jsqr";
import { Camera as CameraIcon, X } from "lucide-react";

/**
 * One live camera for everything at the counter: a Stocklane QR in view is read by itself,
 * and the big button takes a photo of the part. Frames never leave the device until a photo is taken.
 * Without a camera (or permission) the person can still choose a photo from the device.
 */
export function Camera({
  onQR,
  onBarcode,
  onPhoto,
  onClose,
}: {
  onQR: (value: string) => void;
  onBarcode?: (value: string) => void;
  onPhoto: (file: File) => void;
  onClose: () => void;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  const [barcodeReady, setBarcodeReady] = useState(false);
  useEffect(() => {
    let disposed = false,
      stream: MediaStream | undefined,
      timer: ReturnType<typeof setTimeout>;
    const canvas = document.createElement("canvas");
    const barcodeDetector = "BarcodeDetector" in window
      ? new (window as Window & { BarcodeDetector: new (options: { formats: string[] }) => { detect: (source: HTMLVideoElement) => Promise<{ rawValue: string }[]> } }).BarcodeDetector({ formats: ["ean_8", "ean_13", "upc_a", "upc_e", "code_128"] })
      : null;
    setBarcodeReady(!!barcodeDetector);
    const stop = () => stream?.getTracks().forEach((track) => track.stop());
    const read = () => {
      if (disposed) return;
      const v = video.current;
      if (v && v.readyState >= 2 && v.videoWidth) {
        canvas.width = Math.min(640, v.videoWidth);
        canvas.height = Math.round((v.videoHeight * canvas.width) / v.videoWidth);
        const context = canvas.getContext("2d", { willReadFrequently: true });
        if (context) {
          context.drawImage(v, 0, 0, canvas.width, canvas.height);
          const pixels = context.getImageData(0, 0, canvas.width, canvas.height);
          const code = jsQR(pixels.data, pixels.width, pixels.height, { inversionAttempts: "dontInvert" });
          if (code) {
            disposed = true;
            stop();
            onQR(code.data);
            return;
          }
        }
        if (barcodeDetector && onBarcode) {
          void barcodeDetector.detect(v).then((codes) => {
            const value = codes[0]?.rawValue;
            if (value && !disposed) {
              disposed = true;
              stop();
              onBarcode(value);
            }
          }).catch(() => {});
        }
      }
      timer = setTimeout(read, 200);
    };
    (async () => {
      try {
        if (!navigator.mediaDevices?.getUserMedia) throw new Error("no camera API");
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" }, width: { ideal: 1600 } }, audio: false });
        if (disposed) return stop();
        if (video.current) {
          video.current.srcObject = stream;
          await video.current.play();
          setReady(true);
          read();
        }
      } catch {
        stop();
        if (!disposed) setError("The camera could not start. Allow camera access for this site, or choose a photo from this device.");
      }
    })();
    return () => {
      disposed = true;
      clearTimeout(timer);
      stop();
    };
  }, [onQR, onBarcode]);
  const shoot = () => {
    const v = video.current;
    if (!v || !v.videoWidth) return;
    const canvas = document.createElement("canvas");
    canvas.width = v.videoWidth;
    canvas.height = v.videoHeight;
    canvas.getContext("2d")?.drawImage(v, 0, 0);
    canvas.toBlob(
      (blob) => {
        if (!blob) return setError("The photo could not be taken. Try again.");
        (v.srcObject as MediaStream | null)?.getTracks().forEach((track) => track.stop());
        onPhoto(new File([blob], "part.jpg", { type: "image/jpeg" }));
      },
      "image/jpeg",
      0.92,
    );
  };
  return (
    <div className="stock-modal-shade">
      <section className="scanner-dialog" role="dialog" aria-modal="true" aria-labelledby="camera-title">
        <div className="section-heading">
          <div>
            <p className="eyebrow">CAMERA</p>
            <h2 id="camera-title">Scan a QR or product barcode</h2>
          </div>
          <button className="icon-button" aria-label="Close camera" onClick={onClose}>
            <X />
          </button>
        </div>
        {!error && (
          <div className="live-video">
            <video ref={video} muted playsInline />
            <div className="scan-frame" />
            <span>
              <CameraIcon size={18} /> QR and product barcodes are detected automatically.
            </span>
          </div>
        )}
        {!error && (
          <p className="camera-capability" role="status">
            {barcodeReady
              ? "Barcode reader ready. Point at an EAN, UPC or Code 128 barcode."
              : "This browser does not support live barcodes. Use a QR label or take a photo."}
          </p>
        )}
        {error && (
          <p className="stock-error" role="alert">
            {error}
          </p>
        )}
        {!error && (
          <button className="button primary full camera-shutter" disabled={!ready} onClick={shoot}>
            <CameraIcon size={22} /> Take photo
          </button>
        )}
        <input ref={picker} hidden type="file" accept="image/*" onChange={(e) => e.target.files?.[0] && onPhoto(e.target.files[0])} />
        <button className="button secondary full" onClick={() => picker.current?.click()}>
          Choose a photo from this device
        </button>
      </section>
    </div>
  );
}
