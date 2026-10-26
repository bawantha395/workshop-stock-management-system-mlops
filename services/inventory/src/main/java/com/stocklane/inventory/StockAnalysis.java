package com.stocklane.inventory;

import java.time.*;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

@Service
public class StockAnalysis {
 private final JdbcTemplate db;
 public StockAnalysis(JdbcTemplate db){this.db=db;}
 private Instant[] bounds(String from,String until){
  Instant start,end;try{start=Instant.parse(from);end=Instant.parse(until);}catch(DateTimeException error){throw new IllegalArgumentException("Use valid ISO date/time bounds");}
  if(!start.isBefore(end))throw new IllegalArgumentException("End time must follow start time");
  if(Duration.between(start,end).toDays()>3660)throw new IllegalArgumentException("Choose a range of ten years or less");
  return new Instant[]{start,end};
 }
 private OffsetDateTime utc(Instant value){return value.atOffset(ZoneOffset.UTC);}
 @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ)
 public Map<String,Object> summary(String from,String until,String search,String category,boolean archived,int page){
  var range=bounds(from,until);if(page<0||page>100000)throw new IllegalArgumentException("Invalid page");
  String filter=" where (?=true or p.archived=false) and lower(concat(p.name,' ',p.sku,' ',p.brand,' ',coalesce(p.part_number,''),' ',p.location)) like ? and (?='' or lower(p.category)=lower(?))";
  String word="%"+Objects.toString(search,"").trim().toLowerCase(Locale.ROOT).replace("\\","\\\\").replace("%","\\%").replace("_","\\_")+"%";
  String cat=Objects.toString(category,"").trim();
  String sql="select p.id,p.sku,p.name,p.brand,p.part_number,p.category,p.location,p.unit,p.archived,p.quantity as available_now,"+
   "coalesce(sum(case when cast(m.created_at as timestamp with time zone) < ? then case when m.kind in ('ISSUE','STOCK_OUT') then -m.quantity else m.quantity end else 0 end),0) as opening_quantity,"+
   "coalesce(sum(case when cast(m.created_at as timestamp with time zone) >= ? and cast(m.created_at as timestamp with time zone) < ? and m.kind in ('OPENING','RECEIPT','RETURN') then m.quantity else 0 end),0) as added_quantity,"+
   "coalesce(sum(case when cast(m.created_at as timestamp with time zone) >= ? and cast(m.created_at as timestamp with time zone) < ? and m.kind in ('ISSUE','STOCK_OUT') then m.quantity else 0 end),0) as taken_quantity,"+
   "coalesce(sum(case when cast(m.created_at as timestamp with time zone) < ? then case when m.kind in ('ISSUE','STOCK_OUT') then -m.quantity else m.quantity end else 0 end),0) as closing_quantity "+
   "from products p left join movements m on m.product_id=p.id"+filter+
   " group by p.id,p.sku,p.name,p.brand,p.part_number,p.category,p.location,p.unit,p.archived,p.quantity order by p.sku limit 100 offset ?";
  var rows=db.queryForList(sql,utc(range[0]),utc(range[0]),utc(range[1]),utc(range[0]),utc(range[1]),utc(range[1]),archived,word,cat,cat,page*100);
  var total=db.queryForObject("select count(*) from products p"+filter,Integer.class,archived,word,cat,cat);
  return Map.of("rows",rows,"total",total,"page",page,"pageSize",100,"from",range[0].toString(),"until",range[1].toString(),"asOf",Instant.now().toString());
 }
 @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ)
 public List<Map<String,Object>> daily(String from,String until){
  var range=bounds(from,until);
  // Group in Asia/Colombo without relying on a database/server timezone setting.
  var raw=db.queryForList("select m.product_id,p.sku,p.name,p.unit,m.kind,m.quantity,m.created_at from movements m join products p on p.id=m.product_id where cast(m.created_at as timestamp with time zone)>=? and cast(m.created_at as timestamp with time zone)<? order by m.created_at limit 200001",utc(range[0]),utc(range[1]));
  if(raw.size()>200000)throw new IllegalArgumentException("Choose a shorter range for daily export");
  Map<String,Map<String,Object>> result=new TreeMap<>();
  for(var row:raw){String date=Instant.parse(row.get("created_at").toString()).atZone(ZoneId.of("Asia/Colombo")).toLocalDate().toString();String key=date+":"+row.get("product_id");
   var day=result.computeIfAbsent(key,k->{Map<String,Object> d=new LinkedHashMap<>();d.put("date",date);for(String name:List.of("product_id","sku","name","unit"))d.put(name,row.get(name));d.put("out_quantity",java.math.BigDecimal.ZERO);d.put("return_quantity",java.math.BigDecimal.ZERO);return d;});
   String kind=row.get("kind").toString();String field=Set.of("ISSUE","STOCK_OUT").contains(kind)?"out_quantity":("RETURN".equals(kind)?"return_quantity":null);
   if(field!=null)day.put(field,((java.math.BigDecimal)day.get(field)).add((java.math.BigDecimal)row.get("quantity")));
  }
  return new ArrayList<>(result.values());
 }
}
