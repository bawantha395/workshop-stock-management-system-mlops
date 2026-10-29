package com.stocklane.inventory.repository;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** Read-only report queries for the owner's stock analysis. */
@Repository
public class StockAnalysisRepository {
 private static final String FILTER=" where (?=true or p.archived=false) and lower(concat(p.name,' ',p.sku,' ',p.brand,' ',coalesce(p.part_number,''),' ',p.location)) like ? and (?='' or lower(p.category)=lower(?))";
 private final JdbcTemplate db;
 public StockAnalysisRepository(JdbcTemplate db){this.db=db;}
 /** One page (100 rows) of opening, added, taken and closing quantities between two instants. */
 public List<Map<String,Object>> summaryRows(OffsetDateTime from,OffsetDateTime until,boolean archived,String word,String category,int offset){
  String sql="select p.id,p.sku,p.name,p.brand,p.part_number,p.category,p.location,p.unit,p.archived,p.quantity as available_now,"+
   "coalesce(sum(case when cast(m.created_at as timestamp with time zone) < ? then case when m.kind in ('ISSUE','STOCK_OUT') then -m.quantity else m.quantity end else 0 end),0) as opening_quantity,"+
   "coalesce(sum(case when cast(m.created_at as timestamp with time zone) >= ? and cast(m.created_at as timestamp with time zone) < ? and m.kind in ('OPENING','RECEIPT','RETURN') then m.quantity else 0 end),0) as added_quantity,"+
   "coalesce(sum(case when cast(m.created_at as timestamp with time zone) >= ? and cast(m.created_at as timestamp with time zone) < ? and m.kind in ('ISSUE','STOCK_OUT') then m.quantity else 0 end),0) as taken_quantity,"+
   "coalesce(sum(case when cast(m.created_at as timestamp with time zone) < ? then case when m.kind in ('ISSUE','STOCK_OUT') then -m.quantity else m.quantity end else 0 end),0) as closing_quantity "+
   "from products p left join movements m on m.product_id=p.id"+FILTER+
   " group by p.id,p.sku,p.name,p.brand,p.part_number,p.category,p.location,p.unit,p.archived,p.quantity order by p.sku limit 100 offset ?";
  return db.queryForList(sql,from,from,until,from,until,until,archived,word,category,category,offset);
 }
 public Integer summaryTotal(boolean archived,String word,String category){return db.queryForObject("select count(*) from products p"+FILTER,Integer.class,archived,word,category,category);}
 /** Raw movements in a range; the service groups them by Sri Lanka date. */
 public List<Map<String,Object>> movementsBetween(OffsetDateTime from,OffsetDateTime until){
  return db.queryForList("select m.product_id,p.sku,p.name,p.unit,m.kind,m.quantity,m.created_at from movements m join products p on p.id=m.product_id where cast(m.created_at as timestamp with time zone)>=? and cast(m.created_at as timestamp with time zone)<? order by m.created_at limit 200001",from,until);
 }
}
