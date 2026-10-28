# dev: smallest working size, destroyed after each demo.
environment         = "dev"
name                = "stocklane-dev"
deletion_protection = false

availability_zone_count = 2
nat_per_az              = false # one shared NAT gateway

node_instance_type = "m7i-flex.large"
node_min_size      = 2
node_desired_size  = 2
node_max_size      = 2

application_replicas = 1

database_instance_class        = "db.t4g.micro"
database_multi_az              = false
database_storage_type          = "gp2"
database_max_allocated_storage = 0
database_backup_retention_days = 1

cache_node_type  = "cache.t4g.micro"
cache_node_count = 2

monthly_budget_usd = 25
