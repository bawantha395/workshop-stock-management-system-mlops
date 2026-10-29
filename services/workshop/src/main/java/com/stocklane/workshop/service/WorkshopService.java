package com.stocklane.workshop.service;
import com.stocklane.workshop.exception.ConflictException;
import com.stocklane.workshop.exception.NotFoundException;
import com.stocklane.workshop.dto.InvoiceInput;
import com.stocklane.workshop.dto.JobInput;
import com.stocklane.workshop.repository.AllocationRepository;
import com.stocklane.workshop.repository.InvoiceRepository;
import com.stocklane.workshop.repository.JobRepository;
import com.stocklane.workshop.repository.ProcessedEventRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.*;
import java.time.*;
import java.util.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.web.client.RestClient;
import org.springframework.http.client.JdkClientHttpRequestFactory;

@Service
public class WorkshopService {
 private final JobRepository jobRepository;private final InvoiceRepository invoiceRepository;private final AllocationRepository allocationRepository;private final ProcessedEventRepository processedEventRepository;private final Commands commands;private final TransactionTemplate tx;private final ObjectMapper json;private final InvoiceFiles files;
 @Value("${app.inventory-url}")String inventory;@Value("${app.inventory-control-token}")String token;
 private final RestClient client;
 public WorkshopService(JobRepository jobRepository,InvoiceRepository invoiceRepository,AllocationRepository allocationRepository,ProcessedEventRepository processedEventRepository,Commands commands,org.springframework.transaction.PlatformTransactionManager tm,ObjectMapper json,InvoiceFiles files){this.jobRepository=jobRepository;this.invoiceRepository=invoiceRepository;this.allocationRepository=allocationRepository;this.processedEventRepository=processedEventRepository;this.commands=commands;this.tx=new TransactionTemplate(tm);this.json=json;this.files=files;var f=new JdkClientHttpRequestFactory(java.net.http.HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(3)).build());f.setReadTimeout(Duration.ofSeconds(8));client=RestClient.builder().requestFactory(f).build();}
 public List<Map<String,Object>> jobs(){return jobRepository.findAll();}
 public Map<String,Object> job(String id,boolean lock){return jobRepository.findById(id,lock).orElseThrow(()->new NotFoundException("Repair job not found"));}
 public Map<String,Object> create(String key,JobInput input){
  var result=commands.execute(key,"create-job",input,()->{
   for(String s:List.of(Objects.toString(input.customer(),""),Objects.toString(input.vehicle(),""),Objects.toString(input.registration(),"")))if(s.isBlank()||s.length()>180)throw new IllegalArgumentException("Customer, vehicle and registration are required");
   for(String s:List.of(input.customer(),input.vehicle(),input.registration()))if(!s.matches("[\\x20-\\x7e]+"))throw new IllegalArgumentException("Use English/Latin customer and vehicle labels for PDF invoices in this prototype");
   String id=UUID.randomUUID().toString();jobRepository.insertOpen(id,input.customer(),input.vehicle(),input.registration().toUpperCase(),Objects.toString(input.phone(),""),Objects.toString(input.summary(),""),Instant.now().toString());return job(id,false);
  });
  // Repeating the same command repairs a failed gate registration after a timeout.
  client.put().uri(inventory+"/internal/jobs/"+result.get("id")).header("X-Internal-Token",token).retrieve().toBodilessEntity();return result;
 }
 public List<Map<String,Object>> allocations(String jobId){job(jobId,false);return allocationRepository.findByJob(jobId);}
 public Map<String,Object> finalise(String id,String key,InvoiceInput input){
  if(input.labour()==null||input.labour().signum()<0||input.labour().scale()>2)throw new IllegalArgumentException("Labour must be a non-negative amount with at most 2 decimals");
  return commands.execute(key,"finalise-invoice:"+id,input,()->{
   var job=job(id,true);if(!"OPEN".equals(job.get("status")))throw new ConflictException("This job already has a final invoice");
   @SuppressWarnings("unchecked") Map<String,Object> snapshot=client.post().uri(inventory+"/internal/jobs/"+id+"/freeze").header("X-Internal-Token",token).retrieve().body(Map.class);
   if(snapshot==null||!"FROZEN".equals(snapshot.get("state")))throw new ConflictException("Could not freeze job inventory for reconciliation");
   @SuppressWarnings("unchecked") List<Map<String,Object>> lines=(List<Map<String,Object>>)snapshot.get("lines");
   BigDecimal total=input.labour();for(var l:lines)total=total.add(new BigDecimal(l.get("quantity").toString()).multiply(new BigDecimal(l.get("unit_price").toString())));
   total=total.setScale(2,RoundingMode.HALF_UP);String invoiceId=UUID.randomUUID().toString();String number="INV-"+LocalDate.now(ZoneOffset.UTC).toString().replace("-","")+"-"+invoiceId.substring(0,6).toUpperCase();
   Map<String,Object> details=new LinkedHashMap<>();details.put("id",invoiceId);details.put("invoice_number",number);details.put("job_id",id);details.put("customer",job.get("customer"));details.put("vehicle",job.get("vehicle"));details.put("registration",job.get("registration"));details.put("lines",lines);details.put("labour",input.labour());details.put("total",total);details.put("currency","LKR");details.put("approved_by",Commands.actor());details.put("created_at",Instant.now().toString());details.put("revision",snapshot.get("revision"));
   files.write(invoiceId,details);
   invoiceRepository.insert(invoiceId,id,number,commands.encode(details),input.labour(),total,Long.parseLong(snapshot.get("revision").toString()),details.get("created_at"),Commands.actor());
   jobRepository.markInvoiced(id);return details;
  });
 }
 public List<Map<String,Object>> invoices(){return invoiceRepository.findAll();}
 public byte[] pdf(String id){if(!invoiceRepository.exists(id))throw new NotFoundException("Invoice not found");return files.read(id);}
 public void consume(Map<String,Object> event){
  if(!"STOCK_MOVED".equals(event.get("type")))throw new IllegalArgumentException("Unexpected event type");
  String id=event.get("eventId").toString(),hash=commands.hash(commands.encode(event));
  try{tx.executeWithoutResult(status->{
   var seen=processedEventRepository.findById(id);if(seen.isPresent()){if(!hash.equals(seen.get().get("payload_hash")))throw new ConflictException("Event ID reused with different content");return;}
   processedEventRepository.insert(id,hash);
   @SuppressWarnings("unchecked") var p=(Map<String,Object>)event.get("payload");
   // Ordinary stock movements are acknowledged and deduplicated, but are not
   // repair-job allocations. Inventory remains the stock ledger authority.
   if(Set.of("OPENING","RECEIPT","STOCK_OUT").contains(p.get("kind")))return;
   if(!Set.of("ISSUE","RETURN").contains(p.get("kind")))throw new IllegalArgumentException("Unexpected stock movement kind");
   allocationRepository.insertFromEvent(p);
  });}catch(DuplicateKeyException duplicate){var seen=processedEventRepository.findById(id);if(seen.isEmpty()||!hash.equals(seen.get().get("payload_hash")))throw duplicate;}
 }
}
