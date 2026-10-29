package com.stocklane.workshop.controller;
import com.stocklane.workshop.dto.InvoiceInput;
import com.stocklane.workshop.dto.JobInput;
import com.stocklane.workshop.service.WorkshopService;
import java.util.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.http.*;
@RestController
public class WorkshopController {
 private final WorkshopService workshop;public WorkshopController(WorkshopService workshop){this.workshop=workshop;}
 @GetMapping("/api/workshop/jobs") @PreAuthorize("hasAnyRole('OWNER','MECHANIC')") Object jobs(){return workshop.jobs();}
 @PostMapping("/api/workshop/jobs") @PreAuthorize("hasAnyRole('OWNER','MECHANIC')") Object create(@RequestHeader("Idempotency-Key")String key,@RequestBody JobInput input){return workshop.create(key,input);}
 @GetMapping("/api/workshop/jobs/{id}/allocations") @PreAuthorize("hasAnyRole('OWNER','MECHANIC')") Object allocations(@PathVariable String id){return workshop.allocations(id);}
 @PostMapping("/api/workshop/jobs/{id}/invoice") @PreAuthorize("hasAnyRole('OWNER','MECHANIC')") Object invoice(@PathVariable String id,@RequestHeader("Idempotency-Key")String key,@RequestBody InvoiceInput input){return workshop.finalise(id,key,input);}
 @GetMapping("/api/workshop/invoices") @PreAuthorize("hasAnyRole('OWNER','MECHANIC')") Object invoices(){return workshop.invoices();}
 @GetMapping("/api/workshop/invoices/{id}/pdf") @PreAuthorize("hasAnyRole('OWNER','MECHANIC')") ResponseEntity<byte[]> pdf(@PathVariable String id){return ResponseEntity.ok().contentType(MediaType.APPLICATION_PDF).header("Content-Disposition","attachment; filename=invoice-"+id+".pdf").body(workshop.pdf(id));}
 @PostMapping("/internal/events") Object consume(@RequestBody Map<String,Object> event){workshop.consume(event);return Map.of("accepted",true);}
}
