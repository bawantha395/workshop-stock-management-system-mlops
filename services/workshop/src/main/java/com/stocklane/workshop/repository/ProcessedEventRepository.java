package com.stocklane.workshop.repository;

import java.util.Map;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** SQL for event de-duplication: each event ID is applied once. */
@Repository
public class ProcessedEventRepository {
 private final JdbcTemplate db;
 public ProcessedEventRepository(JdbcTemplate db){this.db=db;}
 public Optional<Map<String,Object>> findById(String id){
  var rows=db.queryForList("select payload_hash from processed_events where id=?",id);
  return rows.isEmpty()?Optional.empty():Optional.of(rows.getFirst());
 }
 public void insert(String id,String payloadHash){db.update("insert into processed_events(id,payload_hash) values(?,?)",id,payloadHash);}
}
