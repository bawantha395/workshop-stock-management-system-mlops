package com.stocklane.inventory;

import com.stocklane.platform.Commands;
import com.stocklane.platform.Commands.*;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.data.redis.core.StringRedisTemplate;
import java.time.Duration;

@Service
public class Inventory {
 private final JdbcTemplate db;private final Commands commands;private final StringRedisTemplate redis;private final CaptureVerifier captures;
 public Inventory(JdbcTemplate db,Commands c,StringRedisTemplate redis,CaptureVerifier captures){this.db=db;this.commands=c;this.redis=redis;this.captures=captures;}
 public record ProductInput(String sku,String name,String category,String brand,String grade,String capacity,String barcode,String unit,BigDecimal openingQuantity,BigDecimal sellingPrice,BigDecimal reorderLevel,String imageId,String sourceCaptureId,String partNumber,String location){
  public ProductInput(String sku,String name,String category,String brand,String grade,String capacity,String barcode,String unit,BigDecimal openingQuantity,BigDecimal sellingPrice,BigDecimal reorderLevel,String imageId,String sourceCaptureId){this(sku,name,category,brand,grade,capacity,barcode,unit,openingQuantity,sellingPrice,reorderLevel,imageId,sourceCaptureId,null,null);}
 }
 public record ProductEdit(String name,String category,String brand,String grade,String capacity,String partNumber,String location,BigDecimal reorderLevel){}
 public record ArchiveInput(boolean archived){}

