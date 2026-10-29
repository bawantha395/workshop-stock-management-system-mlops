package com.stocklane.inventory.repository;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** SQL for the people who receive parts at the storeroom counter. */
@Repository
public class PersonRepository {
 private final JdbcTemplate db;
 public PersonRepository(JdbcTemplate db){this.db=db;}
 public List<Map<String,Object>> findActive(){return db.queryForList("select id,name from people where active=TRUE order by name");}
 public Optional<Map<String,Object>> findById(String id){
  var rows=db.queryForList("select id,name,active from people where id=?",id);
  return rows.isEmpty()?Optional.empty():Optional.of(rows.getFirst());
 }
 public boolean nameExists(String name){return db.queryForObject("select count(*) from people where lower(name)=lower(?)",Integer.class,name)>0;}
 public void insert(String id,String name,String createdAt){db.update("insert into people(id,name,active,created_at) values(?,?,TRUE,?)",id,name,createdAt);}
 public void deactivate(String id){db.update("update people set active=FALSE where id=?",id);}
}
