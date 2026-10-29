package com.stocklane.inventory.repository;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** SQL for the stock movement ledger. */
@Repository
public class MovementRepository {
 private final JdbcTemplate db;
 public MovementRepository(JdbcTemplate db){this.db=db;}
 public List<Map<String,Object>> findRecent(){return db.queryForList("select m.*,p.sku,p.name,p.unit,pe.name as receiver_name from movements m join products p on p.id=m.product_id left join people pe on pe.id=m.receiver_id order by m.created_at desc limit 200");}
 public List<Map<String,Object>> findByJob(String jobId){return db.queryForList("select m.*,p.sku,p.name,p.unit from movements m join products p on p.id=m.product_id where m.job_id=? order by m.created_at",jobId);}
 public Optional<Map<String,Object>> findById(String id){
  var rows=db.queryForList("select * from movements where id=?",id);
  return rows.isEmpty()?Optional.empty():Optional.of(rows.getFirst());
 }
 public Map<String,Object> getById(String id){return db.queryForMap("select * from movements where id=?",id);}
 public Optional<Map<String,Object>> findByCapture(String captureId){
  var rows=db.queryForList("select * from movements where source_capture_id=?",captureId);
  return rows.isEmpty()?Optional.empty():Optional.of(rows.getFirst());
 }
 public Optional<Map<String,Object>> findIssue(String issueId,String jobId,String productId){
  var rows=db.queryForList("select * from movements where id=? and kind='ISSUE' and job_id=? and product_id=?",issueId,jobId,productId);
  return rows.isEmpty()?Optional.empty():Optional.of(rows.getFirst());
 }
 public BigDecimal returnedQuantity(String issueId){return db.queryForObject("select coalesce(sum(quantity),0) from movements where issue_id=? and kind='RETURN'",BigDecimal.class,issueId);}
 public void insert(String id,String productId,String kind,BigDecimal quantity,BigDecimal unitPrice,String jobId,String issueId,String actor,String note,String createdAt,String sourceCaptureId,String receiverId){
  db.update("insert into movements(id,product_id,kind,quantity,unit_price,job_id,issue_id,actor,note,created_at,source_capture_id,receiver_id) values(?,?,?,?,?,?,?,?,?,?,?,?)",id,productId,kind,quantity,unitPrice,jobId,issueId,actor,note,createdAt,sourceCaptureId,receiverId);
 }
 /** A counter handover (stock out to a person) of this product. */
 public Optional<Map<String,Object>> findHandover(String id,String productId){
  var rows=db.queryForList("select * from movements where id=? and kind='STOCK_OUT' and product_id=? and receiver_id is not null",id,productId);
  return rows.isEmpty()?Optional.empty():Optional.of(rows.getFirst());
 }
 /** Recent counter handovers to one person, with the quantity already taken back. */
 public List<Map<String,Object>> handovers(String receiverId,String since){
  return db.queryForList("select m.id,m.product_id,p.sku,p.name,p.unit,m.quantity,m.created_at,coalesce((select sum(r.quantity) from movements r where r.issue_id=m.id and r.kind='RETURN'),0) as returned from movements m join products p on p.id=m.product_id where m.kind='STOCK_OUT' and m.receiver_id=? and m.created_at>=? order by m.created_at desc limit 100",receiverId,since);
 }
 /** Bulk insert of imported history rows: id, product_id, kind, quantity, unit_price, actor, note, created_at. */
 public void insertImported(List<Object[]> rows){db.batchUpdate("insert into movements(id,product_id,kind,quantity,unit_price,actor,note,created_at) values(?,?,?,?,?,?,?,?)",rows);}
 /** Net quantity per product still issued to a job (issues minus returns). */
 public List<Map<String,Object>> jobSnapshotLines(String jobId){
  return db.queryForList("select m.product_id,p.sku,p.name,p.unit,m.unit_price,sum(case when m.kind='ISSUE' then m.quantity else -m.quantity end) as quantity from movements m join products p on p.id=m.product_id where m.job_id=? and m.kind in ('ISSUE','RETURN') group by m.product_id,p.sku,p.name,p.unit,m.unit_price having sum(case when m.kind='ISSUE' then m.quantity else -m.quantity end)>0",jobId);
 }
}
