package com.stocklane.inventory;
import static org.assertj.core.api.Assertions.*;
import com.stocklane.platform.Commands;
import java.math.BigDecimal;
import java.util.*;
import java.util.concurrent.*;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.test.web.servlet.MockMvc;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@SpringBootTest(properties={"spring.datasource.url=jdbc:h2:mem:inventory-tests;MODE=PostgreSQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1","app.relay-delay=3600000"})
@ActiveProfiles("local") @AutoConfigureMockMvc
class InventoryTest {
 @Autowired StockAnalysis analysis;@Autowired Inventory inventory;@Autowired JdbcTemplate db;@Autowired MockMvc http;
 String id;
 String key(){return UUID.randomUUID().toString();}
 BigDecimal n(String s){return new BigDecimal(s);}
 Inventory.MovementInput move(String kind,String amount,String job,String issue){return new Inventory.MovementInput(kind,id,n(amount),job,issue,"test",null);}
 @BeforeEach void setup(){db.update("delete from product_audit");db.update("delete from outbox");db.update("delete from movements");db.update("delete from products");db.update("delete from job_gates");db.update("delete from commands");id=inventory.create(key(),new Inventory.ProductInput("MOB-5W30-4L","Mobil 5W-30 4L","Engine oil","Mobil","5W-30","4L",null,"UNIT",n("50"),n("5000"),n("5"),null,null)).get("id").toString();}
 @Test void receiptRetriesDoNotCreateExtraStock(){String key=key();var m=move("RECEIPT","10",null,null);var first=inventory.move(key,m);var retry=inventory.move(key,m);assertThat(first.get("id")).isEqualTo(retry.get("id"));assertThat((BigDecimal)inventory.product(id,false).get("quantity")).isEqualByComparingTo("60");}
 @Test void reusingKeyForDifferentBodyIsRejected(){String k=key();inventory.move(k,move("RECEIPT","10",null,null));assertThatThrownBy(()->inventory.move(k,move("RECEIPT","11",null,null))).isInstanceOf(Commands.Conflict.class);}
 @Test void identicalNewDeliveryGetsANewReceipt(){inventory.move(key(),move("RECEIPT","10",null,null));inventory.move(key(),move("RECEIPT","10",null,null));assertThat((BigDecimal)inventory.product(id,false).get("quantity")).isEqualByComparingTo("70");}
 @Test void overIssueRollsBackMovementAndCommand(){String job=key();inventory.openJob(job);String command=key();assertThatThrownBy(()->inventory.move(command,move("ISSUE","51",job,null))).isInstanceOf(Commands.Conflict.class);assertThat(db.queryForObject("select count(*) from commands where id=?",Integer.class,command)).isZero();assertThat(inventory.jobMovements(job)).isEmpty();}
 @Test void returnUsesOriginalPriceAndCannotExceedIssue(){String job=key();inventory.openJob(job);String issue=inventory.move(key(),move("ISSUE","2",job,null)).get("id").toString();db.update("update products set selling_price=6500 where id=?",id);inventory.move(key(),move("RETURN","1",job,issue));assertThatThrownBy(()->inventory.move(key(),move("RETURN","2",job,issue))).isInstanceOf(Commands.Conflict.class);var snapshot=inventory.snapshot(job);@SuppressWarnings("unchecked")var lines=(List<Map<String,Object>>)snapshot.get("lines");assertThat((BigDecimal)lines.getFirst().get("quantity")).isEqualByComparingTo("1");assertThat((BigDecimal)lines.getFirst().get("unit_price")).isEqualByComparingTo("5000");}
 @Test void frozenJobRejectsIssuesAndReturns(){String job=key();inventory.openJob(job);String issue=inventory.move(key(),move("ISSUE","2",job,null)).get("id").toString();inventory.freezeJob(job);assertThatThrownBy(()->inventory.move(key(),move("ISSUE","1",job,null))).isInstanceOf(Commands.Conflict.class);assertThatThrownBy(()->inventory.move(key(),move("RETURN","1",job,issue))).isInstanceOf(Commands.Conflict.class);}
 @Test void fractionalSealedBottleIsRejected(){assertThatThrownBy(()->inventory.move(key(),move("RECEIPT","1.5",null,null))).isInstanceOf(IllegalArgumentException.class);}
 @Test void jobIsRequiredBeforeIssue(){assertThatThrownBy(()->inventory.move(key(),move("ISSUE","1",key(),null))).isInstanceOf(Commands.Conflict.class);}
 @Test void concurrentIssuesCannotOverdraw() throws Exception {String job=key();inventory.openJob(job);try(var pool=Executors.newFixedThreadPool(2)){var tasks=List.<Callable<Boolean>>of(()->{try{inventory.move(key(),move("ISSUE","40",job,null));return true;}catch(Commands.Conflict e){return false;}},()->{try{inventory.move(key(),move("ISSUE","40",job,null));return true;}catch(Commands.Conflict e){return false;}});var results=pool.invokeAll(tasks);assertThat(results.stream().map(f->{try{return f.get();}catch(Exception e){throw new RuntimeException(e);}}).filter(Boolean::booleanValue).count()).isEqualTo(1);assertThat((BigDecimal)inventory.product(id,false).get("quantity")).isEqualByComparingTo("10");}}
 @Test void internalRoutesRequireServiceIdentity()throws Exception{http.perform(get("/internal/products/"+id)).andExpect(status().isUnauthorized());http.perform(get("/internal/products/"+id).header("X-Internal-Token","local-development-service-token-32-characters")).andExpect(status().isOk());}

