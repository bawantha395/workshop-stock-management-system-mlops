package com.stocklane.workshop;
import static org.assertj.core.api.Assertions.*;
import java.util.*;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import com.stocklane.workshop.exception.ConflictException;
import com.stocklane.workshop.service.WorkshopService;
@SpringBootTest(properties="spring.datasource.url=jdbc:h2:mem:workshop-tests;MODE=PostgreSQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1") @ActiveProfiles("local")
class ProjectionTest {
 @Autowired WorkshopService workshop;@Autowired JdbcTemplate db;
 @BeforeEach void clear(){db.update("delete from allocations");db.update("delete from processed_events");}
 Map<String,Object> event(){Map<String,Object> p=new HashMap<>(Map.of("id",UUID.randomUUID().toString(),"job_id",UUID.randomUUID().toString(),"product_id",UUID.randomUUID().toString(),"sku","OIL-4L","name","Oil 4L","unit","UNIT","kind","ISSUE","quantity",2,"unit_price",5000,"created_at","2026-10-25T00:00:00Z"));return new HashMap<>(Map.of("eventId",UUID.randomUUID().toString(),"type","STOCK_MOVED","payload",p));}
 @Test void redeliveredEventIsAppliedOnce(){var e=event();workshop.consume(e);workshop.consume(e);assertThat(db.queryForObject("select count(*) from allocations",Integer.class)).isEqualTo(1);assertThat(db.queryForObject("select count(*) from processed_events",Integer.class)).isEqualTo(1);}
 @Test void reusedEventIdCannotChangeItsPayload(){var e=event();workshop.consume(e);@SuppressWarnings("unchecked")var payload=(Map<String,Object>)e.get("payload");payload.put("quantity",3);assertThatThrownBy(()->workshop.consume(e)).isInstanceOf(ConflictException.class);assertThat(db.queryForObject("select quantity from allocations",java.math.BigDecimal.class)).isEqualByComparingTo("2");}
 @Test void ordinaryStockEventsAreAcknowledgedWithoutCreatingRepairAllocations(){
  for(String kind:List.of("OPENING","RECEIPT","STOCK_OUT")){
   var e=event();@SuppressWarnings("unchecked")var payload=(Map<String,Object>)e.get("payload");
   payload.put("kind",kind);payload.put("job_id",null);payload.put("issue_id",null);
   workshop.consume(e);workshop.consume(e);
  }
  assertThat(db.queryForObject("select count(*) from processed_events",Integer.class)).isEqualTo(3);
  assertThat(db.queryForObject("select count(*) from allocations",Integer.class)).isZero();
 }
 @Test void unsupportedStockKindIsNotAcknowledged(){
  var e=event();@SuppressWarnings("unchecked")var payload=(Map<String,Object>)e.get("payload");payload.put("kind","INVALID");
  assertThatThrownBy(()->workshop.consume(e)).isInstanceOf(IllegalArgumentException.class);
  assertThat(db.queryForObject("select count(*) from processed_events",Integer.class)).isZero();
 }
}
