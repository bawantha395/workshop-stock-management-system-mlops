package com.stocklane.inventory.controller;
import com.stocklane.inventory.dto.ArchiveInput;
import com.stocklane.inventory.dto.ForecastSnapshotRequest;
import com.stocklane.inventory.dto.MovementInput;
import com.stocklane.inventory.dto.ProductEdit;
import com.stocklane.inventory.dto.ProductInput;
import com.stocklane.inventory.dto.PersonInput;
import com.stocklane.inventory.service.ForecastSnapshotService;
import com.stocklane.inventory.service.InventoryService;
import com.stocklane.inventory.service.PeopleService;
import com.stocklane.inventory.service.StockAnalysisService;
import java.util.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
@RestController
public class InventoryController {
 private final InventoryService inventory;private final StockAnalysisService analysis;private final ForecastSnapshotService forecast;private final PeopleService people;
 public InventoryController(InventoryService inventory,StockAnalysisService analysis,ForecastSnapshotService forecast,PeopleService people){this.inventory=inventory;this.analysis=analysis;this.forecast=forecast;this.people=people;}
 @PostMapping("/api/inventory/analysis/forecast/history") @PreAuthorize("hasRole('OWNER')") Object forecastHistory(@RequestBody ForecastSnapshotRequest body,Authentication actor){return forecast.prepare(body.historyFrom(),body.historyConfirmed(),actor.getName());}
 @GetMapping("/api/inventory/people") @PreAuthorize("hasAnyRole('OWNER','MECHANIC')") Object people(){return people.list();}
 @PostMapping("/api/inventory/people") @PreAuthorize("hasRole('OWNER')") Object addPerson(@RequestHeader("Idempotency-Key")String key,@RequestBody PersonInput body){return people.add(key,body);}
 @DeleteMapping("/api/inventory/people/{id}") @PreAuthorize("hasRole('OWNER')") Object removePerson(@PathVariable String id){return people.remove(id);}
 @GetMapping("/api/inventory/people/{id}/handovers") @PreAuthorize("hasAnyRole('OWNER','MECHANIC')") Object handovers(@PathVariable String id){return inventory.handovers(id);}
 @GetMapping("/api/inventory/analysis") @PreAuthorize("hasRole('OWNER')") Object analysis(@RequestParam String from,@RequestParam String until,@RequestParam(defaultValue="")String search,@RequestParam(defaultValue="")String category,@RequestParam(defaultValue="true")boolean archived,@RequestParam(defaultValue="0")int page){return analysis.summary(from,until,search,category,archived,page);}
 @GetMapping("/api/inventory/analysis/daily") @PreAuthorize("hasRole('OWNER')") Object daily(@RequestParam String from,@RequestParam String until){return analysis.daily(from,until);}
 @GetMapping("/api/inventory/session") Object session(Authentication a){return Map.of("name",a.getName(),"roles",a.getAuthorities().stream().map(Object::toString).toList());}
 @GetMapping("/api/inventory/products") @PreAuthorize("hasAnyRole('OWNER','MECHANIC')") Object products(){return inventory.products();}
 @GetMapping(value="/api/inventory/catalogue",produces="application/json") @PreAuthorize("hasAnyRole('OWNER','MECHANIC')") String catalogue(){return inventory.catalogue();}
 @PostMapping("/api/inventory/products") @PreAuthorize("hasAnyRole('OWNER','MECHANIC')") Object create(@RequestHeader("Idempotency-Key")String key,@RequestBody ProductInput p){return inventory.create(key,p);}
 @GetMapping("/api/inventory/products/archived") @PreAuthorize("hasRole('OWNER')") Object archived(){return inventory.archivedProducts();}
 @PatchMapping("/api/inventory/products/{id}") @PreAuthorize("hasRole('OWNER')") Object edit(@PathVariable String id,@RequestHeader("Idempotency-Key")String key,@RequestBody ProductEdit p){return inventory.edit(key,id,p);}
 @PostMapping("/api/inventory/products/{id}/archive") @PreAuthorize("hasRole('OWNER')") Object archive(@PathVariable String id,@RequestHeader("Idempotency-Key")String key,@RequestBody ArchiveInput p){return inventory.archive(key,id,p);}
 @GetMapping("/api/inventory/movements") @PreAuthorize("hasAnyRole('OWNER','MECHANIC')") Object movements(){return inventory.movements();}
 @PostMapping("/api/inventory/movements") @PreAuthorize("hasAnyRole('OWNER','MECHANIC')") Object move(@RequestHeader("Idempotency-Key")String key,@RequestBody MovementInput m){if("OPENING".equals(m.kind()))throw new IllegalArgumentException("Opening stock is recorded during product registration");return inventory.move(key,m);}
 @GetMapping("/api/inventory/jobs/{id}/snapshot") @PreAuthorize("hasAnyRole('OWNER','MECHANIC')") Object snapshot(@PathVariable String id){return inventory.snapshot(id);}
 @PutMapping("/internal/jobs/{id}") Object open(@PathVariable String id){return inventory.openJob(id);}
 @GetMapping("/internal/products/{id}") Object product(@PathVariable String id){return inventory.product(id,false);}
 @GetMapping("/internal/movements/{id}") Object movement(@PathVariable String id){return inventory.movementById(id);}
 @GetMapping("/internal/catalogue") Object internalCatalogue(){return inventory.products();}
 @GetMapping("/api/inventory/jobs/{id}/movements") @PreAuthorize("hasAnyRole('OWNER','MECHANIC')") Object jobMoves(@PathVariable String id){return inventory.jobMovements(id);}
 @PostMapping("/internal/jobs/{id}/freeze") Object freeze(@PathVariable String id){return inventory.freezeJob(id);}
}
