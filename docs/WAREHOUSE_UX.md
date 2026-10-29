# Warehouse task UI

This frontend update is based on main a8bcc0d and retains its deployed image
references, frontend release manifest and workshop-to-inventory network policy.
It uses the existing stock-first backend; no Terraform apply is required.

## Screens

- Workspace: Receive stock, Take stock out, Find an item, Count stock.
- Receiving / stock-out: scan, verify item, set quantity, add a draft line,
  review the list and confirm. Draft lines do not change stock.
- Find: searchable item cards, photos, manufacturer part numbers, available
  quantity, shelf and QR labels. No long product dropdown or similarity scores.
- Catalogue: separate owner editing, archive/restore and printable QR labels.
- Needs review: connected-camera evidence. Add a verified capture to the
  appropriate draft and confirm it alongside the other lines.
- Activity: confirmed ledger movements with actor and local date/time.
- Count stock: physical-versus-recorded comparison only. It does not save a
  count session or automatically post an adjustment. Recheck discrepancies
  with the owner before making a ledger correction.

## Scanning

A task opens a live rear-camera QR scanner. Video is decoded on the device
with jsQR and is not uploaded. It stops on the first decoded QR and releases
camera tracks when closed. A scan selects an item; it never increments a
quantity or posts stock automatically. Each deliberate scan requires its own
quantity confirmation before adding a line.

HTTPS, camera permission and a compatible phone/browser are required. A QR
photo upload and keyboard scanner/pasted QR input remain available. The optional
photo-identification route uses the existing vision API. Bedrock suggestions
appear only when the server reports that they are configured.

## Register without losing your receipt

If an incoming item is unfamiliar, identify its photo or search its part number.
Choose Register new item, review manufacturer/part/name/category/shelf, and open
More details for specification and pack description. Optional Bedrock suggestions
can prefill visible label fields when enabled.

During a receiving task a new catalogue entry always starts at zero stock.
Registration generates its QR and returns to the same task, with the new item
selected. Enter its delivered quantity and add it to the receipt. This prevents
registration and receipt confirmation from counting the same delivery twice.
Standalone catalogue registration still supports a counted opening quantity.

## Draft and retry behaviour

Receiving and stock-out have separate drafts. They survive navigation and reload
in the same browser tab, scoped to the signed-in user. They are not synced across
devices/tabs and are not an offline warehouse system. Clearing browser storage
removes local drafts; finish pending operations before doing so.

Each line receives a command ID before submission. That ID and attempted state
are saved before the HTTP request. Retries retain the ID. Confirmed movement
IDs, camera reconciliation and reference indexing are tracked separately.

A list is posted as sequential independent ledger transactions, **not one atomic
batch transaction**. If one fails, preceding lines may already be recorded.
The UI shows their results and retries unfinished work without reposting completed
movements. An uncertain attempted line stays locked. A definitively rejected
400/404/409/422 line without a movement can be removed and corrected. The server
remains authoritative for available stock and access controls.

## Deployment

1. Push the change to main and let **Validate platform** pass (it includes the
   frontend npm tests).
2. Run **Deploy environment**. Its release and frontend stages rebuild the web
   app and publish it to S3/CloudFront; refresh the website afterwards.

## Verification

- TypeScript/Vite production build and npm production dependency audit pass.
- All 8 frontend tests pass. npm test includes quantity/ledger rules and a real React DOM integration test
  with simulated API responses. It exercises draft no-write, navigation, reload,
  partial failure, stable retry keys, completed-line skipping, stock-out overdraw,
  job-free movements and physical-count comparison. Scanner tests decode a generated
  QR once, verify camera track release, check permission denial and reject any
  attempted frame upload. Camera APIs are simulated; QR decoding is real.
- These tests do not establish live AWS connectivity or camera hardware behaviour.
- A local Chromium visual run was blocked by the runtime's socket permissions.
  Real mobile camera permission, printing and responsive visual checks remain
  release acceptance steps on the deployed application.

## Acceptance

Receive two items: confirm neither quantity changes before Confirm receipt.
Confirm and check Activity. Take two units out; verify the new balance.
Add two outgoing lines for the same item; the sum must not exceed availability.
Refresh an unfinished draft: it must return under Continue where you left off.
Test camera denial: close the scanner and use photo/scanner input.
Register a new item inside a receipt: catalogue quantity must remain zero until
that receipt is confirmed. Check the generated QR identifies the same item.
A mechanic must not see owner edit/archive controls.
