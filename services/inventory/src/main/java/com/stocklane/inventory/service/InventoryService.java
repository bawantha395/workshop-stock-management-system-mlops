package com.stocklane.inventory.service;

import com.stocklane.inventory.dto.ArchiveInput;
import com.stocklane.inventory.dto.MovementInput;
import com.stocklane.inventory.dto.ProductEdit;
import com.stocklane.inventory.dto.ProductInput;
import com.stocklane.inventory.repository.JobGateRepository;
import com.stocklane.inventory.repository.MovementRepository;
import com.stocklane.inventory.repository.OutboxRepository;
import com.stocklane.inventory.repository.ProductRepository;
import com.stocklane.inventory.exception.ConflictException;
import com.stocklane.inventory.exception.NotFoundException;
import java.math.BigDecimal;
import java.time.Duration;
import java.time.Instant;
import java.util.*;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** Stock rules: catalogue, receipts, issues, returns, job gates. SQL lives in the repositories. */
@Service
public class InventoryService {
 private final ProductRepository productRepository;private final MovementRepository movementRepository;private final JobGateRepository gateRepository;private final OutboxRepository outboxRepository;
 private final Commands commands;private final StringRedisTemplate redis;private final PeopleService people;
 public InventoryService(ProductRepository productRepository,MovementRepository movementRepository,JobGateRepository gateRepository,OutboxRepository outboxRepository,Commands c,StringRedisTemplate redis,PeopleService people){this.productRepository=productRepository;this.movementRepository=movementRepository;this.gateRepository=gateRepository;this.outboxRepository=outboxRepository;this.commands=c;this.redis=redis;this.people=people;}

