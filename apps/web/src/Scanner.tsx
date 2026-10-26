import { useEffect, useRef, useState } from "react";
import jsQR from "jsqr";
import { Camera, X } from "lucide-react";

/** Decode locally: video frames never leave the phone. Stop at the first result. */
export function Scanner({
  onScan,
  onClose,
}: {
  onScan: (value: string) => void;
  onClose: () => void;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let disposed = false,
      stream: MediaStream | undefined,
      timer: ReturnType<typeof setTimeout>;
    const canvas = document.createElement("canvas");
    const read = () => {
      if (disposed) return;
      const v = video.current;
      if (v && v.readyState >= 2 && v.videoWidth) {
        canvas.width = Math.min(720, v.videoWidth);
        canvas.height = Math.round(
          (v.videoHeight * canvas.width) / v.videoWidth,
        );
        const context = canvas.getContext("2d", { willReadFrequently: true });
        if (context) {
          context.drawImage(v, 0, 0, canvas.width, canvas.height);
          const pixels = context.getImageData(
            0,
            0,
            canvas.width,
            canvas.height,
          );
          const code = jsQR(pixels.data, pixels.width, pixels.height, {
            inversionAttempts: "dontInvert",
          });
          if (code) {
            disposed = true;
            stream?.getTracks().forEach((track) => track.stop());
            onScan(code.data);
            return;
          }
        }
      }
      timer = setTimeout(read, 200);
    };
    (async () => {
      try {
        if (!navigator.mediaDevices?.getUserMedia)
          throw new Error(
            "Live scanning needs HTTPS and a supported browser. Use a QR photo or scanner input below.",
          );
        stream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: { ideal: "environment" },
            width: { ideal: 1280 },
          },
          audio: false,
        });
        if (disposed) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        if (video.current) {
          video.current.srcObject = stream;
          await video.current.play();
          read();
        }
      } catch {
        stream?.getTracks().forEach((track) => track.stop());
        if (!disposed)
          setError(
            "Camera could not start. Allow camera access in your browser, or close this scanner and use a QR photo or scanner input.",
          );
      }
    })();
    return () => {
      disposed = true;
      clearTimeout(timer);
      stream?.getTracks().forEach((track) => track.stop());
    };
  }, [onScan]);
  return (
    <div className="stock-modal-shade">
      <section
        className="scanner-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="scanner-title"
      >
        <div className="section-heading">
          <div>
            <p className="eyebrow">LIVE QR SCANNER</p>
            <h2 id="scanner-title">Point at one QR label</h2>
          </div>
          <button
            className="icon-button"
            aria-label="Close scanner"
            onClick={onClose}
          >
            <X />
          </button>
        </div>
        <div className="live-video">
          <video ref={video} muted playsInline />
          <div className="scan-frame" />
          <span>
            <Camera size={18} /> Keep the label inside the frame
          </span>
        </div>
        {error ? (
          <p className="stock-error" role="alert">
            {error}
          </p>
        ) : (
          <p className="stock-help">
            Stops after one scan. Scanning never changes stock.
          </p>
        )}
        <button className="button secondary full" onClick={onClose}>
          Use another method
        </button>
      </section>
    </div>
  );
}
