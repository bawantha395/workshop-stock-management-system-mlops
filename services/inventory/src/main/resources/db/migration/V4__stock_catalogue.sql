ALTER TABLE products ADD COLUMN part_number VARCHAR(180);
ALTER TABLE products ADD COLUMN manufacturer_key VARCHAR(100);
ALTER TABLE products ADD COLUMN location VARCHAR(180) NOT NULL DEFAULT '';
ALTER TABLE products ADD COLUMN archived BOOLEAN NOT NULL DEFAULT FALSE;
CREATE UNIQUE INDEX products_manufacturer_part ON products(manufacturer_key,part_number);
CREATE TABLE product_audit(id VARCHAR(36) PRIMARY KEY, product_id VARCHAR(36) NOT NULL REFERENCES products(id), actor VARCHAR(180) NOT NULL, action VARCHAR(30) NOT NULL, details TEXT NOT NULL, created_at VARCHAR(40) NOT NULL);
