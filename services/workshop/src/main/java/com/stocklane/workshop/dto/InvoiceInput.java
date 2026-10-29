package com.stocklane.workshop.dto;

import java.math.BigDecimal;

/** Request body for finalising a job invoice. */
public record InvoiceInput(BigDecimal labour){}
