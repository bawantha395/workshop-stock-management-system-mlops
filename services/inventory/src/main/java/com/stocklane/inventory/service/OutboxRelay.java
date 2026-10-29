package com.stocklane.inventory.service;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.stocklane.inventory.repository.OutboxRepository;
import java.util.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import software.amazon.awssdk.services.sqs.SqsClient;
@Component
public class OutboxRelay {
 private final OutboxRepository outbox;private final ObjectMapper json;private final Commands commands;private SqsClient sqs;
 @Value("${app.event-mode}") String mode;@Value("${app.workshop-url}")String workshop;@Value("${app.vision-url}")String vision;@Value("${app.internal-token}")String token;
 @Value("${app.stock-queue}")String stockQueue;@Value("${app.catalogue-queue}")String catalogueQueue;
 public OutboxRelay(OutboxRepository outbox,ObjectMapper json,Commands c){this.outbox=outbox;this.json=json;this.commands=c;}
 @Scheduled(fixedDelayString="${app.relay-delay:2000}") public void run(){
  for(var row:outbox.findDue(System.currentTimeMillis())){
   try{
    String type=(String)row.get("type");String envelope=commands.encode(Map.of("eventId",row.get("id"),"type",type,"payload",json.readValue((String)row.get("payload"),Map.class)));
    if(mode.equals("http"))RestClient.create().post().uri((type.equals("STOCK_MOVED")?workshop:vision)+"/internal/events").header("X-Internal-Token",token).header("Content-Type","application/json").body(envelope).retrieve().toBodilessEntity();
    else{if(sqs==null)sqs=SqsClient.create();String queue=type.equals("STOCK_MOVED")?stockQueue:catalogueQueue;if(queue.isBlank())throw new IllegalStateException("Queue URL missing");sqs.sendMessage(b->b.queueUrl(queue).messageBody(envelope));}
    outbox.markDelivered(row.get("id"));
   }catch(Exception e){long backoff=Math.min(60000,1000L << Math.min(6,((Number)row.get("attempts")).intValue()));outbox.scheduleRetry(row.get("id"),System.currentTimeMillis()+backoff);}
  }
 }
}
