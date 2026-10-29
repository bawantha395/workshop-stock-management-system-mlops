package com.stocklane.inventory.dto;

/** Request body for preparing a stock-usage history snapshot for forecasting. */
public record ForecastSnapshotRequest(String historyFrom,boolean historyConfirmed){}
