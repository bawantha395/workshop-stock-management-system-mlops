package com.stocklane.inventory.service;

import com.fasterxml.jackson.databind.*;
import com.stocklane.inventory.exception.ConflictException;
import com.stocklane.inventory.repository.CommandRepository;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.time.Instant;
import java.util.*;
import java.util.function.Supplier;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionTemplate;

/** Records a command and its business writes in the SAME transaction. */
@Component
public class Commands {
 private final CommandRepository repository; private final TransactionTemplate tx; private final ObjectMapper json;
 public Commands(CommandRepository repository,org.springframework.transaction.PlatformTransactionManager tm,ObjectMapper json){this.repository=repository;this.tx=new TransactionTemplate(tm);this.json=json;}
 public Map<String,Object> execute(String key,String operation,Object body,Supplier<Map<String,Object>> work){
  if(key==null||!key.matches("[a-zA-Z0-9_-]{16,100}"))throw new IllegalArgumentException("A 16-100 character Idempotency-Key is required");
  String hash=hash(operation+"|"+actor()+"|"+encode(body));
  Map<String,Object> existing=replay(key,hash);if(existing!=null)return existing;
  try{return tx.execute(status->{
   repository.insert(key,hash,Instant.now().toString());
   Map<String,Object> result=work.get();
   repository.updateResponse(key,encode(result));return result;
  });}catch(DuplicateKeyException race){Map<String,Object> response=replay(key,hash);if(response!=null)return response;throw race;}
 }
 @SuppressWarnings("unchecked") private Map<String,Object> replay(String id,String hash){
  var row=repository.find(id);if(row.isEmpty())return null;
  if(!hash.equals(row.get().get("request_hash")))throw new ConflictException("This request key was already used for different data");
  try{return json.readValue((String)row.get().get("response"),Map.class);}catch(Exception e){throw new IllegalStateException("Stored command response is invalid",e);}
 }
 public String encode(Object o){try{return json.writer().with(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS).writeValueAsString(o);}catch(Exception e){throw new IllegalArgumentException("Invalid JSON",e);}}
 public String hash(String s){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(s.getBytes(StandardCharsets.UTF_8)));}catch(Exception e){throw new IllegalStateException(e);}}
 public static String actor(){var a=SecurityContextHolder.getContext().getAuthentication();return a==null?"system":a.getName();}
}
