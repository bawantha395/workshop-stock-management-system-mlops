package com.stocklane.workshop.repository;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** SQL for repair jobs. */
@Repository
public class JobRepository {
 private final JdbcTemplate db;
 public JobRepository(JdbcTemplate db){this.db=db;}
 public List<Map<String,Object>> findAll(){return db.queryForList("select * from jobs order by created_at desc");}
 public Optional<Map<String,Object>> findById(String id,boolean lock){
  var rows=db.queryForList("select * from jobs where id=?"+(lock?" for update":""),id);
  return rows.isEmpty()?Optional.empty():Optional.of(rows.getFirst());
 }
 public void insertOpen(String id,String customer,String vehicle,String registration,String phone,String summary,String createdAt){
  db.update("insert into jobs(id,customer,vehicle,registration,phone,summary,status,created_at) values(?,?,?,?,?,?,'OPEN',?)",id,customer,vehicle,registration,phone,summary,createdAt);
 }
 public void markInvoiced(String id){db.update("update jobs set status='INVOICED' where id=?",id);}
}
