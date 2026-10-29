package com.stocklane.inventory.dto;

import java.math.BigDecimal;

/**
 * Request body for a stock movement: receipt, issue, return or stock out.
 * receiverId names the person who received a part at the storeroom counter (stock out),
 * and a return without a repair job takes back such a counter handover (issueId).
 */
public record MovementInput(String kind,String productId,BigDecimal quantity,String jobId,String issueId,String note,String receiverId){}