 @Test void stockOutNeedsNoRepairJobAndIsIdempotent(){String k=key();var m=move("STOCK_OUT","2",null,null);inventory.move(k,m);inventory.move(k,m);assertThat((BigDecimal)inventory.product(id,false).get("quantity")).isEqualByComparingTo("48");assertThat(db.queryForObject("select count(*) from movements where kind='STOCK_OUT'",Integer.class)).isEqualTo(1);}
 @Test void stockOutCannotOverdraw(){assertThatThrownBy(()->inventory.move(key(),move("STOCK_OUT","51",null,null))).isInstanceOf(Commands.Conflict.class);assertThat((BigDecimal)inventory.product(id,false).get("quantity")).isEqualByComparingTo("50");}
 @Test void catalogueEditKeepsStableIdentityAndAudit(){inventory.edit(key(),id,new Inventory.ProductEdit("AC filter","Filters","Example","","", "AC-123","Shelf B",n("3")));assertThat(inventory.product(id,false).get("part_number")).isEqualTo("AC-123");assertThat((BigDecimal)inventory.product(id,false).get("quantity")).isEqualByComparingTo("50");assertThat(db.queryForObject("select count(*) from product_audit where product_id=?",Integer.class,id)).isEqualTo(1);}
 @Test void mechanicCannotEditCatalogue()throws Exception{http.perform(patch("/api/inventory/products/"+id).header("X-Demo-User","mechanic").header("Idempotency-Key",key()).contentType("application/json").content("{\"name\":\"test\"}")).andExpect(status().isForbidden());}
 @Test void archivePreservesHistoryAndBlocksMovements(){assertThatThrownBy(()->inventory.archive(key(),id,new Inventory.ArchiveInput(true))).isInstanceOf(Commands.Conflict.class);inventory.move(key(),move("STOCK_OUT","50",null,null));inventory.archive(key(),id,new Inventory.ArchiveInput(true));assertThat(inventory.products()).isEmpty();assertThat(inventory.archivedProducts()).hasSize(1);assertThatThrownBy(()->inventory.move(key(),move("RECEIPT","1",null,null))).isInstanceOf(Commands.Conflict.class);inventory.archive(key(),id,new Inventory.ArchiveInput(false));assertThat(inventory.products()).hasSize(1);}

