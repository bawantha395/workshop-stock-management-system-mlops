package com.stocklane.workshop.service;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.apache.pdfbox.pdmodel.*;
import org.apache.pdfbox.pdmodel.font.*;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.core.sync.RequestBody;

@Component
public class InvoiceFiles {
 @Value("${app.files-root}")String root;@Value("${app.media-bucket}")String bucket;
 public void write(String id,Map<String,Object> details){
  try(PDDocument doc=new PDDocument();ByteArrayOutputStream bytes=new ByteArrayOutputStream()){
    List<String> rows=new ArrayList<>();rows.add(details.get("invoice_number")+" | "+details.get("created_at"));rows.add("Customer: "+details.get("customer"));rows.add("Vehicle: "+details.get("vehicle")+" | "+details.get("registration"));rows.add(" ");
    @SuppressWarnings("unchecked") var lines=(List<Map<String,Object>>)details.get("lines");
    for(var line:lines)rows.add(line.get("sku")+" | "+line.get("quantity")+" "+line.get("unit")+" x LKR "+line.get("unit_price"));
    rows.add(" ");rows.add("Labour: LKR "+details.get("labour"));rows.add("TOTAL: LKR "+details.get("total"));rows.add("Approved by: "+details.get("approved_by"));rows.add("Inventory revision: "+details.get("revision"));
    List<String> wrapped=new ArrayList<>();for(String row:rows){String clean=row.replaceAll("[^\\x20-\\x7e]","?");while(clean.length()>84){wrapped.add(clean.substring(0,84));clean=clean.substring(84);}wrapped.add(clean);}
    for(int offset=0;offset<wrapped.size();offset+=27){
     PDPage page=new PDPage();doc.addPage(page);
     try(var out=new PDPageContentStream(doc,page)){
      out.beginText();out.setFont(new PDType1Font(Standard14Fonts.FontName.HELVETICA_BOLD),20);out.newLineAtOffset(45,750);out.showText("WORKSHOP SERVICE INVOICE");out.endText();
      int y=705;for(String row:wrapped.subList(offset,Math.min(offset+27,wrapped.size()))){out.beginText();out.setFont(new PDType1Font(Standard14Fonts.FontName.HELVETICA),11);out.newLineAtOffset(45,y);out.showText(row);out.endText();y-=23;}
      out.beginText();out.setFont(new PDType1Font(Standard14Fonts.FontName.HELVETICA),9);out.newLineAtOffset(45,35);out.showText("Page "+(offset/27+1));out.endText();
     }
    }
   doc.save(bytes);byte[] data=bytes.toByteArray();
   if(!bucket.isBlank()){try(var s3=S3Client.create()){s3.putObject(b->b.bucket(bucket).key("invoices/"+id+".pdf").contentType("application/pdf"),RequestBody.fromBytes(data));}}
   else{Path dir=Path.of(root).toAbsolutePath();Files.createDirectories(dir);Path temp=Files.createTempFile(dir,"invoice-",".tmp");Files.write(temp,data);Files.move(temp,dir.resolve(id+".pdf"),StandardCopyOption.REPLACE_EXISTING,StandardCopyOption.ATOMIC_MOVE);}
  }catch(IOException e){throw new IllegalStateException("Invoice PDF could not be stored",e);}
 }
 public byte[] read(String id){try{UUID.fromString(id);if(!bucket.isBlank()){try(var s3=S3Client.create()){return s3.getObjectAsBytes(b->b.bucket(bucket).key("invoices/"+id+".pdf")).asByteArray();}}return Files.readAllBytes(Path.of(root).resolve(id+".pdf"));}catch(IOException e){throw new IllegalStateException("Invoice PDF is temporarily unavailable",e);}}
}
