# Stocklane real public training data

Prepared 2026-10-27. These are real external observations and source catalogue images, not generated fixtures or your workshop records.

- `photos/`: 115 original source image files, 23 product identities, five images per identity; manifest, checksums and provenance. Eight products are in training, eight in validation and seven in test, with no product overlap across splits.
- `monthly-history/history.json`: 64 complete real anonymous car-parts series, 51 monthly observations each, January 1998–March 2002. Source missing-value series were excluded. No monthly quantity is converted to a made-up daily history.
- `monthly-history/observed-monthly-sales.csv`: the same 3,264 observed months in a readable table. This is an analytical source file, not an inventory import.
- `source-lock.json`: exact official URLs, selected IDs, SHA256 checksums, attribution and licence. One mislabelled source product was excluded after visual review.
- `real-photo-overview.png`: source photo preview, not an extra training sample.
- `photo-products.json`: source product IDs and original multilingual titles, not manufacturer fitment verification.
- `local-validation-report.json`: actual local evaluation. No AWS job was started while preparing this file. Both pooled quality gates failed; these models are not ready for live stock decisions.
- Training instructions: [docs/MLOPS.md](../../docs/MLOPS.md) (run **Deploy environment** with `train`, or **Train real-data ML models**).
- `ATTRIBUTION.md` and `LICENSE-CC-BY-4.0.txt`: source attribution and reuse terms.

The photo source is Amazon Berkeley Objects, https://registry.opendata.aws/amazon-berkeley-objects/ . Images include product sets, close-ups, marketing panels and accessories. The history source is Monash Car Parts with Missing Values, https://zenodo.org/records/4656022 , DOI 10.5281/zenodo.4656022. Both sources identify CC BY 4.0 releases. Anonymous history IDs cannot be linked to the photo ASINs or current workshop stock.

Use the new **Train real-data ML models** GitHub Actions workflow after deploying the accompanying source update. It downloads these pinned inputs automatically; no manual data ZIP upload or notebook setup is required. It creates actual SageMaker Training jobs and pending benchmark Model Registry versions in Sydney, subject to your account's permissions and quotas. It leaves live workshop models and stock unchanged.

For a production workshop model, collect real approved item photos and dated stock movements from that business, then validate on independent workshop data. Do not describe this external benchmark as trained on your brother's workshop.
