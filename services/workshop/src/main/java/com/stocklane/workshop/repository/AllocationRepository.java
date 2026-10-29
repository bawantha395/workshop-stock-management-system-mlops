package com.stocklane.workshop.repository;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** SQL for stock allocations projected from inventory events. */
@Repository
public class AllocationRepository {
 private final JdbcTemplate db;
 public AllocationRepository(JdbcTemplate db){this.db=db;}
 public List<Map<String,Object>> findByJob(String jobId){return db.queryForList("select * from allocations where job_id=? order by created_at",jobId);}
 /** Stores one ISSUE or RETURN movement from an inventory event payload. */
 public void insertFromEvent(Map<String,Object> p){
  db.update("insert into allocations(id,job_id,product_id,sku,name,unit,kind,quantity,unit_price,issue_id,created_at) values(?,?,?,?,?,?,?,?,?,?,?)",p.get("id"),p.get("job_id"),p.get("product_id"),p.get("sku"),p.get("name"),p.get("unit"),p.get("kind"),new BigDecimal(p.get("quantity").toString()),new BigDecimal(p.get("unit_price").toString()),p.get("issue_id"),p.get("created_at"));
 }
}
