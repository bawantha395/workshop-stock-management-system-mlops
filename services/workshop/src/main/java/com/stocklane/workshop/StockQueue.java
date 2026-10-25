package com.stocklane.workshop;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import software.amazon.awssdk.services.sqs.SqsClient;
@Component
public class StockQueue {
 private final Workshop workshop;private final ObjectMapper json;private SqsClient sqs;
 @Value("${app.event-mode}")String mode;@Value("${app.stock-queue}")String queue;
 public StockQueue(Workshop workshop,ObjectMapper json){this.workshop=workshop;this.json=json;}
 @Scheduled(fixedDelay=2000) void poll(){if(!mode.equals("sqs")||queue.isBlank())return;
  try{if(sqs==null)sqs=SqsClient.create();for(var message:sqs.receiveMessage(b->b.queueUrl(queue).maxNumberOfMessages(10).waitTimeSeconds(2)).messages()){
    try{workshop.consume(json.readValue(message.body(),new com.fasterxml.jackson.core.type.TypeReference<java.util.Map<String,Object>>(){}));sqs.deleteMessage(b->b.queueUrl(queue).receiptHandle(message.receiptHandle()));}catch(Exception e){/* no delete: retry, then redrive to DLQ */}
  }}catch(Exception e){/* readiness and alarms must also monitor SQS age */}
 }
}
