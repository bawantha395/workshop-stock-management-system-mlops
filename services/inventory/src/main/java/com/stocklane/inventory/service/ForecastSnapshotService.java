package com.stocklane.inventory.service;

import com.fasterxml.jackson.databind.*;
import java.time.*;
import java.util.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;
import software.amazon.awssdk.core.sync.RequestBody;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.*;

@Service
public class ForecastSnapshotService {
 private final ForecastHistoryService history;private final ObjectMapper json;private final String bucket;
 private S3Client client;
 public ForecastSnapshotService(ForecastHistoryService h,ObjectMapper json,@Value("${MODEL_BUCKET:}")String bucket){this.history=h;this.json=json;this.bucket=bucket;}
 private synchronized S3Client s3(){if(bucket.isBlank())throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"Forecast storage is not configured");if(client==null)client=S3Client.builder().overrideConfiguration(c->c.apiCallTimeout(Duration.ofSeconds(20)).apiCallAttemptTimeout(Duration.ofSeconds(8))).build();return client;}
 public Map<String,Object> prepare(String from,boolean confirmed,String actor){
  var data=history.snapshot(from,confirmed,actor);
  try{
   byte[] bytes=json.writeValueAsBytes(data);if(bytes.length>12*1024*1024)throw new IllegalArgumentException("History snapshot is too large; choose a shorter period");
   String hash=HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(bytes));
   String key="forecast/datasets/"+hash+"/history.json";
   s3().putObject(PutObjectRequest.builder().bucket(bucket).key(key).contentType("application/json").build(),RequestBody.fromBytes(bytes));
   byte[] pointer=json.writeValueAsBytes(Map.of("key",key,"sha256",hash,"asOf",data.get("asOf")));
   s3().putObject(PutObjectRequest.builder().bucket(bucket).key("forecast/datasets/latest.json").contentType("application/json").build(),RequestBody.fromBytes(pointer));
   return Map.of("datasetUri","s3://"+bucket+"/"+key,"message","History prepared. Run Train and publish stock forecast in GitHub Actions.");
  }catch(IllegalArgumentException e){throw e;}catch(Exception e){throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"Could not prepare forecast history. Verify storage permissions and retry.");}
 }
}
