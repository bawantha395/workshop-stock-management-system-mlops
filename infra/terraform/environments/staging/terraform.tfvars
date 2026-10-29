# staging: production-like layout at reduced size, destroyed when not in use.
environment         = "staging"
name                = "stocklane-staging"
deletion_protection = false

availability_zone_count = 2
nat_per_az              = false

node_instance_type = "m7i-flex.large"
node_min_size      = 2
node_desired_size  = 2
node_max_size      = 3

application_replicas = 2

database_instance_class        = "db.t4g.small"
database_multi_az              = false
database_storage_type          = "gp3"
database_max_allocated_storage = 40
database_backup_retention_days = 3

cache_node_type  = "cache.t4g.micro"
cache_node_count = 2

monthly_budget_usd = 60

# Argo CD and Grafana sign in with admin / admin (still limited to admin_allowed_cidrs).
demo_admin_credentials = true
