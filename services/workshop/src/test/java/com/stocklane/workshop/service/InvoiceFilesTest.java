package com.stocklane.workshop.service;
import static org.assertj.core.api.Assertions.*;
import java.nio.file.Path;
import java.util.*;
import java.math.BigDecimal;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.apache.pdfbox.Loader;
import org.apache.pdfbox.text.PDFTextStripper;

class InvoiceFilesTest {
 @TempDir Path temp;
 Map<String,Object> details(int count){List<Map<String,Object>> lines=new ArrayList<>();for(int i=0;i<count;i++)lines.add(Map.of("sku","PART-"+i,"quantity",1,"unit","UNIT","unit_price",500));Map<String,Object> data=new HashMap<>();data.putAll(Map.of("invoice_number","INV-TEST","customer","Test Customer","vehicle","Montero","registration","TEST-0001","created_at","2026-10-25T00:00:00Z","lines",lines,"labour",1000,"total",count*500+1000,"approved_by","test-owner","revision",count));return data;}
 @Test void pdfContainsConfirmedTotal() throws Exception {var files=new InvoiceFiles();files.root=temp.toString();files.bucket="";String id=UUID.randomUUID().toString();files.write(id,details(1));byte[] bytes=files.read(id);assertThat(new String(bytes,0,4)).isEqualTo("%PDF");try(var doc=Loader.loadPDF(bytes)){assertThat(new PDFTextStripper().getText(doc)).contains("TOTAL: LKR 1500","PART-0","Test Customer");}}
 @Test void longInvoicesPaginateWithoutLosingPartsOrTotals() throws Exception {var files=new InvoiceFiles();files.root=temp.toString();files.bucket="";String id=UUID.randomUUID().toString();files.write(id,details(60));try(var doc=Loader.loadPDF(files.read(id))){assertThat(doc.getNumberOfPages()).isGreaterThan(1);assertThat(new PDFTextStripper().getText(doc)).contains("PART-59","TOTAL: LKR 31000");}}
}