 public record MovementInput(String kind,String productId,BigDecimal quantity,String jobId,String issueId,String note,String sourceCaptureId){}
 public List<Map<String,Object>> products(){return db.queryForList("select * from products where archived=FALSE order by created_at desc,sku");}
 public List<Map<String,Object>> movements(){return db.queryForList("select m.*,p.sku,p.name,p.unit from movements m join products p on p.id=m.product_id order by m.created_at desc limit 200");}
 public List<Map<String,Object>> jobMovements(String jobId){return db.queryForList("select m.*,p.sku,p.name,p.unit from movements m join products p on p.id=m.product_id where m.job_id=? order by m.created_at",jobId);}
 public Map<String,Object> product(String id,boolean lock){var rows=db.queryForList("select * from products where id=?"+(lock?" for update":""),id);if(rows.isEmpty())throw new Missing("Product not found");return rows.getFirst();}
 public Map<String,Object> create(String key,ProductInput p){
  return commands.execute(key,"create-product",p,()->{
   required(p.sku(),"SKU");required(p.name(),"Name");required(p.category(),"Category");required(p.brand(),"Brand");
   if(p.unit()==null||!Set.of("UNIT","LITRE").contains(p.unit()))throw new IllegalArgumentException("Unit must be UNIT or LITRE");
   positiveOrZero(p.sellingPrice());positiveOrZero(p.reorderLevel());positiveOrZero(p.openingQuantity());
   if(p.brand().length()>100||p.category().length()>80||Objects.toString(p.grade(),"").length()>80||Objects.toString(p.capacity(),"").length()>60||Objects.toString(p.partNumber(),"").length()>180||Objects.toString(p.location(),"").length()>180)throw new IllegalArgumentException("One or more catalogue fields are too long");
   String id=UUID.randomUUID().toString();
   db.update("insert into products(id,sku,name,category,brand,grade,capacity,barcode,unit,quantity,selling_price,reorder_level,image_id,created_at) values(?,?,?,?,?,?,?,?,?,0,?,?,?,?)",id,p.sku().trim().toUpperCase(),p.name().trim(),p.category(),p.brand(),Objects.toString(p.grade(),""),Objects.toString(p.capacity(),""),blankNull(p.barcode()),p.unit(),p.sellingPrice(),p.reorderLevel(),blankNull(p.imageId()),Instant.now().toString());
   db.update("update products set manufacturer_key=?,part_number=?,location=? where id=?",p.brand().trim().toUpperCase(Locale.ROOT),part(p.partNumber()),Objects.toString(p.location(),""),id);
   if(p.sourceCaptureId()!=null&&p.openingQuantity().signum()<=0)throw new IllegalArgumentException("Confirm a positive receipt quantity for this captured item");
   if(p.openingQuantity().signum()>0)record(new MovementInput(p.sourceCaptureId()==null?"OPENING":"RECEIPT",id,p.openingQuantity(),null,null,"Approved initial physical count",p.sourceCaptureId()));
   Map<String,Object> result=product(id,false);event("CATALOGUE_APPROVED",result);return result;
  });
 }
 public Map<String,Object> move(String key,MovementInput m){return commands.execute(key,"movement",m,()->record(m));}
 private Map<String,Object> record(MovementInput m){
  if(m.quantity()==null||m.quantity().signum()<=0||m.quantity().scale()>3)throw new IllegalArgumentException("Quantity must be positive, with at most 3 decimals");
  if(m.kind()==null||!Set.of("OPENING","RECEIPT","ISSUE","RETURN","STOCK_OUT").contains(m.kind()))throw new IllegalArgumentException("Unsupported movement type");
  if(m.sourceCaptureId()!=null)try{UUID.fromString(m.sourceCaptureId());}catch(Exception e){throw new IllegalArgumentException("Invalid capture event ID");}
  captures.verify(m);
  if(m.note()!=null&&m.note().length()>500)throw new IllegalArgumentException("Note is too long");
  boolean job=Set.of("ISSUE","RETURN").contains(m.kind());
  if(job){var gate=gate(m.jobId(),true);if(!"OPEN".equals(gate.get("state")))throw new Conflict("This job is frozen for invoicing; stock changes are blocked");}
  Map<String,Object> product=product(m.productId(),true);
  if(Boolean.TRUE.equals(product.get("archived")))throw new Conflict("This product is archived");
  if("STOCK_OUT".equals(m.kind())&&(m.jobId()!=null||m.issueId()!=null))throw new IllegalArgumentException("Stock OUT does not use a repair job");
  if("UNIT".equals(product.get("unit"))&&m.quantity().stripTrailingZeros().scale()>0)throw new IllegalArgumentException("Sealed units require a whole number");
  BigDecimal price=(BigDecimal)product.get("selling_price");
  if("RETURN".equals(m.kind())){
   var issues=db.queryForList("select * from movements where id=? and kind='ISSUE' and job_id=? and product_id=?",m.issueId(),m.jobId(),m.productId());
   if(issues.isEmpty())throw new Conflict("Select the original issue for this return");
   var issue=issues.getFirst();BigDecimal returned=db.queryForObject("select coalesce(sum(quantity),0) from movements where issue_id=? and kind='RETURN'",BigDecimal.class,m.issueId());
   if(m.quantity().add(returned).compareTo((BigDecimal)issue.get("quantity"))>0)throw new Conflict("Return exceeds the outstanding issued quantity");
   price=(BigDecimal)issue.get("unit_price");
  }
  BigDecimal delta=Set.of("ISSUE","STOCK_OUT").contains(m.kind())?m.quantity().negate():m.quantity();
  BigDecimal balance=((BigDecimal)product.get("quantity")).add(delta);
  if(balance.signum()<0)throw new Conflict("Insufficient stock for this issue");
  db.update("update products set quantity=? where id=?",balance,m.productId());
  String id=UUID.randomUUID().toString();
  db.update("insert into movements(id,product_id,kind,quantity,unit_price,job_id,issue_id,actor,note,created_at,source_capture_id) values(?,?,?,?,?,?,?,?,?,?,?)",id,m.productId(),m.kind(),m.quantity(),price,m.jobId(),m.issueId(),Commands.actor(),Objects.toString(m.note(),""),Instant.now().toString(),m.sourceCaptureId());
  if(job)db.update("update job_gates set revision=revision+1 where id=?",m.jobId());
  Map<String,Object> result=new LinkedHashMap<>(db.queryForMap("select * from movements where id=?",id));result.put("sku",product.get("sku"));result.put("name",product.get("name"));result.put("unit",product.get("unit"));result.put("balance",balance);
  if(job)event("STOCK_MOVED",result);return result;
 }
 private void event(String type,Object payload){db.update("insert into outbox(id,type,payload,created_at) values(?,?,?,?)",UUID.randomUUID().toString(),type,commands.encode(payload),Instant.now().toString());}
 private Map<String,Object> gate(String id,boolean lock){if(id==null)throw new IllegalArgumentException("A repair job is required");var rows=db.queryForList("select * from job_gates where id=?"+(lock?" for update":""),id);if(rows.isEmpty())throw new Conflict("Repair job is not registered with inventory");return rows.getFirst();}
 @Transactional public Map<String,Object> openJob(String id){
  try{UUID.fromString(id);}catch(Exception e){throw new IllegalArgumentException("Invalid job ID");}
  var existing=db.queryForList("select * from job_gates where id=?",id);if(!existing.isEmpty())return existing.getFirst();
  db.update("insert into job_gates(id,state,revision) values(?,'OPEN',0)",id);return gate(id,false);
 }
 @Transactional public Map<String,Object> freezeJob(String id){gate(id,true);db.update("update job_gates set state='FROZEN' where id=?",id);return snapshot(id);}
 public Map<String,Object> snapshot(String id){var gate=gate(id,false);var lines=db.queryForList("select m.product_id,p.sku,p.name,p.unit,m.unit_price,sum(case when m.kind='ISSUE' then m.quantity else -m.quantity end) as quantity from movements m join products p on p.id=m.product_id where m.job_id=? and m.kind in ('ISSUE','RETURN') group by m.product_id,p.sku,p.name,p.unit,m.unit_price having sum(case when m.kind='ISSUE' then m.quantity else -m.quantity end)>0",id);return Map.of("jobId",id,"revision",gate.get("revision"),"state",gate.get("state"),"lines",lines);}
 public String catalogue(){String key="stocklane:catalogue:v2";try{String s=redis.opsForValue().get(key);if(s!=null)return s;}catch(Exception ignored){}
  String s=commands.encode(db.queryForList("select id,sku,name,category,brand,grade,capacity,barcode,unit,selling_price,reorder_level,image_id,part_number,location,archived from products where archived=FALSE order by sku"));
  try{redis.opsForValue().set(key,s,Duration.ofSeconds(30));}catch(Exception ignored){}return s;
 }
 public Object captureMovement(String capture){var rows=db.queryForList("select * from movements where source_capture_id=?",capture);return rows.isEmpty()?null:rows.getFirst();}
 public Object movementById(String id){var rows=db.queryForList("select * from movements where id=?",id);if(rows.isEmpty())throw new Missing("Movement not found");return rows.getFirst();}
 public List<Map<String,Object>> archivedProducts(){return db.queryForList("select * from products where archived=TRUE order by sku");}
 public Map<String,Object> edit(String key,String id,ProductEdit p){return commands.execute(key,"edit-product:"+id,p,()->{
  product(id,true);required(p.name(),"Name");required(p.category(),"Category");required(p.brand(),"Manufacturer");positiveOrZero(p.reorderLevel());
  if(p.name().length()>180||p.brand().length()>100||p.category().length()>80||Objects.toString(p.grade(),"").length()>80||Objects.toString(p.capacity(),"").length()>60||Objects.toString(p.partNumber(),"").length()>180||Objects.toString(p.location(),"").length()>180)throw new IllegalArgumentException("One or more catalogue fields are too long");
  db.update("update products set name=?,category=?,brand=?,manufacturer_key=?,grade=?,capacity=?,part_number=?,location=?,reorder_level=? where id=?",p.name().trim(),p.category().trim(),p.brand().trim(),p.brand().trim().toUpperCase(Locale.ROOT),Objects.toString(p.grade(),""),Objects.toString(p.capacity(),""),part(p.partNumber()),Objects.toString(p.location(),""),p.reorderLevel(),id);
  audit(id,"EDIT",p);Map<String,Object> result=product(id,false);event("CATALOGUE_APPROVED",result);return result;
 });}
 public Map<String,Object> archive(String key,String id,ArchiveInput input){return commands.execute(key,"archive-product:"+id,input,()->{
  var p=product(id,true);if(input.archived()&&((BigDecimal)p.get("quantity")).signum()!=0)throw new Conflict("Record the physical stock OUT before archiving a product with remaining stock");
  db.update("update products set archived=? where id=?",input.archived(),id);audit(id,input.archived()?"ARCHIVE":"RESTORE",input);return product(id,false);
 });}
 private void audit(String id,String action,Object details){db.update("insert into product_audit(id,product_id,actor,action,details,created_at) values(?,?,?,?,?,?)",UUID.randomUUID().toString(),id,Commands.actor(),action,commands.encode(details),Instant.now().toString());}
 private static String part(String p){return p==null||p.isBlank()?null:p.trim().toUpperCase(Locale.ROOT);}
 private static String blankNull(String s){return s==null||s.isBlank()?null:s.trim();}
 private static void required(String s,String label){if(s==null||s.isBlank()||s.length()>180)throw new IllegalArgumentException(label+" is required (maximum 180 characters)");}
 private static void positiveOrZero(BigDecimal n){if(n==null||n.signum()<0)throw new IllegalArgumentException("Prices and opening/reorder quantities must be zero or greater");}
}