 public List<Map<String,Object>> products(){return productRepository.findActive();}
 public List<Map<String,Object>> movements(){return movementRepository.findRecent();}
 public List<Map<String,Object>> jobMovements(String jobId){return movementRepository.findByJob(jobId);}
 public Map<String,Object> product(String id,boolean lock){return productRepository.findById(id,lock).orElseThrow(()->new NotFoundException("Product not found"));}
 public Map<String,Object> create(String key,ProductInput p){
  return commands.execute(key,"create-product",p,()->{
   required(p.sku(),"SKU");required(p.name(),"Name");required(p.category(),"Category");required(p.brand(),"Brand");
   if(p.unit()==null||!Set.of("UNIT","LITRE").contains(p.unit()))throw new IllegalArgumentException("Unit must be UNIT or LITRE");
   positiveOrZero(p.sellingPrice());positiveOrZero(p.reorderLevel());positiveOrZero(p.openingQuantity());
   if(p.brand().length()>100||p.category().length()>80||Objects.toString(p.grade(),"").length()>80||Objects.toString(p.capacity(),"").length()>60||Objects.toString(p.partNumber(),"").length()>180||Objects.toString(p.location(),"").length()>180)throw new IllegalArgumentException("One or more catalogue fields are too long");
   String id=UUID.randomUUID().toString();
   productRepository.insert(id,p.sku().trim().toUpperCase(),p.name().trim(),p.category(),p.brand(),Objects.toString(p.grade(),""),Objects.toString(p.capacity(),""),blankNull(p.barcode()),p.unit(),p.sellingPrice(),p.reorderLevel(),blankNull(p.imageId()),Instant.now().toString());
   productRepository.updateCatalogueKeys(id,p.brand().trim().toUpperCase(Locale.ROOT),part(p.partNumber()),Objects.toString(p.location(),""));
   if(p.openingQuantity().signum()>0)record(new MovementInput("OPENING",id,p.openingQuantity(),null,null,"Approved initial physical count",null));
   Map<String,Object> result=product(id,false);event("CATALOGUE_APPROVED",result);return result;
  });
 }
 public Map<String,Object> move(String key,MovementInput m){return commands.execute(key,"movement",m,()->record(m));}
 private Map<String,Object> record(MovementInput m){
  if(m.quantity()==null||m.quantity().signum()<=0||m.quantity().scale()>3)throw new IllegalArgumentException("Quantity must be positive, with at most 3 decimals");
  if(m.kind()==null||!Set.of("OPENING","RECEIPT","ISSUE","RETURN","STOCK_OUT").contains(m.kind()))throw new IllegalArgumentException("Unsupported movement type");
  if(m.note()!=null&&m.note().length()>500)throw new IllegalArgumentException("Note is too long");
  boolean counterReturn="RETURN".equals(m.kind())&&m.jobId()==null;
  boolean job="ISSUE".equals(m.kind())||"RETURN".equals(m.kind())&&!counterReturn;
  if(m.receiverId()!=null&&!"STOCK_OUT".equals(m.kind())&&!counterReturn)throw new IllegalArgumentException("Only a counter handover or its return names a receiver");
  String receiver="STOCK_OUT".equals(m.kind())&&m.receiverId()!=null?people.active(m.receiverId()).get("id").toString():null;
  if(job){var gate=gate(m.jobId(),true);if(!"OPEN".equals(gate.get("state")))throw new ConflictException("This job is frozen for invoicing; stock changes are blocked");}
  Map<String,Object> product=product(m.productId(),true);
  if(Boolean.TRUE.equals(product.get("archived")))throw new ConflictException("This product is archived");
  if("STOCK_OUT".equals(m.kind())&&(m.jobId()!=null||m.issueId()!=null))throw new IllegalArgumentException("Stock OUT does not use a repair job");
  if("UNIT".equals(product.get("unit"))&&m.quantity().stripTrailingZeros().scale()>0)throw new IllegalArgumentException("Sealed units require a whole number");
  BigDecimal price=(BigDecimal)product.get("selling_price");
  if("RETURN".equals(m.kind())){
   var issues=counterReturn?movementRepository.findHandover(m.issueId(),m.productId()):movementRepository.findIssue(m.issueId(),m.jobId(),m.productId());
   if(issues.isEmpty())throw new ConflictException(counterReturn?"Select the part this person received":"Select the original issue for this return");
   if(counterReturn)receiver=Objects.toString(issues.get().get("receiver_id"),null);
   var issue=issues.get();BigDecimal returned=movementRepository.returnedQuantity(m.issueId());
   if(m.quantity().add(returned).compareTo((BigDecimal)issue.get("quantity"))>0)throw new ConflictException("Return exceeds the outstanding issued quantity");
   price=(BigDecimal)issue.get("unit_price");
  }
  BigDecimal delta=Set.of("ISSUE","STOCK_OUT").contains(m.kind())?m.quantity().negate():m.quantity();
  BigDecimal balance=((BigDecimal)product.get("quantity")).add(delta);
  if(balance.signum()<0)throw new ConflictException("Insufficient stock for this issue");
  productRepository.updateQuantity(m.productId(),balance);
  String id=UUID.randomUUID().toString();
  movementRepository.insert(id,m.productId(),m.kind(),m.quantity(),price,m.jobId(),m.issueId(),Commands.actor(),Objects.toString(m.note(),""),Instant.now().toString(),receiver);
  if(job)gateRepository.incrementRevision(m.jobId());
  Map<String,Object> result=new LinkedHashMap<>(movementRepository.getById(id));result.put("sku",product.get("sku"));result.put("name",product.get("name"));result.put("unit",product.get("unit"));result.put("balance",balance);
  event("STOCK_MOVED",result);return result;
 }
 private void event(String type,Object payload){outboxRepository.insert(UUID.randomUUID().toString(),type,commands.encode(payload),Instant.now().toString());}
 private Map<String,Object> gate(String id,boolean lock){if(id==null)throw new IllegalArgumentException("A repair job is required");return gateRepository.find(id,lock).orElseThrow(()->new ConflictException("Repair job is not registered with inventory"));}
 @Transactional public Map<String,Object> openJob(String id){
  try{UUID.fromString(id);}catch(Exception e){throw new IllegalArgumentException("Invalid job ID");}
  var existing=gateRepository.find(id,false);if(existing.isPresent())return existing.get();
  gateRepository.insertOpen(id);return gate(id,false);
 }
 @Transactional public Map<String,Object> freezeJob(String id){gate(id,true);gateRepository.freeze(id);return snapshot(id);}
 public Map<String,Object> snapshot(String id){var gate=gate(id,false);var lines=movementRepository.jobSnapshotLines(id);return Map.of("jobId",id,"revision",gate.get("revision"),"state",gate.get("state"),"lines",lines);}
 public String catalogue(){String key="stocklane:catalogue:v2";try{String s=redis.opsForValue().get(key);if(s!=null)return s;}catch(Exception ignored){}
  String s=commands.encode(productRepository.catalogueRows());
  try{redis.opsForValue().set(key,s,Duration.ofSeconds(30));}catch(Exception ignored){}return s;
 }
 public Object movementById(String id){return movementRepository.findById(id).orElseThrow(()->new NotFoundException("Movement not found"));}
 /** Parts handed to one person at the counter in the last 30 days, with what is still out. */
 public List<Map<String,Object>> handovers(String receiverId){
  people.active(receiverId);
  var rows=movementRepository.handovers(receiverId,Instant.now().minus(Duration.ofDays(30)).toString());
  List<Map<String,Object>> open=new ArrayList<>();
  for(var row:rows){BigDecimal out=((BigDecimal)row.get("quantity")).subtract((BigDecimal)row.get("returned"));if(out.signum()>0){var copy=new LinkedHashMap<>(row);copy.put("outstanding",out);open.add(copy);}}
  return open;
 }
 public List<Map<String,Object>> archivedProducts(){return productRepository.findArchived();}
 public Map<String,Object> edit(String key,String id,ProductEdit p){return commands.execute(key,"edit-product:"+id,p,()->{
  product(id,true);required(p.name(),"Name");required(p.category(),"Category");required(p.brand(),"Manufacturer");positiveOrZero(p.reorderLevel());
  if(p.name().length()>180||p.brand().length()>100||p.category().length()>80||Objects.toString(p.grade(),"").length()>80||Objects.toString(p.capacity(),"").length()>60||Objects.toString(p.partNumber(),"").length()>180||Objects.toString(p.location(),"").length()>180)throw new IllegalArgumentException("One or more catalogue fields are too long");
  productRepository.updateCatalogue(id,p.name().trim(),p.category().trim(),p.brand().trim(),p.brand().trim().toUpperCase(Locale.ROOT),Objects.toString(p.grade(),""),Objects.toString(p.capacity(),""),part(p.partNumber()),Objects.toString(p.location(),""),p.reorderLevel());
  audit(id,"EDIT",p);Map<String,Object> result=product(id,false);event("CATALOGUE_APPROVED",result);return result;
 });}
 public Map<String,Object> archive(String key,String id,ArchiveInput input){return commands.execute(key,"archive-product:"+id,input,()->{
  var p=product(id,true);if(input.archived()&&((BigDecimal)p.get("quantity")).signum()!=0)throw new ConflictException("Record the physical stock OUT before archiving a product with remaining stock");
  productRepository.updateArchived(id,input.archived());audit(id,input.archived()?"ARCHIVE":"RESTORE",input);return product(id,false);
 });}
 private void audit(String id,String action,Object details){productRepository.insertAudit(UUID.randomUUID().toString(),id,Commands.actor(),action,commands.encode(details),Instant.now().toString());}
 private static String part(String p){return p==null||p.isBlank()?null:p.trim().toUpperCase(Locale.ROOT);}
 private static String blankNull(String s){return s==null||s.isBlank()?null:s.trim();}
 private static void required(String s,String label){if(s==null||s.isBlank()||s.length()>180)throw new IllegalArgumentException(label+" is required (maximum 180 characters)");}
 private static void positiveOrZero(BigDecimal n){if(n==null||n.signum()<0)throw new IllegalArgumentException("Prices and opening/reorder quantities must be zero or greater");}
}
