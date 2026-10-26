# Owner stock analysis

Stock analysis is visible only to owners; both report endpoints enforce OWNER
on the server. It is separate from the short recent-activity view.

## Reports

Choose start and end date/time in Asia/Colombo, item/name/SKU/part-number/shelf
search, category and whether to include archived items. Presets cover 7, 30, 90
and 365 days. Apply filters to load the report.

Each row shows counting unit, quantity at the start, added quantity, taken-out
quantity, quantity at the end and available now. Start is inclusive and end is
exclusive. Added includes initial opening counts, receipts and returns; taken
out includes standalone STOCK_OUT and legacy ISSUE. No units/litres are mixed
into a meaningless combined total.

Historical balances are reconstructed from all recorded movements, not the
Activity API's 200-row limit. Current catalogue names/categories/shelves appear
alongside those historical quantities; metadata itself is not reconstructed
as of the chosen date. Manual database quantity changes outside the ledger
cannot be inferred as historical stock movements.

Rows are paginated in groups of 100. Export this page exports the displayed
rows. Daily usage (all items) exports daily outgoing/returned quantities across
all items for the selected report period; it does not inherit item/category
filters. Its dates use Asia/Colombo. It limits output to ranges with at most
200,000 ledger movements. CSV output neutralises spreadsheet formula prefixes.

## Happy path

1. Choose a test item with an initial recorded quantity of 10.
2. Receive 5 and take out 2 within the report period.
3. Select a period starting after the initial count but before receipt, ending
   after the stock-out: start 10, added 5, taken 2, end 13, available now 13.
4. Add another receipt of 3 after that period. Re-run the same range: end stays
   13, available now becomes 16.
5. Search its SKU/part number, change category filter and test Archived.
6. Export the page and daily usage. Verify the actual movement dates and units.
7. Sign in as a mechanic: the page is absent and API access is denied.

Deploy the inventory image and let Flyway apply V5 before publishing this frontend.
The new tests cover historical boundaries, >200 movement history, Sri Lanka daily
grouping, invalid dates and mechanic denial. Java CI must pass before release.

## Demand forecasting: implemented separately

The new Forecast microservice, owner history snapshot and SageMaker training /
quality-gate / publish workflow are implemented. See [DEMAND_FORECASTING.md](DEMAND_FORECASTING.md)
for deployment and one-run operation. No model has been trained on your workshop
from this environment. With insufficient data, results are explicitly labelled
as weekday baselines or more history needed. No automatic stock changes occur.
