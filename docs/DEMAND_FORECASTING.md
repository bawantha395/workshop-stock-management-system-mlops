# Demand forecasting

The forecast answers one question for the owner: **what should I order this week?** It estimates
how much of each item will be used in the next 30 days and compares that with what is on the shelf.

## Model

**Chronos-Bolt** (`amazon/chronos-bolt-small`, Apache-2.0), a pretrained time-series model, used
without any training. It runs on CPU in the nightly GitHub Actions job (`forecast.yml`); the
weights come from the official Hugging Face repository as `.safetensors`. It forecasts the median
daily use for 37 days.

## Data

- Source: recorded **outgoing** stock (gave out, used up), per item and day, exported nightly by
  the inventory service to S3 (`forecast/datasets/`). The export starts at the first recorded movement.
- Days when the item was out of stock are filled with the item's in-stock average.
- This is recorded use, not true demand: a customer who found the shelf empty is not counted.

## Which items get a forecast

| Situation | Result |
| --- | --- |
| Fewer than 21 usable days | `needs_more_history`: reorder-level rule |
| No use in the last 28 days | `not_moving`: forecast of zero, shown as "not being used" |
| Back-test error (WAPE) above 60 % | `unreliable`: reorder-level rule |
| Otherwise | `forecast`: used for the reorder list and Stock report |

The back-test hides the item's last 7 to 28 days (a quarter of its history), forecasts them, and
measures the error. The model never sees the days it is judged on.

## What the owner sees

- **Reorder this week** on the home page: items to order, most urgent first, with a purchase-list download.
- **Stock report**: for each item, in stock, status, how long it will last, and what to order.
- Without a forecast an item uses the reorder-level rule: at or below its reorder level (5 by default),
  order enough to reach double that level.

## Limits

- Slow, lumpy parts (one sold every few weeks) fail the back-test and fall back to the reorder level. That is intended.
- Lead time and safety stock are not modelled; the order quantity covers the next seven days.
- No stock is changed and no purchase order is placed automatically.
- Hugging Face must be reachable from the GitHub runner at 02:00. If it is not, the job fails and the previous forecast stays.
