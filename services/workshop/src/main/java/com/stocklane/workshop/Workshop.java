package com.stocklane.workshop;
import com.stocklane.platform.Commands;
import com.stocklane.platform.Commands.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.*;
import java.time.*;
import java.util.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.web.client.RestClient;
import org.springframework.http.client.JdkClientHttpRequestFactory;

@Service
public class Workshop {
 private final JdbcTemplate db;private final Commands commands;private final TransactionTemplate tx;private final ObjectMapper json;private final InvoiceFiles files;
 @Value("${app.inventory-url}")String inventory;@Value("${app.inventory-control-token}")String token;
 private final RestClient client;
 public Workshop(JdbcTemplate db,Commands commands,org.springframework.transaction.PlatformTransactionManager tm,ObjectMapper json,InvoiceFiles files){this.db=db;this.commands=commands;this.tx=new TransactionTemplate(tm);this.json=json;this.files=files;var f=new JdkClientHttpRequestFactory(java.net.http.HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(3)).build());f.setReadTimeout(Duration.ofSeconds(8));client=RestClient.builder().requestFactory(f).build();}
 public record JobInput(String customer,String vehicle,String registration,String phone,String summary){}
 public record InvoiceInput(BigDecimal labour){}
 public List<Map<String,Object>> jobs(){return db.queryForList("select * from jobs order by created_at desc");}
 public Map<String,Object> job(String id,boolean lock){var rows=db.queryForList("select * from jobs where id=?"+(lock?" for update":""),id);if(rows.isEmpty())throw new Missing("Repair job not found");return rows.getFirst();}
 public Map<String,Object> create(String key,JobInput input){
  var result=commands.execute(key,"create-job",input,()->{
   for(String s:List.of(Objects.toString(input.customer(),""),Objects.toString(input.vehicle(),""),Objects.toString(input.registration(),"")))if(s.isBlank()||s.length()>180)throw new IllegalArgumentException("Customer, vehicle and registration are required");
   for(String s:List.of(input.customer(),input.vehicle(),input.registration()))if(!s.matches("[\\x20-\\x7e]+"))throw new IllegalArgumentException("Use English/Latin customer and vehicle labels for PDF invoices in this prototype");
   String id=UUID.randomUUID().toString();db.update("insert into jobs(id,customer,vehicle,registration,phone,summary,status,created_at) values(?,?,?,?,?,?,'OPEN',?)",id,input.customer(),input.vehicle(),input.registration().toUpperCase(),Objects.toString(input.phone(),""),Objects.toString(input.summary(),""),Instant.now().toString());return job(id,false);
  });
  // Repeating the same command repairs a failed gate registration after a timeout.
  client.put().uri(inventory+"/internal/jobs/"+result.get("id")).header("X-Internal-Token",token).retrieve().toBodilessEntity();return result;
 }
 public List<Map<String,Object>> allocations(String jobId){job(jobId,false);return db.queryForList("select * from allocations where job_id=? order by created_at",jobId);}
 public Map<String,Object> finalise(String id,String key,InvoiceInput input){
  if(input.labour()==null||input.labour().signum()<0||input.labour().scale()>2)throw new IllegalArgumentException("Labour must be a non-negative amount with at most 2 decimals");
  return commands.execute(key,"finalise-invoice:"+id,input,()->{
   var job=job(id,true);if(!"OPEN".equals(job.get("status")))throw new Conflict("This job already has a final invoice");
   @SuppressWarnings("unchecked") Map<String,Object> snapshot=client.post().uri(inventory+"/internal/jobs/"+id+"/freeze").header("X-Internal-Token",token).retrieve().body(Map.class);
   if(snapshot==null||!"FROZEN".equals(snapshot.get("state")))throw new Conflict("Could not freeze job inventory for reconciliation");
   @SuppressWarnings("unchecked") List<Map<String,Object>> lines=(List<Map<String,Object>>)snapshot.get("lines");
   BigDecimal total=input.labour();for(var l:lines)total=total.add(new BigDecimal(l.get("quantity").toString()).multiply(new BigDecimal(l.get("unit_price").toString())));
   total=total.setScale(2,RoundingMode.HALF_UP);String invoiceId=UUID.randomUUID().toString();String number="INV-"+LocalDate.now(ZoneOffset.UTC).toString().replace("-","")+"-"+invoiceId.substring(0,6).toUpperCase();
   Map<String,Object> details=new LinkedHashMap<>();details.put("id",invoiceId);details.put("invoice_number",number);details.put("job_id",id);details.put("customer",job.get("customer"));details.put("vehicle",job.get("vehicle"));details.put("registration",job.get("registration"));details.put("lines",lines);details.put("labour",input.labour());details.put("total",total);details.put("currency","LKR");details.put("approved_by",Commands.actor());details.put("created_at",Instant.now().toString());details.put("revision",snapshot.get("revision"));
   files.write(invoiceId,details);
   db.update("insert into invoices(id,job_id,invoice_number,snapshot,labour,total,revision,created_at,approved_by) values(?,?,?,?,?,?,?,?,?)",invoiceId,id,number,commands.encode(details),input.labour(),total,Long.parseLong(snapshot.get("revision").toString()),details.get("created_at"),Commands.actor());
   db.update("update jobs set status='INVOICED' where id=?",id);return details;
  });
 }
 public List<Map<String,Object>> invoices(){return db.queryForList("select id,job_id,invoice_number,labour,total,revision,created_at,approved_by from invoices order by created_at desc");}
 public byte[] pdf(String id){var rows=db.queryForList("select id from invoices where id=?",id);if(rows.isEmpty())throw new Missing("Invoice not found");return files.read(id);}
 public void consume(Map<String,Object> event){
  if(!"STOCK_MOVED".equals(event.get("type")))throw new IllegalArgumentException("Unexpected event type");
  String id=event.get("eventId").toString(),hash=commands.hash(commands.encode(event));
  try{tx.executeWithoutResult(status->{
   var seen=db.queryForList("select payload_hash from processed_events where id=?",id);if(!seen.isEmpty()){if(!hash.equals(seen.getFirst().get("payload_hash")))throw new Conflict("Event ID reused with different content");return;}
   db.update("insert into processed_events(id,payload_hash) values(?,?)",id,hash);
   @SuppressWarnings("unchecked") var p=(Map<String,Object>)event.get("payload");
   db.update("insert into allocations(id,job_id,product_id,sku,name,unit,kind,quantity,unit_price,issue_id,created_at) values(?,?,?,?,?,?,?,?,?,?,?)",p.get("id"),p.get("job_id"),p.get("product_id"),p.get("sku"),p.get("name"),p.get("unit"),p.get("kind"),new BigDecimal(p.get("quantity").toString()),new BigDecimal(p.get("unit_price").toString()),p.get("issue_id"),p.get("created_at"));
  });}catch(DuplicateKeyException duplicate){var seen=db.queryForList("select payload_hash from processed_events where id=?",id);if(seen.isEmpty()||!hash.equals(seen.getFirst().get("payload_hash")))throw duplicate;}
 }
}
