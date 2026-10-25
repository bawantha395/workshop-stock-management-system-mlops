package com.stocklane.platform;

import com.fasterxml.jackson.databind.*;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.time.Instant;
import java.util.*;
import java.util.function.Supplier;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionTemplate;

/** Records a command and its business writes in the SAME transaction. */
@Component
public class Commands {
 private final JdbcTemplate db; private final TransactionTemplate tx; private final ObjectMapper json;
 public Commands(JdbcTemplate db,org.springframework.transaction.PlatformTransactionManager tm,ObjectMapper json){this.db=db;this.tx=new TransactionTemplate(tm);this.json=json;}
 public Map<String,Object> execute(String key,String operation,Object body,Supplier<Map<String,Object>> work){
  if(key==null||!key.matches("[a-zA-Z0-9_-]{16,100}"))throw new IllegalArgumentException("A 16-100 character Idempotency-Key is required");
  String hash=hash(operation+"|"+actor()+"|"+encode(body));
  Map<String,Object> existing=replay(key,hash);if(existing!=null)return existing;
  try{return tx.execute(status->{
   db.update("insert into commands(id,request_hash,response,created_at) values(?,?,?,?)",key,hash,"",Instant.now().toString());
   Map<String,Object> result=work.get();
   db.update("update commands set response=? where id=?",encode(result),key);return result;
  });}catch(DuplicateKeyException race){Map<String,Object> response=replay(key,hash);if(response!=null)return response;throw race;}
 }
 @SuppressWarnings("unchecked") private Map<String,Object> replay(String id,String hash){
  var rows=db.queryForList("select request_hash,response from commands where id=?",id);if(rows.isEmpty())return null;
  if(!hash.equals(rows.getFirst().get("request_hash")))throw new Conflict("This request key was already used for different data");
  try{return json.readValue((String)rows.getFirst().get("response"),Map.class);}catch(Exception e){throw new IllegalStateException("Stored command response is invalid",e);}
 }
 public String encode(Object o){try{return json.writer().with(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS).writeValueAsString(o);}catch(Exception e){throw new IllegalArgumentException("Invalid JSON",e);}}
 public String hash(String s){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(s.getBytes(StandardCharsets.UTF_8)));}catch(Exception e){throw new IllegalStateException(e);}}
 public static String actor(){var a=SecurityContextHolder.getContext().getAuthentication();return a==null?"system":a.getName();}
 public static class Conflict extends RuntimeException{public Conflict(String s){super(s);}}
 public static class Missing extends RuntimeException{public Missing(String s){super(s);}}
}
