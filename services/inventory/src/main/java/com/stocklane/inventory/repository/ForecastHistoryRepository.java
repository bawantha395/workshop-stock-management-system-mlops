package com.stocklane.inventory.repository;

import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** Read-only queries that feed the stock-usage history used for forecasting. */
@Repository
public class ForecastHistoryRepository {
 private final JdbcTemplate db;
 public ForecastHistoryRepository(JdbcTemplate db){this.db=db;}
 /** Active items; one extra row is fetched so the caller can detect the 1000-item limit. */
 public List<Map<String,Object>> activeProducts(){return db.queryForList("select id,sku,name,unit,quantity,created_at from products where archived=false order by id limit 1001");}
 /** The whole ledger; one extra row is fetched so the caller can detect the 200000-row limit. */
 public List<Map<String,Object>> allMovements(){return db.queryForList("select product_id,kind,quantity,created_at from movements order by created_at limit 200001");}
}
