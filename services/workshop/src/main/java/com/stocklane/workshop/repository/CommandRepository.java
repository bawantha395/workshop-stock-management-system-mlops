package com.stocklane.workshop.repository;

import java.util.Map;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** Stored idempotent commands: one row per Idempotency-Key. */
@Repository
public class CommandRepository {
 private final JdbcTemplate db;
 public CommandRepository(JdbcTemplate db){this.db=db;}
 public Optional<Map<String,Object>> find(String id){
  var rows=db.queryForList("select request_hash,response from commands where id=?",id);
  return rows.isEmpty()?Optional.empty():Optional.of(rows.getFirst());
 }
 public void insert(String id,String requestHash,String createdAt){db.update("insert into commands(id,request_hash,response,created_at) values(?,?,?,?)",id,requestHash,"",createdAt);}
 public void updateResponse(String id,String response){db.update("update commands set response=? where id=?",response,id);}
}
