-- People who receive parts at the storeroom counter, and who received each stock-out.
CREATE TABLE people(id VARCHAR(36) PRIMARY KEY, name VARCHAR(80) NOT NULL, active BOOLEAN NOT NULL DEFAULT TRUE, created_at VARCHAR(40) NOT NULL);
CREATE UNIQUE INDEX people_name ON people(name);
ALTER TABLE movements ADD COLUMN receiver_id VARCHAR(36);
CREATE INDEX movements_receiver ON movements(receiver_id);
