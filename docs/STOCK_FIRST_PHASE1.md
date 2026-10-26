# Stock-first phase one

**UI update:** daily screens now use the [warehouse task workflow](WAREHOUSE_UX.md).
Use that guide for current receiving, stock-out, scanning and deployment steps.
The model and backend scope below remains unchanged.

## Scope

The web UI now handles stock only, for filters, belts, parts, sealed containers,
measured liquids and other catalogue items. Jobs, customers, labour and invoices
are absent from this UI. Existing workshop APIs and data remain compatible.

## Daily flow

1. Register an item: manufacturer, part number if visible, description,
   specification, size, shelf, counting unit and initial physical quantity.
2. Registration generates a stable product QR. Download PNG or print/save PDF.
   The QR identifies a product type; it does not identify a unique physical unit.
3. Select IN or OUT. Scan with a keyboard QR reader, paste the QR, or use the
   mobile camera photo input. A close-up product photo searches approved references.
4. Verify the exact item and quantity, then confirm. A photo never changes stock
   automatically. OUT does not require a repair job. Negative stock is rejected.
5. Unknown products can be registered from their photo. Optional Bedrock provides
   visible label suggestions, including manufacturer part number. A person reviews
   every field. Manufacturer plus part number is unique when a part number exists.
6. Owners edit metadata, archive zero-stock items and restore them. Stable QR,
   quantity history and audit records remain. Quantity changes use ledger movements.

## What AI does

- Existing pretrained MobileNetV2 encoder retrieves similar approved reference
  images. This is not a workshop-trained object detector. Similarity is not an
  accuracy percentage. The configured threshold is not yet workshop-calibrated.
- Bedrock can propose visible label fields. Prompt version v2 limits its output;
  it does not approve an item, invent stock, infer vehicle fitment or change quantity.
- QR decoding is deterministic computer vision. It does not require an LLM.
- Adding reference photos indexes examples; it does not retrain the encoder.

The existing vision deployment contains these photo/AI capabilities for this
phase. Separate ML and AI deployments, a workshop training/evaluation dataset,
SageMaker training runs and automated model promotion remain later milestones.
No new AWS deployment or Bedrock invocation was performed while preparing this ZIP.

## Wi-Fi camera

The edge connector accepts a controlled tray USB camera or an RTSP/HTTP(S)
stream through CAMERA_STREAM_URL. Set camera secrets in the device environment,
not source control. Existing Cognito camera credentials and HTTPS capture endpoint
are required. Start with an empty fixed tray; station direction is IN or OUT.
Evidence enters Camera inbox for staff review. Retries reuse the capture ID.
This is not a room-wide item counter. Camera model/protocol and tray behaviour
need physical hardware testing before relying on them.

## Deploy through the existing pipelines

1. Synchronise your local main branch before copying these changes. Preserve
   existing GitOps releases, generated environment settings and image digests.
   Never upload deploy/generated credentials or Terraform state.
2. Commit the changed source, migration and tests. Run Validate platform.
   Java 21 CI must compile and pass the new inventory tests before release.
3. Run Prepare AWS release from the updated main, review and merge its GitOps PR.
4. Run the existing platform bootstrap/deployment workflow for the merged commit.
   Keep the completed database-bootstrap Job. Flyway runs V4 on inventory startup.
5. Wait for inventory and vision readiness and Argo CD sync, then publish the new
   frontend using the existing release workflow. Do not publish it against old APIs.
6. Bedrock remains optional. Enable it only through your reviewed Terraform model
   configuration and IAM permissions. An empty model ID leaves suggestions disabled.
   No additional Terraform infrastructure is required for the stock-only features.

## Acceptance checks

- Register a filter with opening quantity 10; generated QR selects the same item.
- Confirm OUT 2 without a job: balance 8. Retry the same request: still 8.
- Try OUT 9: rejected. IN 3: balance 11. Review stock activity.
- Take a reference photo; save it without movement: balance unchanged.
- Duplicate manufacturer/part number: rejected. Different part: separate product.
- Owner edits shelf/name: same QR still works. Mechanic cannot edit catalogue.
- Archiving nonzero stock is rejected. Zero-stock archive hides the item but retains
  history; restore returns it to the active catalogue.
- Unknown photos never automatically approve or mutate stock. Bedrock-disabled
  deployments still allow manual entry; enabled suggestions need human approval.
- Mobile QR PNG, printed QR and camera inbox require a real device smoke test.

## Verification for this handoff

- React TypeScript/Vite production build passed.
- 28 vision/API/QR tests passed with the real baseline encoder.
- Platform, pipeline, Kustomize and delivery tests: 126 passed, 5 skipped across
  the suite and dependency-corrected delivery rerun. The skips require configured
  external tooling or integration environments.
- Python camera connector compilation passed. Hardware was not tested.
- Java 21 inventory compilation/tests must pass in existing Validate platform CI;
  this workstation has Java 17 and a verified Java 21 download was unavailable.
- Browser automation could not run because the browser download was unavailable.
  Desktop/mobile visual and real-device acceptance checks remain required.

## Changed source

README.md; apps/web/src/{main.tsx,api.ts,stock.css};
services/inventory Java API, inventory ledger, capture verifier and tests;
services/inventory/src/main/resources/db/migration/V4__stock_catalogue.sql;
services/vision/app/{main.py,qr.py,bedrock.py}; vision QR/API tests;
edge/camera_agent.py; this guide. Existing environment manifests and infrastructure
settings are retained from main cddbd21.
