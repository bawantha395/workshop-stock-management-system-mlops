package com.stocklane.inventory.service;

import com.stocklane.inventory.repository.ForecastHistoryRepository;
import java.time.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * Exports the forecast history to S3 every night, so the scheduled forecast workflow
 * always has fresh history and nobody has to press "Prepare forecast history".
 * History runs from the first recorded movement (at most three years back). Exports are
 * content-addressed, so several replicas exporting the same night write the same object.
 */
@Component
public class ForecastExportService {
 private static final Logger log=LoggerFactory.getLogger(ForecastExportService.class);
 private final ForecastSnapshotService snapshots;private final ForecastHistoryRepository history;
 private final boolean enabled;private final String bucket;
 public ForecastExportService(ForecastSnapshotService snapshots,ForecastHistoryRepository history,
   @Value("${app.forecast.nightly-export:true}")boolean enabled,@Value("${MODEL_BUCKET:}")String bucket){
  this.snapshots=snapshots;this.history=history;this.enabled=enabled;this.bucket=bucket;
 }
 @Scheduled(cron="${app.forecast.export-cron:0 30 1 * * *}",zone="Asia/Colombo")
 public void run(){export(LocalDate.now(ZoneId.of("Asia/Colombo")));}
 /** Returns the history start that was exported, or null when there was nothing to export. */
 public String export(LocalDate today){
  if(!enabled||bucket.isBlank())return null;
  try{
   String first=history.firstMovementAt();
   if(first==null){log.info("Nightly forecast export skipped: no stock movements yet");return null;}
   LocalDate start=Instant.parse(first).atZone(ZoneId.of("Asia/Colombo")).toLocalDate(),earliest=today.minusDays(1095);
   if(start.isBefore(earliest))start=earliest;
   if(!start.isBefore(today))start=today;
   snapshots.prepare(start.toString(),true,"nightly-export");
   log.info("Nightly forecast export written from {}",start);return start.toString();
  }catch(RuntimeException e){log.warn("Nightly forecast export failed: {}",e.getMessage());return null;}
 }
}
