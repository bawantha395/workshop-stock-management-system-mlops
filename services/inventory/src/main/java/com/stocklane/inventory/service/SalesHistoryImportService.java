package com.stocklane.inventory.service;

import com.stocklane.inventory.dto.SalesHistoryImport;
import com.stocklane.inventory.exception.ConflictException;
import com.stocklane.inventory.repository.MovementRepository;
import com.stocklane.inventory.repository.ProductRepository;
import java.math.BigDecimal;
import java.time.*;
import java.util.*;
import org.springframework.stereotype.Service;

/**
 * Owner import of real past sales: new catalogue items, an opening balance and one
 * STOCK_OUT per sales day, all with their original (Asia/Colombo) dates and a recorded source.
 * Everything is validated before the first write, and the whole import is one idempotent command.
 * Imported rows are history, not live stock activity, so no outbox events are emitted
 * (imported items carry no reference photo for the vision service to index).
 */
@Service
public class SalesHistoryImportService {
 static final ZoneId ZONE=ZoneId.of("Asia/Colombo");
 static final int MAX_PRODUCTS=200,MAX_DAYS=1096,MAX_ROWS=60000;
 private final ProductRepository products;private final MovementRepository movements;private final Commands commands;
 public SalesHistoryImportService(ProductRepository products,MovementRepository movements,Commands commands){this.products=products;this.movements=movements;this.commands=commands;}

 public Map<String,Object> importHistory(String key,SalesHistoryImport body){return commands.execute(key,"import-sales-history",body,()->apply(body,LocalDate.now(ZONE)));}

