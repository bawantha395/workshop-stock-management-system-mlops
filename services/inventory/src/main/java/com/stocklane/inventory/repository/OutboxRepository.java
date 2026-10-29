package com.stocklane.inventory.repository;

import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** SQL for the transactional outbox: events are written with the business change, then relayed. */
@Repository
public class OutboxRepository {
 private final JdbcTemplate db;
 public OutboxRepository(JdbcTemplate db){this.db=db;}
 public void insert(String id,String type,String payload,String createdAt){db.update("insert into outbox(id,type,payload,created_at) values(?,?,?,?)",id,type,payload,createdAt);}
 public List<Map<String,Object>> findDue(long nowMillis){return db.queryForList("select * from outbox where delivered=false and next_attempt_at<=? order by created_at limit 20",nowMillis);}
 public void markDelivered(Object id){db.update("update outbox set delivered=true,attempts=attempts+1 where id=?",id);}
 public void scheduleRetry(Object id,long nextAttemptAtMillis){db.update("update outbox set attempts=attempts+1,next_attempt_at=? where id=?",nextAttemptAtMillis,id);}
}
