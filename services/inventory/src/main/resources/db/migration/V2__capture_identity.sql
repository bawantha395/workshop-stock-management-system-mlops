ALTER TABLE movements ADD COLUMN source_capture_id VARCHAR(36);
CREATE UNIQUE INDEX movements_capture_once ON movements(source_capture_id);
