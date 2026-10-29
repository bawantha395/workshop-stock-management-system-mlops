# Training on real data

This guide runs the real production ML lifecycle on real, licensed data. Nothing in it is
generated, and you don't need CloudShell. Every change made to the source data is written
down here and stored with the data.

| Model | Real data | How it gets in |
|---|---|---|
| Stock forecast | UCI Online Retail II: real daily sales of a UK online retailer | **Already in the repo** at `datasets/real-data/online-retail-ii/`. Import it on the app's forecast page. |
| Photo matching | Kaggle "50 Types of Car Parts": real photos of car parts, Apache 2.0 | The workflow **Train photo model on real car-part photos** downloads it with your Kaggle API token. |

Both use the same quality gates as workshop data. If a model doesn't beat its baseline, the
pipeline rejects it, and that is a valid result.

## 1. Stock forecast: UCI Online Retail II

**Source:** Chen, D. (2012). *Online Retail II* [Dataset]. UCI Machine Learning Repository.
https://doi.org/10.24432/C5CG6D. License: **CC BY 4.0**, so credit the source when you show
it.

- **What it is.** All 1,067,371 real transactions from 2009-12-01 to 2011-12-09. The
  products are gift items, not car parts; no free, real, daily car-part sales dataset
  exists.
- **Where it came from.** The file was built from the complete copy in the CRAN package
  `onlineretail2` (github.com/allanvc/onlineretail2). Its SHA-256 is recorded in
  `ATTRIBUTION.txt`.
- **Rebuilding it.** `python3 mlops/real_data/online_retail.py` rebuilds the file directly
  from the UCI archive instead.

**What was changed in `sales-history-import.json`:**

- **Products kept.** Only product stock codes; postage, fees and manual adjustments are
  dropped.
- **Cancellations.** Each day's sales are netted with that day's cancellations, and a day
  never goes below 0.
- **Which products.** The 40 products that sold throughout the whole period, most selling
  days first.
- **Stock levels.** The source has no stock levels, so each item's **opening balance** is
  all its recorded sales plus its last 28 days of sales. That means the item was never out
  of stock in the history.
- **Dates.** The file keeps the **original dates**. When you import it, the app moves every
  date forward by **whole weeks** so the last real day becomes yesterday. Fridays stay
  Fridays, and up to 6 trailing source days are dropped so the weekday lines up. The shift
  is written into the note stored on every imported item.

**Local check (`preflight.json`):** the same forecast code SageMaker runs was run against
this data.

- **Gate passed:** 5 of the 40 items beat the weekday baseline by at least 5% with WAPE of
  60% or less, so they are served as **Trained ML**.
- **The other 35** stay on the labelled **Weekday baseline**.

**Steps:**

1. **Get the file.** Download `datasets/real-data/online-retail-ii/sales-history-import.json`
   from GitHub or from the zip.
2. **Import it.** In the app, sign in as OWNER, open **Stock report**, and at the bottom open **Bring in old sales records**. Choose the file, tick the license box and click **Bring in sales**. The importer checks everything before it writes anything:
   - SKUs must be new.
   - No sale can be dated today or later.
   - No item can sell more than its opening balance.
3. **Nothing else to prepare.** The import prepares the forecast history by itself, with the correct dates.
4. **Train.** In GitHub Actions, run **Train and publish stock forecast** for `dev`. The app
   then shows the forecasts, with **Trained ML** or **Weekday baseline** on each item.

## 2. Photo matching: Kaggle car-part photos

**Source:** Kaggle "50 Types of Car Parts" (`gpiosenka/car-parts-40-classes`). The license
shown on the dataset page is **Apache 2.0**. The images aren't stored in this repository;
the workflow downloads them each time.

**One-time setup:**

1. In Kaggle, open **Settings → API → Create New Token**. This downloads `kaggle.json`.
2. In GitHub, go to **Settings → Secrets and variables → Actions** and add two repository
   secrets:
   - `KAGGLE_USERNAME`
   - `KAGGLE_KEY`

   Copy their values from that file.

**What `mlops/real_data/car_parts_photos.py` does:**

- **Items.** Each part type becomes one stock item, `CP-<PART TYPE>`.
- **Splits.** The archive's own train/validation/test split is kept, so test photos are
  never used in training.
- **Sessions.** The photos come from many sources, so each photo is its own capture
  session.
- **Duplicates.** Byte-identical duplicates are dropped.
- **Size.** At most 20 training photos are kept per part type, which stays under the
  2,000-image limit.
- **Provenance.** The source, URL, license and archive SHA-256 go into
  `dataset-metadata.json`. That file is uploaded with the dataset and copied into the
  trained model as `trainingData`. Models trained this way are named
  `catalogue-calibrator-…`.

**Steps:**

1. **Train.** Run **Train photo model on real car-part photos** for `dev`. It does all of
   this in one run:
   - Downloads the archive and builds the dataset.
   - Runs the photo quality gate **on the runner first**: validation precision of at least
     98%, then test precision of at least 98% with recall of at least 50%.
   - Uploads the dataset.
   - Starts SageMaker only if that gate passed.

   The run summary shows the metrics.
2. **Approve.** If a model was registered, review it, then run **Review SageMaker model**
   with `Approved`.
3. **Deploy.** Run **Deploy environment** with that `model_package` ARN.
4. **Use it in the app.** Register a few part types as items with a reference photo. The
   scanner then matches new photos against those references.

The training image must include the updated training code. Run **Deploy environment** once
after pushing this change, before you train.

## What to say about it

> "The pipeline is the production one. The data is real public data with a recorded
> license, and every transformation is documented and stored with the data. The quality
> gates are unchanged: of 40 real products, 5 beat the baseline and were served as ML,
> and the rest stayed on the baseline. Only models a person approves are deployed."
