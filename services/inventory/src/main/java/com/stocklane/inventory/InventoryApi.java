package com.stocklane.inventory;
import java.util.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
@RestController
public class InventoryApi {
 private final Inventory inventory;
 public InventoryApi(Inventory inventory){this.inventory=inventory;}
 @GetMapping("/api/inventory/session") Object session(Authentication a){return Map.of("name",a.getName(),"roles",a.getAuthorities().stream().map(Object::toString).toList());}
 @GetMapping("/api/inventory/products") @PreAuthorize("hasAnyRole('OWNER','MECHANIC')") Object products(){return inventory.products();}
 @GetMapping(value="/api/inventory/catalogue",produces="application/json") @PreAuthorize("hasAnyRole('OWNER','MECHANIC')") String catalogue(){return inventory.catalogue();}
 @PostMapping("/api/inventory/products") @PreAuthorize("hasAnyRole('OWNER','MECHANIC')") Object create(@RequestHeader("Idempotency-Key")String key,@RequestBody Inventory.ProductInput p){return inventory.create(key,p);}
 @GetMapping("/api/inventory/movements") @PreAuthorize("hasAnyRole('OWNER','MECHANIC')") Object movements(){return inventory.movements();}
 @PostMapping("/api/inventory/movements") @PreAuthorize("hasAnyRole('OWNER','MECHANIC')") Object move(@RequestHeader("Idempotency-Key")String key,@RequestBody Inventory.MovementInput m){if("OPENING".equals(m.kind()))throw new IllegalArgumentException("Opening stock is recorded during product registration");return inventory.move(key,m);}
 @GetMapping("/api/inventory/jobs/{id}/snapshot") @PreAuthorize("hasAnyRole('OWNER','MECHANIC')") Object snapshot(@PathVariable String id){return inventory.snapshot(id);}
 @PutMapping("/internal/jobs/{id}") Object open(@PathVariable String id){return inventory.openJob(id);}
 @GetMapping("/internal/products/{id}") Object product(@PathVariable String id){return inventory.product(id,false);}
 @GetMapping("/internal/movements/{id}") Object movement(@PathVariable String id){return inventory.movementById(id);}
 @GetMapping("/internal/catalogue") Object internalCatalogue(){return inventory.products();}
 @GetMapping("/api/inventory/captures/{id}/movement") @PreAuthorize("hasAnyRole('OWNER','MECHANIC')") Object captureMovement(@PathVariable String id){Map<String,Object> result=new HashMap<>();result.put("movement",inventory.captureMovement(id));return result;}
 @GetMapping("/api/inventory/jobs/{id}/movements") @PreAuthorize("hasAnyRole('OWNER','MECHANIC')") Object jobMoves(@PathVariable String id){return inventory.jobMovements(id);}
 @PostMapping("/internal/jobs/{id}/freeze") Object freeze(@PathVariable String id){return inventory.freezeJob(id);}
}
