package com.stocklane.workshop.repository;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** SQL for final invoices. */
@Repository
public class InvoiceRepository {
 private final JdbcTemplate db;
 public InvoiceRepository(JdbcTemplate db){this.db=db;}
 public List<Map<String,Object>> findAll(){return db.queryForList("select id,job_id,invoice_number,labour,total,revision,created_at,approved_by from invoices order by created_at desc");}
 public boolean exists(String id){return !db.queryForList("select id from invoices where id=?",id).isEmpty();}
 public void insert(String id,String jobId,String invoiceNumber,String snapshot,BigDecimal labour,BigDecimal total,long revision,Object createdAt,String approvedBy){
  db.update("insert into invoices(id,job_id,invoice_number,snapshot,labour,total,revision,created_at,approved_by) values(?,?,?,?,?,?,?,?,?)",id,jobId,invoiceNumber,snapshot,labour,total,revision,createdAt,approvedBy);
 }
}
