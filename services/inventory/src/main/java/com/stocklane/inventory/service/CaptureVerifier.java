package com.stocklane.inventory.service;
import com.stocklane.inventory.dto.MovementInput;
import com.stocklane.inventory.exception.ConflictException;
import java.time.Duration;
import java.util.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.http.client.JdkClientHttpRequestFactory;
@Component
public class CaptureVerifier {
 @Value("${app.vision-url}")String vision;@Value("${app.vision-read-token}")String token;
 private final RestClient http;
 public CaptureVerifier(){var factory=new JdkClientHttpRequestFactory(java.net.http.HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build());factory.setReadTimeout(Duration.ofSeconds(4));http=RestClient.builder().requestFactory(factory).build();}
 public void verify(MovementInput movement){
  if(movement.sourceCaptureId()==null)return;
  @SuppressWarnings("unchecked") Map<String,Object> capture=http.get().uri(vision+"/internal/captures/"+movement.sourceCaptureId()).header("X-Internal-Token",token).retrieve().body(Map.class);
  if(capture==null||!"PENDING".equals(capture.get("status")))throw new ConflictException("Capture is not pending review");
  String expected="IN".equals(capture.get("direction"))?"RECEIPT":(capture.get("job_id")==null?"STOCK_OUT":"ISSUE");
  if(!expected.equals(movement.kind()))throw new ConflictException("Movement direction disagrees with the capture station");
  if(capture.get("job_id")!=null&&!Objects.equals(capture.get("job_id"),movement.jobId()))throw new ConflictException("Capture belongs to a different repair job");
 }
}
