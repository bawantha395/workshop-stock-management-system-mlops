package com.stocklane.inventory.dto;

import java.math.BigDecimal;

/** Request body for a stock movement: receipt, issue, return or stock out. */
public record MovementInput(String kind,String productId,BigDecimal quantity,String jobId,String issueId,String note,String sourceCaptureId){}
