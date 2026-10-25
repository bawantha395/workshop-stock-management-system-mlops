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
 @Autowired Inventory inventory;@Autowired JdbcTemplate db;@Autowired MockMvc http;
 String id;
 String key(){return UUID.randomUUID().toString();}
 BigDecimal n(String s){return new BigDecimal(s);}
 Inventory.MovementInput move(String kind,String amount,String job,String issue){return new Inventory.MovementInput(kind,id,n(amount),job,issue,"test",null);}
 @BeforeEach void setup(){db.update("delete from outbox");db.update("delete from movements");db.update("delete from products");db.update("delete from job_gates");db.update("delete from commands");id=inventory.create(key(),new Inventory.ProductInput("MOB-5W30-4L","Mobil 5W-30 4L","Engine oil","Mobil","5W-30","4L",null,"UNIT",n("50"),n("5000"),n("5"),null,null)).get("id").toString();}
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
}
