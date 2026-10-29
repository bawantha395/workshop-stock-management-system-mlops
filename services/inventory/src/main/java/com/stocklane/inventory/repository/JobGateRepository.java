package com.stocklane.inventory.repository;

import java.util.Map;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** SQL for repair-job gates: OPEN jobs accept issues, FROZEN jobs are being invoiced. */
@Repository
public class JobGateRepository {
 private final JdbcTemplate db;
 public JobGateRepository(JdbcTemplate db){this.db=db;}
 public Optional<Map<String,Object>> find(String id,boolean lock){
  var rows=db.queryForList("select * from job_gates where id=?"+(lock?" for update":""),id);
  return rows.isEmpty()?Optional.empty():Optional.of(rows.getFirst());
 }
 public void insertOpen(String id){db.update("insert into job_gates(id,state,revision) values(?,'OPEN',0)",id);}
 public void freeze(String id){db.update("update job_gates set state='FROZEN' where id=?",id);}
 public void incrementRevision(String id){db.update("update job_gates set revision=revision+1 where id=?",id);}
}
