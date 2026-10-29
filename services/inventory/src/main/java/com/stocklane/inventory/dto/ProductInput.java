package com.stocklane.inventory.dto;

import java.math.BigDecimal;

/** Request body for registering a catalogue item with its opening count. */
public record ProductInput(String sku,String name,String category,String brand,String grade,String capacity,String barcode,String unit,BigDecimal openingQuantity,BigDecimal sellingPrice,BigDecimal reorderLevel,String imageId,String sourceCaptureId,String partNumber,String location){
 public ProductInput(String sku,String name,String category,String brand,String grade,String capacity,String barcode,String unit,BigDecimal openingQuantity,BigDecimal sellingPrice,BigDecimal reorderLevel,String imageId,String sourceCaptureId){this(sku,name,category,brand,grade,capacity,barcode,unit,openingQuantity,sellingPrice,reorderLevel,imageId,sourceCaptureId,null,null);}
}
