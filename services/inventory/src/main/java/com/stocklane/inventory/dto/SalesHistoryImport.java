package com.stocklane.inventory.dto;

import java.math.BigDecimal;
import java.util.List;

/** Request body for importing real past sales (for example from a previous system or a public dataset). */
public record SalesHistoryImport(String source,String sourceUrl,String license,String note,String sourceSha256,List<Product> products){
 /** One catalogue item, its opening balance and its recorded daily sales. */
 public record Product(String sku,String name,String category,String brand,String unit,BigDecimal sellingPrice,BigDecimal reorderLevel,String openingDate,BigDecimal openingQuantity,List<DailySale> sales){}
 /** Quantity that left stock on one Asia/Colombo calendar day. */
 public record DailySale(String date,BigDecimal quantity){}
}