 Map<String,Object> apply(SalesHistoryImport body,LocalDate today){
  if(body==null)throw new IllegalArgumentException("Upload a sales history file");
  text(body.source(),"Source",180);text(body.license(),"License",80);
  if(body.sourceUrl()!=null&&(body.sourceUrl().length()>300||!body.sourceUrl().startsWith("https://")))throw new IllegalArgumentException("Source URL must be an https link (maximum 300 characters)");
  if(body.note()!=null&&body.note().length()>1000)throw new IllegalArgumentException("Import note is too long");
  if(body.sourceSha256()!=null&&!body.sourceSha256().matches("[0-9a-f]{64}"))throw new IllegalArgumentException("Source checksum must be a SHA-256 hex digest");
  var items=body.products();
  if(items==null||items.isEmpty()||items.size()>MAX_PRODUCTS)throw new IllegalArgumentException("Import 1 to "+MAX_PRODUCTS+" items at a time");
  LocalDate yesterday=today.minusDays(1),earliest=today.minusDays(MAX_DAYS);
  Set<String> skus=new HashSet<>();int rows=0;LocalDate first=null,last=null;
  for(var p:items){
   if(p==null)throw new IllegalArgumentException("Empty item in import");
   String sku=sku(p.sku());
   if(!skus.add(sku))throw new IllegalArgumentException("SKU "+sku+" appears twice in the import");
   if(products.skuExists(sku))throw new ConflictException("SKU "+sku+" already exists; history can only be imported for new items");
   text(p.name(),"Name",180);text(p.category(),"Category",80);text(p.brand(),"Brand",100);
   if(p.unit()==null||!Set.of("UNIT","LITRE").contains(p.unit()))throw new IllegalArgumentException("Unit must be UNIT or LITRE");
   zeroOrMore(p.sellingPrice(),"Selling price");zeroOrMore(p.reorderLevel(),"Reorder level");
   LocalDate opening=date(p.openingDate(),"Opening date");
   if(opening.isBefore(earliest)||!opening.isBefore(yesterday))throw new IllegalArgumentException(sku+": opening date must be within the last three years and before yesterday");
   quantity(p.openingQuantity(),p.unit(),sku+" opening quantity");
   if(p.sales()==null||p.sales().size()>MAX_DAYS)throw new IllegalArgumentException(sku+": include at most "+MAX_DAYS+" sales days");
   LocalDate previous=opening;BigDecimal total=BigDecimal.ZERO;
   for(var sale:p.sales()){
    if(sale==null)throw new IllegalArgumentException(sku+": empty sales row");
    LocalDate day=date(sale.date(),sku+" sales date");
    if(!day.isAfter(previous))throw new IllegalArgumentException(sku+": sales dates must be after the opening date, ascending and unique");
    if(day.isAfter(yesterday))throw new IllegalArgumentException(sku+": sales must end by yesterday; today's partial day is not history");
    quantity(sale.quantity(),p.unit(),sku+" sales quantity");total=total.add(sale.quantity());previous=day;
   }
   if(total.compareTo(p.openingQuantity())>0)throw new IllegalArgumentException(sku+": recorded sales exceed the opening balance");
   rows+=p.sales().size()+1;if(rows>MAX_ROWS)throw new IllegalArgumentException("Import at most "+MAX_ROWS+" history rows at a time");
   first=first==null||opening.isBefore(first)?opening:first;last=last==null||previous.isAfter(last)?previous:last;
  }
  String actor=Commands.actor(),now=Instant.now().toString();
  String note=limit("Imported history: "+body.source()+" ("+body.license()+")",500);
  Map<String,Object> provenance=new LinkedHashMap<>();provenance.put("source",body.source());provenance.put("sourceUrl",body.sourceUrl());provenance.put("license",body.license());provenance.put("note",body.note());provenance.put("sourceSha256",body.sourceSha256());
  List<Object[]> history=new ArrayList<>();
  for(var p:items){
   String id=UUID.randomUUID().toString(),sku=sku(p.sku()),opened=noon(LocalDate.parse(p.openingDate()));
   products.insert(id,sku,p.name().trim(),p.category().trim(),p.brand().trim(),"","",null,p.unit(),p.sellingPrice(),p.reorderLevel(),null,opened);
   products.updateCatalogueKeys(id,p.brand().trim().toUpperCase(Locale.ROOT),null,"");
   history.add(new Object[]{UUID.randomUUID().toString(),id,"OPENING",p.openingQuantity(),p.sellingPrice(),actor,limit("Opening balance for imported history ("+body.source()+")",500),opened});
   BigDecimal balance=p.openingQuantity();
   for(var sale:p.sales()){history.add(new Object[]{UUID.randomUUID().toString(),id,"STOCK_OUT",sale.quantity(),p.sellingPrice(),actor,note,noon(LocalDate.parse(sale.date()))});balance=balance.subtract(sale.quantity());}
   products.updateQuantity(id,balance);
   products.insertAudit(UUID.randomUUID().toString(),id,actor,"IMPORT",commands.encode(provenance),now);
  }
  movements.insertImported(history);
  Map<String,Object> result=new LinkedHashMap<>();
  result.put("products",items.size());result.put("movements",history.size());
  result.put("trackingFrom",first.plusDays(1).toString());result.put("lastSalesDay",last.toString());
  result.put("message","Imported "+items.size()+" items and "+history.size()+" history rows. Prepare forecast history from "+first.plusDays(1)+".");
  return result;
 }
 private static String noon(LocalDate day){return day.atTime(12,0).atZone(ZONE).toInstant().toString();}
 private static String sku(String s){
  String sku=s==null?"":s.trim().toUpperCase(Locale.ROOT);
  if(!sku.matches("[A-Z0-9][A-Z0-9._-]{0,79}"))throw new IllegalArgumentException("SKU must be 1-80 letters, digits, dot, dash or underscore");
  return sku;
 }
 private static LocalDate date(String s,String label){try{return LocalDate.parse(s);}catch(Exception e){throw new IllegalArgumentException(label+" must be an ISO date (YYYY-MM-DD)");}}
 private static void text(String s,String label,int max){if(s==null||s.isBlank()||s.length()>max)throw new IllegalArgumentException(label+" is required (maximum "+max+" characters)");}
 private static void zeroOrMore(BigDecimal n,String label){if(n==null||n.signum()<0||n.scale()>2&&n.stripTrailingZeros().scale()>2)throw new IllegalArgumentException(label+" must be zero or greater, with at most 2 decimals");}
 private static void quantity(BigDecimal n,String unit,String label){
  if(n==null||n.signum()<=0||n.stripTrailingZeros().scale()>3)throw new IllegalArgumentException(label+" must be positive, with at most 3 decimals");
  if("UNIT".equals(unit)&&n.stripTrailingZeros().scale()>0)throw new IllegalArgumentException(label+" must be a whole number for sealed units");
 }
 private static String limit(String s,int max){return s.length()<=max?s:s.substring(0,max);}
}
