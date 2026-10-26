package com.stocklane.inventory;

import java.time.*;
import java.math.BigDecimal;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.*;

/** Uses the whole ledger and only complete Asia/Colombo days. Never fabricates history. */
@Service
public class ForecastHistory {
 private final JdbcTemplate db;
 public ForecastHistory(JdbcTemplate db){this.db=db;}
 @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ)
 public Map<String,Object> snapshot(String from,boolean confirmed,String actor){
  if(!confirmed)throw new IllegalArgumentException("Confirm complete stock tracking for the selected history period");
  LocalDate start;try{if(from==null)throw new DateTimeException("missing");start=LocalDate.parse(from);}catch(DateTimeException e){throw new IllegalArgumentException("Use a valid history start date");}
  ZoneId zone=ZoneId.of("Asia/Colombo");Instant asOf=Instant.now();LocalDate until=asOf.atZone(zone).toLocalDate();
  if(start.isAfter(until)||start.isBefore(until.minusDays(1095)))throw new IllegalArgumentException("Choose a history start on or before today, within three years");
  var products=db.queryForList("select id,sku,name,unit,quantity,created_at from products where archived=false order by id limit 1001");
  if(products.size()>1000)throw new IllegalArgumentException("Forecast export supports at most 1000 active items");
  var movements=db.queryForList("select product_id,kind,quantity,created_at from movements order by created_at limit 200001");
  if(movements.size()>200000)throw new IllegalArgumentException("Forecast export exceeds 200000 movements; archive/export offline history first");
  Map<String,Map<LocalDate,BigDecimal[]>> days=new HashMap<>();Map<String,BigDecimal> totals=new HashMap<>();
  for(var m:movements){
   String id=m.get("product_id").toString(),kind=m.get("kind").toString();Instant instant=Instant.parse(m.get("created_at").toString());
   if(instant.isAfter(asOf))throw new IllegalArgumentException("Future dated movements must be corrected before forecasting");
   boolean outgoing=Set.of("ISSUE","STOCK_OUT").contains(kind);
   if(!outgoing&&!Set.of("OPENING","RECEIPT","RETURN").contains(kind))throw new IllegalArgumentException("Unknown movement kind in history");
   BigDecimal amount=(BigDecimal)m.get("quantity"),delta=outgoing?amount.negate():amount;
   totals.merge(id,delta,BigDecimal::add);
   var day=days.computeIfAbsent(id,k->new TreeMap<>()).computeIfAbsent(instant.atZone(zone).toLocalDate(),k->new BigDecimal[]{BigDecimal.ZERO,BigDecimal.ZERO});
   day[0]=day[0].add(delta);if(outgoing)day[1]=day[1].add(amount);
  }
  List<Map<String,Object>> rows=new ArrayList<>();
  for(var p:products){
   String id=p.get("id").toString();
   if(((BigDecimal)p.get("quantity")).compareTo(totals.getOrDefault(id,BigDecimal.ZERO))!=0)throw new IllegalArgumentException("Ledger and available stock differ; reconcile stock before forecasting");
   LocalDate registered=Instant.parse(p.get("created_at").toString()).atZone(zone).toLocalDate().plusDays(1);
   LocalDate first=registered.isAfter(start)?registered:start;if(first.isAfter(until))first=until;
   var history=days.getOrDefault(id,Map.of());BigDecimal balance=BigDecimal.ZERO;
   for(var entry:history.entrySet())if(entry.getKey().isBefore(first))balance=balance.add(entry.getValue()[0]);
   List<BigDecimal> usage=new ArrayList<>();List<Boolean> inStock=new ArrayList<>();
   for(LocalDate day=first;day.isBefore(until);day=day.plusDays(1)){
    var movement=history.getOrDefault(day,new BigDecimal[]{BigDecimal.ZERO,BigDecimal.ZERO});
    boolean available=balance.signum()>0;balance=balance.add(movement[0]);
    usage.add(movement[1]);inStock.add(available&&balance.signum()>0);
   }
   Map<String,Object> row=new LinkedHashMap<>();for(String key:List.of("id","sku","name","unit"))row.put(key,p.get(key));
   row.put("start",first.toString());row.put("usage",usage);row.put("inStock",inStock);rows.add(row);
  }
  return Map.of("schemaVersion",1,"timezone","Asia/Colombo","historyConfirmed",true,"historyFrom",start.toString(),"historyUntil",until.toString(),"asOf",asOf.toString(),"confirmedBy",actor,"products",rows);
 }
}