 @Test void analysisSeparatesPastPeriodFromCurrentStock(){
  db.update("update movements set created_at='2025-01-01T00:00:00Z' where product_id=?",id);
  String incoming=inventory.move(key(),move("RECEIPT","10",null,null)).get("id").toString();
  String outgoing=inventory.move(key(),move("STOCK_OUT","2",null,null)).get("id").toString();
  String later=inventory.move(key(),move("RECEIPT","5",null,null)).get("id").toString();
  db.update("update movements set created_at='2025-01-02T00:00:00Z' where id=?",incoming);
  db.update("update movements set created_at='2025-01-03T00:00:00Z' where id=?",outgoing);
  db.update("update movements set created_at='2025-01-04T00:00:00Z' where id=?",later);
  @SuppressWarnings("unchecked") var rows=(List<Map<String,Object>>)analysis.summary("2025-01-02T00:00:00Z","2025-01-04T00:00:00Z","","",true,0).get("rows");
  var row=rows.getFirst();assertThat((BigDecimal)row.get("opening_quantity")).isEqualByComparingTo("50");assertThat((BigDecimal)row.get("added_quantity")).isEqualByComparingTo("10");assertThat((BigDecimal)row.get("taken_quantity")).isEqualByComparingTo("2");assertThat((BigDecimal)row.get("closing_quantity")).isEqualByComparingTo("58");assertThat((BigDecimal)row.get("available_now")).isEqualByComparingTo("63");
 }
 @Test void analysisUsesAllLedgerRowsBeyondActivityLimit(){
  db.update("update movements set created_at='2025-01-01T00:00:00Z' where product_id=?",id);
  for(int i=0;i<205;i++)db.update("insert into movements(id,product_id,kind,quantity,unit_price,actor,note,created_at) values(?,?,'RECEIPT',1,0,'test','','2025-01-02T12:00:00Z')",key(),id);
  db.update("update products set quantity=255 where id=?",id);
  @SuppressWarnings("unchecked") var rows=(List<Map<String,Object>>)analysis.summary("2025-01-02T00:00:00Z","2025-01-03T00:00:00Z","MOB","",true,0).get("rows");
  assertThat((BigDecimal)rows.getFirst().get("added_quantity")).isEqualByComparingTo("205");
 }
 @Test void dailyUsageGroupsBySriLankaDate(){
  String outgoing=inventory.move(key(),move("STOCK_OUT","2",null,null)).get("id").toString();db.update("update movements set created_at='2025-01-01T20:00:00Z' where id=?",outgoing);
  var daily=analysis.daily("2025-01-01T19:00:00Z","2025-01-02T19:00:00Z");assertThat(daily).hasSize(1);assertThat(daily.getFirst().get("date")).isEqualTo("2025-01-02");assertThat((BigDecimal)daily.getFirst().get("out_quantity")).isEqualByComparingTo("2");
 }
 @Test void mechanicsCannotAccessOwnerAnalysis()throws Exception{http.perform(get("/api/inventory/analysis").param("from","2025-01-01T00:00:00Z").param("until","2025-02-01T00:00:00Z").header("X-Demo-User","mechanic")).andExpect(status().isForbidden());}
 @Test void invalidAnalysisDatesAreRejected(){assertThatThrownBy(()->analysis.summary("invalid","2025-01-02T00:00:00Z","","",true,0)).isInstanceOf(IllegalArgumentException.class);assertThatThrownBy(()->analysis.summary("2025-02-01T00:00:00Z","2025-01-02T00:00:00Z","","",true,0)).isInstanceOf(IllegalArgumentException.class);}
 @Autowired ForecastHistory forecastHistory;
 @Test void forecastHistoryRequiresOwnerAndConfirmedTracking()throws Exception{
  http.perform(post("/api/inventory/analysis/forecast/history").header("X-Demo-User","mechanic").contentType("application/json").content("{\"historyFrom\":\"2026-01-01\",\"historyConfirmed\":true}")).andExpect(status().isForbidden());
  assertThatThrownBy(()->forecastHistory.snapshot("2026-01-01",false,"owner")).isInstanceOf(IllegalArgumentException.class);
 }
 @Test void forecastHistoryExcludesPartialRegistrationDayAndChecksLedger(){
  var today=java.time.LocalDate.now(java.time.ZoneId.of("Asia/Colombo"));
  var created=today.minusDays(35).atStartOfDay(java.time.ZoneId.of("Asia/Colombo")).toInstant().toString();
  db.update("update products set created_at=? where id=?",created,id);db.update("update movements set created_at=? where product_id=?",created,id);
  var snapshot=forecastHistory.snapshot(today.minusDays(40).toString(),true,"owner");
  @SuppressWarnings("unchecked") var rows=(List<Map<String,Object>>)snapshot.get("products");
  assertThat((List<?>)rows.getFirst().get("usage")).hasSize(34);
  assertThat(snapshot.get("historyUntil")).isEqualTo(today.toString());
  db.update("update products set quantity=49 where id=?",id);
  assertThatThrownBy(()->forecastHistory.snapshot(today.minusDays(40).toString(),true,"owner")).isInstanceOf(IllegalArgumentException.class).hasMessageContaining("Ledger");
 }
}
