package com.stocklane.inventory.repository;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** SQL for the catalogue (products) and its audit trail. */
@Repository
public class ProductRepository {
 private final JdbcTemplate db;
 public ProductRepository(JdbcTemplate db){this.db=db;}
 public List<Map<String,Object>> findActive(){return db.queryForList("select * from products where archived=FALSE order by created_at desc,sku");}
 public List<Map<String,Object>> findArchived(){return db.queryForList("select * from products where archived=TRUE order by sku");}
 public Optional<Map<String,Object>> findById(String id,boolean lock){
  var rows=db.queryForList("select * from products where id=?"+(lock?" for update":""),id);
  return rows.isEmpty()?Optional.empty():Optional.of(rows.getFirst());
 }
 /** Compact catalogue used by the web app and the vision service; cached by the service. */
 public List<Map<String,Object>> catalogueRows(){return db.queryForList("select id,sku,name,category,brand,grade,capacity,barcode,unit,selling_price,reorder_level,image_id,part_number,location,archived from products where archived=FALSE order by sku");}
 public void insert(String id,String sku,String name,String category,String brand,String grade,String capacity,String barcode,String unit,BigDecimal sellingPrice,BigDecimal reorderLevel,String imageId,String createdAt){
  db.update("insert into products(id,sku,name,category,brand,grade,capacity,barcode,unit,quantity,selling_price,reorder_level,image_id,created_at) values(?,?,?,?,?,?,?,?,?,0,?,?,?,?)",id,sku,name,category,brand,grade,capacity,barcode,unit,sellingPrice,reorderLevel,imageId,createdAt);
 }
 public void updateCatalogueKeys(String id,String manufacturerKey,String partNumber,String location){db.update("update products set manufacturer_key=?,part_number=?,location=? where id=?",manufacturerKey,partNumber,location,id);}
 public void updateCatalogue(String id,String name,String category,String brand,String manufacturerKey,String grade,String capacity,String partNumber,String location,BigDecimal reorderLevel){
  db.update("update products set name=?,category=?,brand=?,manufacturer_key=?,grade=?,capacity=?,part_number=?,location=?,reorder_level=? where id=?",name,category,brand,manufacturerKey,grade,capacity,partNumber,location,reorderLevel,id);
 }
 public void updateQuantity(String id,BigDecimal quantity){db.update("update products set quantity=? where id=?",quantity,id);}
 public void updateArchived(String id,boolean archived){db.update("update products set archived=? where id=?",archived,id);}
 public void insertAudit(String auditId,String productId,String actor,String action,String details,String createdAt){
  db.update("insert into product_audit(id,product_id,actor,action,details,created_at) values(?,?,?,?,?,?)",auditId,productId,actor,action,details,createdAt);
 }
}
