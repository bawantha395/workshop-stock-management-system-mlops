package com.stocklane.inventory.dto;

import java.math.BigDecimal;

/** Request body for editing catalogue details (owner only). */
public record ProductEdit(String name,String category,String brand,String grade,String capacity,String partNumber,String location,BigDecimal reorderLevel){}
