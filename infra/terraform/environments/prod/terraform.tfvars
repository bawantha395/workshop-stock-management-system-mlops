# prod: highly available and protected against accidental deletion.
environment         = "prod"
name                = "stocklane-prod"
deletion_protection = true

availability_zone_count = 3
nat_per_az              = true # one NAT gateway per AZ

node_instance_type = "m6i.large"
node_min_size      = 3
node_desired_size  = 3
node_max_size      = 6

application_replicas = 3

database_instance_class        = "db.t4g.small"
database_multi_az              = true
database_storage_type          = "gp3"
database_max_allocated_storage = 100
database_backup_retention_days = 14

cache_node_type  = "cache.t4g.small"
cache_node_count = 2

monthly_budget_usd = 300
